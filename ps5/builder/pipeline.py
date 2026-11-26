"""PS5 Longshot Plus Builder: the title folder made from a game file and the kit, on Linux, macOS or Windows.

    python pipeline.py --game <game.nup | folder with exefs/> --out <folder> [--kit <kit>] [--work <folder>] [--jobs N]

The kit (ps5/builder/make_kit.py) holds everything of the title that is not made from the game, compiled already. This
adds the game's part, on this PC and from the player's own copy:

  1. the game's program is read out of the game file (its exefs: about 50 MB, not the game's 25 GB);
  2. it is translated to C (the kit's lifter, nx2/lift.py);
  3. the C is compiled for the console (clang);
  4. it is linked with the kit's objects and libraries (ld.lld) and made the console's executable (ps5-native-tool);
  5. the title folder is laid out: <out>/<title id>, to copy to /data/homebrew on the console.

Nothing made here may be shared: eboot.bin and image.bin are made from the game.

The tools: clang, ld.lld, llvm-nm and ps5-native-tool, looked for in --tools, in LONGSHOT_PS5_TOOLS, in a tools/bin folder
beside the kit, then on PATH. Lines starting with "@@" are for the window (ps5/builder/app.py): "@@step <n> <of> <name>",
"@@progress <done> <total>", "@@done <folder>", "@@error <text>".
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = ".exe" if os.name == "nt" else ""
# The console the title is made for. attribute3 (sce_sys/param.json) is read by the console's kernel at each start: the Pro's
# value asks for its High CPU Frequency mode and its larger memory (13,232 MiB of direct memory); the base value starts the
# title as a base-generation process (12,016 MiB), on a Pro too, where it was measured: Kokiri Forest plays with 1.9 GB free
# at the least, against the Pro mode's 3.2 GB. With that much less room the base profile keeps PS5_Hookshot's 512-texel
# textures (the Pro's 1024 take 135 MB more in the forest). The switches go in longshot_env.txt in the title folder, which
# the title reads at its start (host/hos_main.c); a line the player adds there afterwards is theirs.
MODELS = {
    "base": {
        "name": "PS5 / PS5 Slim",
        "attribute3": 0x140040,
        "env": {
            "RX_VK_COMPILE_SHADERS": "most",
            "RX_VK_TEX_MAX_DIM": "512",
            "RX_VK_TEX_SKIP_MB": "2",
            "RX_VK_WB_MAX_KB": "1024",
            "HOS_PS5_ZERO_FIRST": "1",
            "RX_VK_IMPORT_CHUNK_MB": "4",
            "RX_VK_IMPORT_SPAN_MB": "16",
            "RX_VK_EXACT_STALE": "1",
            "HOS_PS5_RENDER_MB": "2560",
            "HOS_PS5_TEX_RESERVE_MB": "1800",
            # (the title closes itself under 400 MiB free, not 220: a base console's kernel panicked at 1024 textures)
            "HOS_PS5_MEM_FLOOR_MB": "400",
            "RX_VK_EVICT_MIN_UNUSED": "30",
        },
    },
    "pro": {
        "name": "PS5 Pro",
        "attribute3": 0x8540040,
        "env": {
            "RX_VK_COMPILE_SHADERS": "most",
            "RX_VK_TEX_MAX_DIM": "1024",
            "RX_VK_TEX_SKIP_MB": "64",
            "RX_VK_WB_MAX_KB": "1024",
            "HOS_PS5_ZERO_FIRST": "1",
            "RX_VK_IMPORT_CHUNK_MB": "4",
            "RX_VK_IMPORT_SPAN_MB": "16",
            "RX_VK_EXACT_STALE": "1",
            "HOS_PS5_RENDER_MB": "3584",
            "HOS_PS5_TEX_RESERVE_MB": "1600",
            "RX_VK_EVICT_MIN_UNUSED": "60",
        },
    },
}
STEPS = ["Reading the game's program", "Translating it to C", "Compiling for the console", "Linking", "Making the title folder",
         "Listing the game's shaders", "Extracting the game's data", "Downloading the amiibo"]


class Stop(Exception):
    pass


def say(text):
    print(text, flush=True)


def step(n):
    say("@@step %d %d %s" % (n, len(STEPS), STEPS[n - 1]))


def find_kit(given):
    for d in (given, os.environ.get("LONGSHOT_PS5_KIT"), os.path.join(HERE, "kit"), os.path.join(HERE, "..", "kit"),
              os.path.join(HERE, "..", "..", "dist", "kit")):
        if d and os.path.exists(os.path.join(d, "kit.json")):
            return os.path.abspath(d)
    raise Stop("the kit was not found (kit.json): give its folder with --kit")


def find_tool(name, kit, given):
    dirs = [given, os.environ.get("LONGSHOT_PS5_TOOLS"), os.path.join(kit, "..", "tools", "bin"), os.path.join(kit, "tools", "bin")]
    for d in dirs:
        if d and os.path.exists(os.path.join(d, name + EXE)):
            return os.path.abspath(os.path.join(d, name + EXE))
    found = shutil.which(name)
    if found:
        return found
    raise Stop("%s was not found: it comes with the builder (tools/bin); --tools names another folder" % name)


def available_gb():
    try:
        if os.name == "nt":
            import ctypes

            class M(ctypes.Structure):
                _fields_ = [("n", ctypes.c_ulong), ("load", ctypes.c_ulong)] + [(k, ctypes.c_ulonglong) for k in
                                                                               ("total", "avail", "a", "b", "c", "d", "e")]
            m = M()
            m.n = ctypes.sizeof(M)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.avail / 2**30
        if sys.platform == "darwin":
            pages = int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout or 0)
            return pages / 2**30 / 2   # (no "available" figure there: half of what the Mac has)
        for line in open("/proc/meminfo"):
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 2**20
    except Exception:
        pass
    return None


# The build's memory (measured on Zelda's real game with the kit's tools, the processes' PSS summed). The translation in one
# process: 1.85 GB at its peak (nx2/compact_bodies.py; 5.05 GB before). Each further process is a forked copy that comes to own
# ~0.5-0.7 GB of it (Python's reference counts write to the shared pages: the instruction texts every worker reads), and with
# several there is one more beside them (chunks.start_side): 7 took 5.6 GB (11.7 GB before, with 8). The compile: mem_need, Gate
MIN_MEMORY_GB = 2     # (--memory's least: the translation in one process; compiles of ~0.9 GB, one at a time)
MIN_FREE_GB = 4       # (below this free at the start, a note)
# (on Windows the workers are new processes holding the emit's tables and their run's functions: up to 395 MB each, measured in
# nx2/chunks.py file_jobs)
LIFT_ONE_GB, LIFT_MORE_GB = 2.0, (0.5 if os.name == "nt" else 0.75)


def lift_processes(memory_gb):
    """The translation's processes within memory_gb (0: the lifter's own rule, by the memory free): n workers and the side process
    beside them, each LIFT_MORE_GB, over the one process's LIFT_ONE_GB; one where two would not fit"""
    if not memory_gb:
        return 0
    n = int((memory_gb - LIFT_ONE_GB) / LIFT_MORE_GB) - 1
    return max(1, min((os.cpu_count() or 2) - 1, n)) if n >= 2 else 1


def default_jobs():
    """Compiles at once at the most: the cores less one (how many run is the memory's call: Gate)"""
    return max(1, (os.cpu_count() or 2) - 1)


def run(cmd, env=None, cwd=None, what=None):
    """the command's output goes on as it comes; a failure stops the build with its last lines"""
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace", env=env, cwd=cwd)
    tail = []
    for line in p.stdout:
        line = line.rstrip("\n")
        tail = (tail + [line])[-25:]
        say(line)
    if p.wait():
        raise Stop("%s failed (exit %d):\n%s" % (what or os.path.basename(cmd[0]), p.returncode, "\n".join(tail[-12:])))


def python_env(kit, work):
    src = os.path.join(kit, "src")
    env = dict(os.environ, OOT_WORK=os.path.join(work, "lift"), PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")
    env.pop("PYTHONPATH", None)
    return src, env


def read_game(kit, work, game):
    step(1)
    exefs = os.path.join(work, "game", "exefs")
    if os.path.isdir(game):
        for d in (game, os.path.join(game, "exefs")):
            if os.path.exists(os.path.join(d, "main")):
                return d
        raise Stop("no exefs (a file named main) in %s" % game)
    if not os.path.isfile(game):
        raise Stop("the game file was not found: %s" % game)
    stamp = "%d %d" % (os.path.getsize(game), int(os.path.getmtime(game)))
    mark = os.path.join(work, "game", ".from")
    if os.path.exists(os.path.join(exefs, "main")) and os.path.exists(mark) and open(mark).read() == stamp:
        say("read already, from this file")
        return exefs
    src, env = python_env(kit, work)
    shutil.rmtree(os.path.join(work, "game"), ignore_errors=True)
    os.makedirs(os.path.join(work, "game"))
    run([sys.executable, "-I", "-u", os.path.join(src, "nx2", "nup.py"), game, "--only", "exefs", "--extract",
         os.path.join(work, "game")], env=env, what="reading the game file")
    if not os.path.exists(os.path.join(exefs, "main")):
        raise Stop("the game file gave no program (exefs/main): is it the supported game and version?")
    open(mark, "w").write(stamp)
    return exefs


def tree_key(*dirs):
    h = hashlib.sha1()
    for d in dirs:
        for base, _, files in sorted(os.walk(d)):
            for f in sorted(files):
                p = os.path.join(base, f)
                h.update(os.path.relpath(p, d).encode() + b"%d" % os.path.getsize(p))
    return h.hexdigest()


def lift(kit, work, exefs, lift_jobs):
    step(2)
    src, env = python_env(kit, work)
    gen = os.path.join(work, "lift", "sa", "gen")
    with open(os.path.join(exefs, "main"), "rb") as f:
        key = hashlib.sha1(f.read()).hexdigest() + " " + json.load(open(os.path.join(kit, "kit.json")))["revisions"]["PS5_Longshot"]
    mark = os.path.join(work, "lift", ".done")
    if os.path.exists(mark) and open(mark).read() == key and os.path.exists(os.path.join(gen, "a64_table.c")):
        say("translated already, from this program with this kit")
        return gen
    if os.path.exists(mark):
        os.remove(mark)
    os.makedirs(os.path.join(work, "lift", "image"), exist_ok=True)
    if lift_jobs:
        env["LONGSHOT_LIFT_JOBS"] = str(lift_jobs)
    run([sys.executable, "-I", "-u", os.path.join(src, "nx2", "lift.py"), "--standalone", "--write", "--exefs", exefs,
         "--work", os.path.join(work, "lift")], env=env, what="the translation")
    if not os.path.exists(os.path.join(gen, "a64_table.c")) or not os.path.exists(os.path.join(work, "lift", "sa", "image", "image.bin")):
        raise Stop("the translation ended without its files: if it was stopped for want of memory, close other programs "
                   "and build again")
    open(mark, "w").write(key)
    return gen


# The compile's memory. What one compile takes at its peak, a little over (nx2/build.py mem_need's rule, measured again here with the
# kit's clang 23 for the PS5 at -O1): 0.4 GB + 50 MB per MB of C + 250 MB per MB of its largest function. The lift's chunks are
# ~24 MB of small functions (1.6-1.7 GB each); a few hold one giant function, and code_028.c's 10 MB one took 4.3 GB alone, more
# than many PCs had free. So:
#   - the giants are compiled cut into pieces (nx2/split_giants.py, as the PC build has done since issue 418's time: 721 MB, and
#     faster, for that file);
#   - a chunk whose need is past what one compile may take (MEMORY_CAP: --memory, else the memory free at the start) is compiled
#     as parts cut at its functions' heads (each part: the chunk's head, its declarations, then a run of its functions; nothing
#     else stands between the lifted functions, so each part is complete C and the objects together are the chunk's);
#   - a compile starts only when its need fits: within --memory with those running, else in the memory free now less what the
#     running ones may still take and RESERVE_MB (one always runs).
RESERVE_MB = 1536
MIN_PART_MB = 900   # (the least a part is cut to: 0.4 GB + ~10 MB of C)
SELF_MB = 400       # (this process, with a part's texts in hand, and the estimates' slack: 2 x 1.4 GB measured 3.08 GB with 300)
COMPILED = "game_%s.o"


def mem_need(text):
    """A lifted C text's compile peak in MB (after split_giants: its pieces are functions of their own)"""
    import lifted_c
    starts = [m.start() for m in lifted_c.HEAD_BYTES.finditer(text)]
    i = text.find(b"\nstatic __attribute__((noinline)) uintptr_t s_")
    while i >= 0:
        starts.append(i)
        i = text.find(b"\nstatic __attribute__((noinline)) uintptr_t s_", i + 1)
    starts = sorted(starts) + [len(text)]
    largest = max([b - a for a, b in zip(starts, starts[1:])] or [0])
    return int(400 + 50 * len(text) / (1 << 20) + 250 * largest / (1 << 20))


def cut_parts(text, cap_mb, giant_bytes):
    """Where to cut text (a lifted chunk, as the lift wrote it) so that each part's need is within cap_mb where the functions allow:
    [(start, end, need)], each part being the head (all before the first function) and text[start:end], a run of whole functions.
    A function of giant_bytes or more is counted at its pieces' size (split_giants cuts it as the part is compiled).
    [(0, len(text), need)]: compiled whole"""
    import lifted_c
    marks = [m.start() for m in lifted_c.HEAD_BYTES.finditer(text)]
    head = marks[0] if marks else 0
    bounds = marks + [len(text)]
    sizes = [y - x for x, y in zip(bounds, bounds[1:])]
    counted = [n if n < giant_bytes else 64 << 10 for n in sizes]
    need = lambda nbytes, largest: int(400 + 50 * (head + nbytes) / (1 << 20) + 250 * largest / (1 << 20))
    whole = need(sum(sizes), max(counted or [0]))
    if len(marks) < 2 or not cap_mb or whole <= cap_mb:
        return [(0, len(text), whole)]
    parts, first, nbytes, largest = [], 0, 0, 0
    for i, (n, c) in enumerate(zip(sizes, counted)):
        if i > first and need(nbytes + n, max(largest, c)) > cap_mb:
            parts.append((marks[first], marks[i], need(nbytes, largest)))
            first, nbytes, largest = i, 0, 0
        nbytes += n
        largest = max(largest, c)
    parts.append((marks[first], len(text), need(nbytes, largest)))
    return parts


class Gate:
    """Compiles started by memory: within limit_mb with those running (--memory), else by the memory free now"""

    def __init__(self, limit_mb):
        import threading
        self.cv = threading.Condition()
        self.limit = limit_mb
        self.running = {}   # (lease: [need, Popen or None])
        self.queue = []     # (the compiles waiting, in the order they came: the largest first, none passed by smaller ones)

    def fits(self, need):
        if self.limit:
            return sum(n for n, _ in self.running.values()) + need <= self.limit
        free = available_gb()
        if free is None:
            return True
        owed = sum(max(0, n - rss_mb(p)) for n, p in self.running.values())
        return free * 1024 - owed - RESERVE_MB >= need

    def enter(self, need):
        with self.cv:
            lease = object()
            self.queue.append(lease)
            while self.queue[0] is not lease or (self.running and not self.fits(need)):
                self.cv.wait(1.0)
            self.queue.pop(0)
            self.running[lease] = [need, None]
            self.cv.notify_all()
            return lease

    def started(self, lease, proc):
        with self.cv:
            self.running[lease][1] = proc

    def leave(self, lease):
        with self.cv:
            self.running.pop(lease, None)
            self.cv.notify_all()


def rss_mb(proc):
    """a running compiler's resident memory in MB (0: not known; Linux only: elsewhere its whole need is counted as owed)"""
    if proc is None or proc.poll() is not None:
        return 0
    try:
        with open("/proc/%d/statm" % proc.pid) as f:
            return (int(f.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")) >> 20
    except (OSError, ValueError, AttributeError):
        return 0


def make_part(nx2, path, lo, hi, out):
    """(--make-part, a process of its own) the C a chunk's compile job compiles, written to out: its part (the chunk's head and
    text[lo:hi], a run of its functions; hi -1: the whole chunk) with its giants split"""
    sys.path.insert(0, nx2)
    import lifted_c
    import split_giants
    with open(path, "rb") as f:
        text = f.read()
    if lo or hi >= 0:
        m = lifted_c.HEAD_BYTES.search(text)
        text = text[:m.start() if m else 0] + text[lo:hi if hi >= 0 else len(text)]
    split, st = split_giants.split_text(text.decode("utf-8"), split_giants.PIECE_KB)
    with open(out, "wb") as f:
        f.write(split.encode("utf-8") if st["functions_split"] else text)


def compile_game(kit, info, work, gen, clang, jobs, memory_gb=0):
    step(3)
    src, env = python_env(kit, work)
    sys.path.insert(0, os.path.join(src, "nx2"))
    import split_giants
    rt64 = os.path.join(work, "rt64")
    # (the 64-bit guest window's runtime header and a64_rt.c: nx2/rtgen.py, as ps5/build.py makes them)
    run([sys.executable, "-I", "-c", "import sys; sys.path.insert(0, sys.argv[1]); import rtgen; rtgen.write(sys.argv[2])",
         os.path.join(src, "nx2"), rt64], env=env, what="the runtime header")
    place = lambda a: a.replace("{kit}", kit).replace("{rt64}", rt64).replace("{gen}", gen)
    flags = [place(a) for a in info["target_flags"] + info["game_flags"]]
    chunks = sorted(f for f in os.listdir(gen) if f.startswith("code_") and f.endswith(".c"))
    others = [os.path.join(gen, f) for f in info["game_files"]] + [os.path.join(rt64, "a64_rt.c")]
    obj_dir = os.path.join(work, "obj")
    cut_dir = os.path.join(work, "cut")   # (the compiled copies of the chunks: giants split, parts cut; removed after each)
    os.makedirs(obj_dir, exist_ok=True)
    os.makedirs(cut_dir, exist_ok=True)
    version = subprocess.run([clang, "--version"], capture_output=True, text=True).stdout.splitlines()[0]
    # (within --memory: the compiles' share is what this process leaves, and the parts are cut to half of it, so two run at once:
    # a part's fixed 0.4 GB makes smaller ones slower in all. Else a chunk is cut only where it does not fit in the memory free)
    limit = max(MIN_PART_MB, memory_gb * 1024 - SELF_MB) if memory_gb else 0
    free = available_gb()
    cap = max(MIN_PART_MB, int(limit / 2 if limit else (free * 1024 - RESERVE_MB if free else 0))) if (limit or free) else 0
    heads = hashlib.sha1()
    for d in (rt64, os.path.join(kit, "src", "third_party", "a64-kit", "rt"), os.path.join(kit, "src", "nx2", "rt"), gen):
        for f in sorted(os.listdir(d)):
            if f.endswith(".h"):
                heads.update(f.encode() + open(os.path.join(d, f), "rb").read())
    base = hashlib.sha1((" ".join(info["target_flags"] + info["game_flags"]) + version + split_giants.flag()).encode() +
                        heads.digest()).hexdigest()

    # (each job: (name, its file, (start, end) of a chunk's part or None for a file compiled as it is, its need). Only offsets are
    # held: a part is read from its chunk when it is compiled, so this process holds no more than the compiles' own texts)
    jobs_list = []
    for c in chunks:
        with open(os.path.join(gen, c), "rb") as f:
            text = f.read()
        parts = cut_parts(text, cap, split_giants.MIN_KB * 1024)
        for i, (lo, hi, need) in enumerate(parts):
            jobs_list.append((c[:-2] + ("" if len(parts) == 1 else "_p%d" % i), os.path.join(gen, c),
                              (lo, hi) if len(parts) > 1 else (0, None), need))
        del text
    for s in others:
        # (the lift's other files: a64_table.c, 16 MB, took 589 MB; the rest ~50 MB)
        jobs_list.append((os.path.basename(s)[:-2], s, None, int(400 + 15 * os.path.getsize(s) / (1 << 20))))
    biggest = max(n for _, _, _, n in jobs_list)
    say("compiler: %s; %d files (%d chunks), up to %d at once%s; the largest compile takes ~%.1f GB" % (
        version, len(jobs_list), len(chunks), jobs, " within %.1f GB" % memory_gb if memory_gb else " as the free memory allows",
        biggest / 1024))
    gate = Gate(limit)
    for f in os.listdir(obj_dir):   # (objects of an earlier build's other cut: not this build's)
        if f.endswith(".o") and f[:-2] not in {COMPILED[:-2] % n for n, _, _, _ in jobs_list}:
            for g in (f, f + ".key"):
                if os.path.exists(os.path.join(obj_dir, g)):
                    os.remove(os.path.join(obj_dir, g))

    def one(job):
        name, path, span, need = job
        obj = os.path.join(obj_dir, COMPILED % name)
        h = hashlib.sha1(base.encode())
        h.update(repr(span).encode())
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(1 << 20), b""):
                h.update(block)
        key, stamp = h.hexdigest(), obj + ".key"
        if os.path.exists(obj) and os.path.exists(stamp) and open(stamp).read() == key:
            return obj, None
        lease = gate.enter(need)
        copy = None
        try:
            if span is not None:   # (made by a process of its own: cutting a giant's lines takes this one's memory for good)
                copy = os.path.join(cut_dir, name + ".c")
                r = subprocess.run([sys.executable, "-I", os.path.abspath(__file__), "--make-part", os.path.join(src, "nx2"), path,
                                    str(span[0]), str(-1 if span[1] is None else span[1]), copy], capture_output=True, text=True)
                if r.returncode:
                    return obj, "%s: making its copy failed (exit %d)\n%s" % (name, r.returncode, (r.stdout + r.stderr)[-3000:])
            p = subprocess.Popen([clang] + flags + ["-c", copy or path, "-o", obj], stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, errors="replace")
            gate.started(lease, p)
            out, _ = p.communicate()
        finally:
            gate.leave(lease)
            if copy and os.path.exists(copy):
                os.remove(copy)
        if p.returncode:
            return obj, "%s: exit %d\n%s" % (name, p.returncode, out[-3000:])
        open(stamp, "w").write(key)
        return obj, None

    jobs_list.sort(key=lambda j: -j[3])   # (the largest first, so none is left alone at the end)
    objects, failed, done, t0 = [], [], 0, time.time()
    say("@@progress 0 %d" % len(jobs_list))
    with concurrent.futures.ThreadPoolExecutor(jobs) as pool:
        for future in concurrent.futures.as_completed([pool.submit(one, j) for j in jobs_list]):
            obj, err = future.result()
            done += 1
            objects.append(obj)
            if err:
                failed.append(err)
                say(err)
            say("@@progress %d %d" % (done, len(jobs_list)))
    if failed:
        hint = (" A compiler stopped by the system (exit -9 or 137) wants less memory: set Memory to use lower (--memory)."
                if any("exit -9" in e or "exit 137" in e for e in failed) else "")
        raise Stop("%d of %d files did not compile.%s" % (len(failed), len(jobs_list), hint))
    say("compiled in %.0f s" % (time.time() - t0))
    return objects


def rsp(path, args):
    """a response file: one argument a line, quoted for lld"""
    with open(path, "w", encoding="utf-8") as f:
        for a in args:
            f.write('"%s"\n' % a.replace("\\", "/").replace('"', '\\"'))
    return "@" + path


def link(kit, info, work, objects, lld, nm):
    step(4)
    out = os.path.join(work, "link")
    os.makedirs(out, exist_ok=True)
    place = lambda a: a.replace("{kit}", kit)
    lk = info["link"]
    # (the libc calls host/ps5 defines because no module a title loads exports them: kept inside the executable)
    with open(os.path.join(out, "local.map"), "w") as f:
        f.write("{\n    local:\n" + "".join("        %s;\n" % n for n in info.get("local_symbols", [
            "fnmatch", "isatty", "pthread_setname_np", "timegm", "syscall", "pipe2", "accept4", "posix_fadvise", "getpwuid",
            "umask"])) + "};\n")
    elf = os.path.join(out, "llvm-pie.elf")
    stubs = [os.path.join(kit, "lib", "stubs", n) for n in ("libSceAgc.so", "libSceAgcDriver.so")]
    sdk_lib = os.path.join(kit, "sdk", "target", "lib")
    args = (["-m", "elf_x86_64", "-pie", "--eh-frame-hdr", "-z", "max-page-size=0x4000", "-mllvm", "-emulated-tls"] +
            [place(a) for a in lk["script"]] + [place(a) for a in lk["flags"]] +
            ["--version-script", os.path.join(kit, "link", "native", "app-symbols.map"),
             "--version-script", os.path.join(out, "local.map"), "--exclude-libs=ALL", "--gc-sections", "-e", "_start",
             "-Map=" + os.path.join(out, "longshot.map"), "-o", elf, os.path.join(kit, "obj", "app_crt.o")] +
            [os.path.join(kit, "obj", n) for n in info["objects"]] + sorted(objects) +
            [os.path.join(kit, "lib", n) for n in ("libavcodec.a", "libswscale.a", "libavutil.a", "libdav1d.a", "libzstd.a")] +
            stubs + [place(a) for a in lk["inputs"]] + ["--as-needed"] +
            sorted(os.path.join(sdk_lib, f) for f in os.listdir(sdk_lib) if f.endswith(".so")) + ["--hash-style=gnu"])
    t0 = time.time()
    run([lld, rsp(os.path.join(out, "link.rsp"), args)], what="the link")
    exported = set(open(os.path.join(kit, "link", "exported.txt")).read().split())

    def undefined(kinds):
        r = subprocess.run([nm, "-D", "--undefined-only", elf], capture_output=True, text=True, check=True).stdout
        return sorted({l.split()[1].split("@")[0] for l in r.splitlines() if len(l.split()) == 2 and l.split()[0] in kinds})
    # (a weak reference nothing defines reads as null: bound to 0 here, or the console's loader takes it for an import)
    weak = [s for s in undefined(("w", "v")) if s not in exported]
    if weak:
        run([lld, rsp(os.path.join(out, "link.rsp"), args + ["--defsym=%s=0" % s for s in weak])], what="the link")
    null = [s for s in undefined(("U",)) if s not in exported]
    if null:
        raise Stop("the link has imports that no module a title loads exports (null at run time): " + " ".join(null[:20]))
    say("linked: %d MB (%.0f s)" % (os.path.getsize(elf) >> 20, time.time() - t0))
    return elf


KNOWN_GPU_HANGS = os.path.join(HERE, "known_gpu_hangs.txt")


def known_gpu_hangs(path=KNOWN_GPU_HANGS):
    """The program keys of known_gpu_hangs.txt: the first word of each line that is not a note, 16 hex digits (anything
    else there stops the build: a list that says less than it seems to is worse than none)"""
    keys = []
    try:
        lines = open(path, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return keys
    for n, line in enumerate(lines, 1):
        words = line.split()
        if not words or words[0].startswith("#"):
            continue
        key = words[0].lower()
        if len(key) != 16 or any(c not in "0123456789abcdef" for c in key):
            raise Stop("%s, line %d: %r is not a program key (16 hex digits)" % (path, n, words[0]))
        if key not in keys:
            keys.append(key)
    return keys


def env_text(profile, hangs):
    """longshot_env.txt: the profile's switches, then the shaders known to hang the GPU (RX_VK_GPU_SKIP, gpu/vk/gpu_skip.h)"""
    text = ("# Longshot on the PS5: the switches of the profile this folder was built for (%s).\n"
            "# NAME=VALUE lines; a line starting with # is a note.\n" % profile["name"])
    text += "".join("%s=%s\n" % kv for kv in sorted(profile["env"].items()))
    if hangs:
        text += ("# shaders known to hang the GPU, left out (the builder's known_gpu_hangs.txt; without them: --no-known-skips)\n"
                 "RX_VK_GPU_SKIP=%s\n" % ",".join(hangs))
    return text


def title(kit, info, work, elf, native, out, model, known_skips=True):
    step(5)
    app = os.path.join(out, info["title_id"])
    if os.path.exists(app):
        for keep in ("eboot.bin", "image.bin"):   # (a folder built before: its executable and image are replaced)
            if os.path.exists(os.path.join(app, keep)):
                os.remove(os.path.join(app, keep))
    os.makedirs(app, exist_ok=True)
    stub_dir = os.path.join(kit, "sdk", "target", "lib")
    new = os.path.join(work, "eboot.elf.new")
    run([native, "link", "--in", elf, "--out", new, "--stub-dir", stub_dir,
         "--stub", os.path.join(kit, "lib", "stubs", "libSceAgc.so"), "--stub", os.path.join(kit, "lib", "stubs", "libSceAgcDriver.so"),
         "--module-sdk", "0x02000009", "--companion-sdk", "0x08050001", "--file-name", "eboot.elf"], what="the console's executable")
    run([native, "self", "--sign", "--in", new, "--out", os.path.join(app, "eboot.bin"), "--magic", "0x1D3D154F"], what="signing")
    run([native, "self", "--inspect", "--file", os.path.join(app, "eboot.bin")], what="the check of eboot.bin")
    shutil.copytree(os.path.join(kit, "title"), app, dirs_exist_ok=True)
    shutil.copy2(os.path.join(work, "lift", "sa", "image", "image.bin"), os.path.join(app, "image.bin"))
    # ---- the console's profile ----
    profile = MODELS[model]
    param = os.path.join(app, "sce_sys", "param.json")
    j = json.load(open(param, encoding="utf-8-sig"))
    j["attribute3"] = profile["attribute3"]
    with open(param, "w", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(j, indent=2) + "\n")
    hangs = known_gpu_hangs() if known_skips else []   # (left out: known_gpu_hangs.txt; gpu/vk/gpu_skip.h reads the line)
    with open(os.path.join(app, "longshot_env.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write(env_text(profile, hangs))
    say("profile: %s (attribute3 %#x%s)" % (profile["name"], profile["attribute3"],
                                           "".join("; %s=%s" % kv for kv in sorted(profile["env"].items()))))
    say("shaders known to hang the GPU: %s" % (", ".join(hangs) + " left out" if hangs else
                                               "none left out" + ("" if known_skips else " (--no-known-skips)")))
    size = sum(os.path.getsize(os.path.join(d, f)) for d, _, fs in os.walk(app) for f in fs)
    say("title: %s (%d MB)" % (app, size >> 20))
    return app


def check(a):
    """--check: the builder's own parts on this PC, with no game: the kit, the tools, the lifter's packages and its helper
    library, and one small file compiled for the console. What the release workflow runs on each system's package."""
    kit = find_kit(a.kit)
    info = json.load(open(os.path.join(kit, "kit.json")))
    say("kit: %s (%s), %d objects" % (info["longshot"], info["title_id"], len(info["objects"])))
    missing = [n for n in info["objects"] if not os.path.exists(os.path.join(kit, "obj", n))]
    if missing:
        raise Stop("the kit lacks %d of its objects (%s)" % (len(missing), missing[0]))
    clang, lld, nm, native = (find_tool(n, kit, a.tools) for n in ("clang", "ld.lld", "llvm-nm", "ps5-native-tool"))
    for tool, args in ((clang, ["--version"]), (lld, ["--version"]), (nm, ["--version"])):
        r = subprocess.run([tool] + args, capture_output=True, text=True)
        if r.returncode:
            raise Stop("%s does not run (exit %d): %s" % (tool, r.returncode, (r.stdout + r.stderr)[-300:]))
        say("%s: %s" % (os.path.basename(tool), (r.stdout + r.stderr).splitlines()[0]))
    r = subprocess.run([native], capture_output=True, text=True)
    if "ps5-native-tool" not in r.stdout + r.stderr:
        raise Stop("%s does not run: %s" % (native, (r.stdout + r.stderr)[-300:]))
    say("ps5-native-tool: runs")
    src, env = python_env(kit, a.work or ".")
    code = ("import sys, os; k = sys.argv[1]; sys.path[:0] = [os.path.join(k, 'nx2'), os.path.join(k, 'third_party', 'a64-kit', 'lift'), "
            "os.path.join(k, 'third_party', 'a64-kit', 'tools')]\n"
            "import numpy, capstone, lz4, zstandard, unicorn\n"
            "import a64emit\n"
            "text = a64emit.translate([(0x10000, 0x91000420)])[0][0]\n"
            "assert 'c->x[0]' in text, text\n"
            "print('lifter: its packages and its helper library load; ADD X0, X1, #1 ->', text.strip())\n"
            # (the game file's reader, as a build starts it: its imports, and the library a ZBIC-compressed main is unpacked
            # with, which must be there ready: a player has no compiler to build it with)
            "import nup, unpack, zbic\n"
            "assert os.path.exists(zbic.DLL), 'the ZBIC library is not in the kit: ' + zbic.DLL\n"
            "assert zbic.lib().zbic_content_size(b'ZBIC', 4) < 0\n"
            # (and reads what it writes: ps5/builder/zbic_check.c. A library that did not stopped every Linux build of v0.1.1)
            "r = zbic.lib().zbic_selftest()\n"
            "assert r == 0, 'the ZBIC library does not unpack its own frames (zbic_selftest %d): ' % r + zbic.DLL\n"
            "print('game file reader: loads, and its ZBIC library unpacks what it packs')\n")
    run([sys.executable, "-I", "-c", code, src], env=env, what="the lifter's parts")
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        c = os.path.join(tmp, "check.c")
        with open(c, "w") as f:
            f.write("#include <stdint.h>\n#include <string.h>\nuint64_t check(const char *s) { return strlen(s) + UINT64_C(1); }\n")
        place = lambda x: x.replace("{kit}", kit)
        flags = [place(x) for x in info["target_flags"]] + ["-march=znver2", "-O1"]
        r = subprocess.run([clang] + flags + ["-c", c, "-o", os.path.join(tmp, "check.o")], capture_output=True, text=True)
        if r.returncode:
            raise Stop("clang did not compile for the console: %s" % (r.stdout + r.stderr)[-600:])
        out = subprocess.run([nm, os.path.join(tmp, "check.o")], capture_output=True, text=True).stdout
        if " T check" not in out:
            raise Stop("the compiled check has no function: %s" % out)
    say("clang: compiles for the console (x86_64-sie-ps5, the kit's SDK)")
    cache = os.path.join(a.work, "amiibo-cache") if a.work else None
    say("amiibo cache: %s" % ("none (--work not given)" if not cache else
                              "%s (%s)" % (cache, "there" if os.path.isdir(cache) else "not there yet: Download amiibo fills it")))
    r = subprocess.run([sys.executable, "-I", "-c", "import PIL; print(PIL.__version__)"], capture_output=True, text=True)
    say("pillow (Download amiibo): " + ("PIL %s loads" % r.stdout.strip() if not r.returncode else
                                        "import PIL fails: the amiibo pictures cannot be made on this PC"))
    say("@@done check")


def shader_lists(kit, work, game, app):
    """(ps5/builder/shader_lists.py) the game's shader list and the pipeline state list in the title folder: the console's first
    start builds the pipelines before play, in a launch of its own, so play does not compile them (each compile leaves memory
    the base console runs out of, issues #4 and #24). Made from the .nup alone: a folder given instead has no romfs to read"""
    step(6)
    if not os.path.isfile(game):
        say("note: no .nup given, so no shader lists: the game compiles its shaders as it plays")
        return
    src, env = python_env(kit, work)
    run([sys.executable, "-I", "-u", os.path.join(HERE, "shader_lists.py"), "--src", src, "--nup", game, "--work", work,
         "--out", app], env=env, what="listing the game's shaders")


def game_data(kit, work, game, app, folder=False):
    """(ps5/builder/game_data.py) the game's whole romfs into the title folder: packs in Data/ and Data.idx (the default), or
    loose files in Data/ (folder). The console reads every game file from there and never the .nup. From a .nup, or from
    the romfs/ of a game folder given instead"""
    step(7)
    src, env = python_env(kit, work)
    if os.path.isfile(game):
        given = ["--nup", game]
    else:
        romfs = os.path.join(game, "romfs")
        if not os.path.isdir(romfs) and os.path.basename(os.path.normpath(game)) == "exefs":
            romfs = os.path.join(os.path.dirname(os.path.normpath(game)), "romfs")
        if not os.path.isdir(romfs):
            raise Stop("the game folder has no romfs/: the console needs the game's data (give the .nup instead)")
        given = ["--romfs", romfs]
    run([sys.executable, "-I", "-u", os.path.join(HERE, "game_data.py"), "--src", src, "--app", app] + given +
        (["--folder"] if folder else []), env=env, what="extracting the game's data")


def amiibo(kit, work, app, wanted):
    """(ps5/builder/amiibo.py) the amiibo catalogue and the figures' pictures, downloaded on this PC into <title>/amiibo/
    (amiibo.idx, figures.pak), only with the option. The download (about 151 MB) is cached in <work>/amiibo-cache, so a
    second build does not repeat it. Never stops the build: a failure is one warning, and the title has no amiibo/. True
    when amiibo/ was written"""
    step(8)
    if not wanted:
        say("amiibo: skipped (Download amiibo is not on)")
        return False
    src, env = python_env(kit, work)
    try:
        run([sys.executable, "-I", "-u", os.path.join(HERE, "amiibo.py"), "--app", app,
             "--cache", os.path.join(work, "amiibo-cache")], env=env, what="downloading the amiibo")
        if not os.path.isdir(os.path.join(app, "amiibo")):
            raise Stop("no amiibo/ was written")
    except (Stop, OSError) as e:
        say("warning: the amiibo were not added (%s); the build goes on without them" % str(e).splitlines()[0])
        return False
    say("amiibo: added to the title folder")
    return True


def build(a):
    kit = find_kit(a.kit)
    info = json.load(open(os.path.join(kit, "kit.json")))
    clang, lld, nm, native = (find_tool(n, kit, a.tools) for n in ("clang", "ld.lld", "llvm-nm", "ps5-native-tool"))
    out = os.path.abspath(a.out)
    work = os.path.abspath(a.work or os.path.join(out, "longshot-ps5-work"))
    os.makedirs(work, exist_ok=True)
    free = shutil.disk_usage(work).free / 2**30
    say("PS5 Longshot Plus Builder: kit %s (%s); work folder %s (%.0f GB free)" % (info["longshot"], info["title_id"], work, free))
    if free < 6:
        raise Stop("the work folder's disk has %.1f GB free: the build wants 6 GB" % free)
    gb = available_gb()
    if a.memory:
        say("memory: the build keeps to about %.1f GB%s" % (a.memory, "" if gb is None else " (%.1f GB is free now)" % gb))
    elif gb is not None and gb < MIN_FREE_GB:
        say("note: %.1f GB of memory is free; the build wants about %.0f GB at the least. Close other programs if it stops."
            % (gb, MIN_FREE_GB))
    exefs = read_game(kit, work, a.game)
    gen = lift(kit, work, exefs, a.lift_jobs or lift_processes(a.memory))
    objects = compile_game(kit, info, work, gen, clang, a.jobs or default_jobs(), a.memory)
    elf = link(kit, info, work, objects, lld, nm)
    app = title(kit, info, work, elf, native, out, a.model, not a.no_known_skips)
    shader_lists(kit, work, a.game, app)
    game_data(kit, work, a.game, app, a.data_folder)
    amiibo(kit, work, app, a.amiibo)
    say("@@done " + app)
    return app


def main():
    if sys.argv[1:2] == ["--make-part"]:
        nx2, path, lo, hi, out = sys.argv[2:7]
        make_part(nx2, path, int(lo), int(hi), out)
        return 0
    ap = argparse.ArgumentParser(description="PS5 Longshot Plus Builder: the PS5 title folder from your own game file")
    ap.add_argument("--check", action="store_true", help="check the builder's own parts on this PC (no game is needed), and stop")
    ap.add_argument("--game", help="the game: a .nup file, or a folder with its exefs")
    ap.add_argument("--out", help="where the title folder goes")
    ap.add_argument("--model", choices=sorted(MODELS),
                    help="the console the folder is for: base (PS5 and PS5 Slim) or pro (PS5 Pro)")
    ap.add_argument("--kit")
    ap.add_argument("--tools")
    ap.add_argument("--work", help="the build's own files (default: <out>/longshot-ps5-work); kept, so a second build is short")
    ap.add_argument("--jobs", type=int, default=0, help="compiles at once (default: by the cores and the memory free)")
    ap.add_argument("--lift-jobs", type=int, default=0, help="the translation's processes (default: the lifter's own rule)")
    ap.add_argument("--memory", type=float, default=0,
                    help="GB of memory the build may use (default: as much as is free). Lower is slower; %.0f at the least"
                    % MIN_MEMORY_GB)
    ap.add_argument("--no-known-skips", action="store_true",
                    help="draw the shaders known to hang the GPU (known_gpu_hangs.txt) instead of leaving them out")
    ap.add_argument("--data-folder", action="store_true",
                    help="the game's data as loose files in Data/ (for mods), not packs with an index (the default)")
    ap.add_argument("--amiibo", action="store_true",
                    help="download the amiibo catalogue and the figures' pictures (about 42 MB in the title; the download is "
                    "about 151 MB, once) into the title folder: never share them")
    a = ap.parse_args()
    if not a.check and not (a.game and a.out and a.model):
        ap.error("--game, --out and --model are needed (or --check)")
    if a.memory and a.memory < MIN_MEMORY_GB:
        ap.error("--memory: %.0f GB at the least" % MIN_MEMORY_GB)
    try:
        check(a) if a.check else build(a)
    except Stop as e:
        say("@@error " + str(e).replace("\n", " | "))
        print(str(e), file=sys.stderr)
        return 1
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        say("@@error " + str(e).replace("\n", " | "))
        print(tb, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
