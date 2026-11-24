"""Game-free: reading the game's files ahead of it (host/ps5/asset_prefetch.c, docs/ps5-asset-prefetch.md), compiled for the
PC with AddressSanitizer against a pack of its own (tests/asset_prefetch_test.c), with a Data.deps the builder's writer
makes (ps5/builder/asset_deps.py encode).

- measuring only (the default): every read goes to the disk, the files a scene opened are kept, in order, in
  cache/prefetch/<scene>.txt when the scene changes, and a scene's next visit is no different;
- HOS_PREFETCH=1: opening a scene's parameters reads its files ahead; the game's reads of them come from the bucket, byte for
  byte what the pack holds, and each is let go once read whole; a settled scene reads ahead the scenes it leads to;
  another scene lets go of what it does not want; the bucket stays under HOS_PREFETCH_MB; short memory empties it;
- a scene's profile comes first the next time; a Data.deps of other packs is refused (the profiles still work);
- the builder's map: decode gives back what encode was given; its SHA-256 is checked.

    python -I -B tests/test_asset_prefetch.py [--cc gcc]
"""
import argparse
import os
from pathlib import Path
import random
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ps5" / "builder"))
import asset_deps  # noqa: E402

BID = bytes(range(1, 17))


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def fnv(b):
    h = 1469598103934665603
    for x in b:
        h = ((h ^ x) * 1099511628211) & (2 ** 64 - 1)
    return "%016x" % h


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="asset-prefetch-") as tmp:
        tmp = Path(tmp)
        exe = tmp / "prefetch"
        r = subprocess.run([a.cc, "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-g", "-fsanitize=address,undefined",
                            "-fno-omit-frame-pointer", str(ROOT / "tests" / "asset_prefetch_test.c"),
                            str(ROOT / "host" / "ps5" / "asset_prefetch.c"), "-I", str(ROOT / "host" / "ps5"), "-lpthread",
                            "-o", str(exe)], capture_output=True, text=True)
        need(r.returncode == 0, "it compiles: " + r.stderr[-3000:])

        # a pack of files: three scenes' parameters, maps, actors and models; sizes from bytes to a few MB
        rnd = random.Random(7)
        files = {}
        for scene in ("Field", "Forest", "Cave"):
            files["Banc/GameBancParam/%s.game__banc__GameBancParam.bgyml" % scene] = 300
            files["Banc/%s/%s_Static.bcett.byml.zs" % (scene, scene)] = 40000
            for k in range(6):
                files["Pack/Actor/%s_Actor%d.pack.zs" % (scene, k)] = 2000 + 500 * k
                files["Model/%s_Model%d.%s_Model%d.bfres.zs" % (scene, k, scene, k)] = 200000 + 100000 * k
        files["Model/Big.Big.bfres.zs"] = 3 << 20
        files["Effect/Code_Loaded.esetb.byml.zs"] = 5000   # (in no list: only a profile can know it)
        pack = bytearray()
        rows = []
        for p, n in files.items():
            rows.append("%s\t%d\t%d" % (p, len(pack), n))
            data = bytes(rnd.getrandbits(8) for _ in range(min(n, 4096))) * (n // 4096 + 1)
            pack += data[:n]
        content = {p: bytes(pack[int(r.split("\t")[1]):int(r.split("\t")[1]) + n]) for (p, n), r in zip(files.items(), rows)}
        (tmp / "pack").write_bytes(pack)
        (tmp / "files.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")

        def scene_files(s):
            return ["Banc/GameBancParam/%s.game__banc__GameBancParam.bgyml" % s, "Banc/%s/%s_Static.bcett.byml.zs" % (s, s)] + \
                ["Pack/Actor/%s_Actor%d.pack.zs" % (s, k) for k in range(6)] + \
                ["Model/%s_Model%d.%s_Model%d.bfres.zs" % (s, k, s, k) for k in range(6)]
        deps_rows = [("Cave", scene_files("Cave"), ["Forest"], 0), ("Field", scene_files("Field") + ["Model/Big.Big.bfres.zs"],
                     ["Forest", "Cave"], 0), ("Forest", scene_files("Forest"), ["Field"], 0)]
        blob = asset_deps.encode(deps_rows, BID)
        back = asset_deps.decode(blob)
        need(back["Field"][0] == deps_rows[1][1] and back["Field"][1] == ["Forest", "Cave"], "the map decodes as it was made")
        bad = bytearray(blob)
        bad[-1] ^= 1
        try:
            asset_deps.decode(bytes(bad))
            need(False, "a damaged map is refused")
        except ValueError:
            pass

        def title(with_deps=True):
            t = tmp / ("title-%d" % len(list(tmp.glob("title-*"))))
            t.mkdir()
            if with_deps:
                (t / "Data.deps").write_bytes(blob)
            return t

        def run(t, *cmds, **env):
            r = subprocess.run([str(exe), str(t), str(tmp / "pack"), str(tmp / "files.txt"), *cmds], capture_output=True,
                               text=True, timeout=120, env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1", **env))
            need(r.returncode == 0, "the driver ran (exit %d): %s" % (r.returncode, (r.stdout + r.stderr)[-3000:]))
            need("AddressSanitizer" not in r.stderr and "runtime error" not in r.stderr, "no memory error: " + r.stderr[-3000:])
            out = r.stdout.splitlines()
            for line in out:   # (every read gave the file's own bytes, from the bucket or the disk)
                parts = line.split()
                if parts and parts[0] in ("hit", "disk"):
                    need(parts[2] == fnv(content[parts[1]]), "the bytes of %s (%s)" % (parts[1], parts[0]))
            return out

        def stats(out):
            line = [x for x in out if x.startswith("stats ")][-1]
            return {k: int(v) for k, v in (kv.split("=") for kv in line.split()[1:])}

        def reads(out, kind):
            return [x.split()[1] for x in out if x.startswith(kind + " ")]

        field = scene_files("Field")
        param = "open:" + field[0]

        # measuring only: all from the disk; the opens kept as the scene's profile, in order
        t = title()
        out = run(t, param, *("open:" + f for f in field[1:4]), "open:Effect/Code_Loaded.esetb.byml.zs",
                  *("read:" + f for f in field[:4]), "scene:Field", "scene:Forest", "stop")
        need(not reads(out, "hit") and len(reads(out, "disk")) == 4, "measuring only: every read from the disk")
        need(any("io: loading Field" in x for x in out) and any("io: Field:" in x and "files opened" in x for x in out),
             "the measurements are logged: " + "\n".join(out))
        profile = (t / "cache" / "prefetch" / "Field.txt").read_text(encoding="utf-8").splitlines()
        need([x for x in profile if not x.startswith("#")] == field[:4] + ["Effect/Code_Loaded.esetb.byml.zs"],
             "the scene's profile, in the order opened: %r" % profile)

        # reading ahead: the parameters opened, the thread reads the rest; the game's reads come from the bucket
        t = title()
        out = run(t, param, "wait", "stats", *("read:" + f for f in field[1:]), "stats", "stop", HOS_PREFETCH="1")
        s0 = stats(out[:out.index([x for x in out if x.startswith("stats ")][0]) + 1])
        need(s0["prefetched"] >= len(field), "the scene's files read ahead: %r" % s0)
        need(reads(out, "hit") == field[1:], "the game's reads came from the bucket: %r" % out)
        s1 = stats(out)
        need(s1["released"] == len(field) - 1, "each let go once read whole: %r" % s1)

        # a settled scene reads ahead those it leads to; another scene lets go of what it does not want
        t = title()
        out = run(t, "scene:Field", "wait", "stats", "scene:Cave", "wait", "stats", "stop", HOS_PREFETCH="1")
        a, b = stats(out[:[i for i, x in enumerate(out) if x.startswith("stats ")][0] + 1]), stats(out)
        need(a["prefetched"] >= 3 * 14, "Field, Forest and Cave read ahead: %r" % a)
        need(b["evicted"] > 0, "going to Cave let go of what it does not want (Field's own): %r" % b)

        # the bucket stays under HOS_PREFETCH_MB (2 MB: the 3 MB model never fits)
        t = title()
        out = run(t, "scene:Field", "wait", "stats", "stop", HOS_PREFETCH="1", HOS_PREFETCH_MB="2")
        need(stats(out)["held"] <= 2 << 20, "under the cap: %r" % stats(out))

        # the title's memory short: the bucket empties and stops
        t = title()
        out = run(t, "scene:Field", "wait", "room:100", "scene:Forest", "wait", "stats", "stop", HOS_PREFETCH="1")
        need(stats(out)["held"] == 0 and any("the bucket stops" in x for x in out), "short memory empties it: %r" % out)

        # the profile first: a file only code loads is read ahead on the next visit
        t = title()
        run(t, param, "open:Effect/Code_Loaded.esetb.byml.zs", "scene:Field", "scene:Forest", "stop")
        out = run(t, param, "wait", "read:Effect/Code_Loaded.esetb.byml.zs", "stop", HOS_PREFETCH="1")
        need(reads(out, "hit") == ["Effect/Code_Loaded.esetb.byml.zs"], "a profiled file read ahead: %r" % out)

        # another build's map: refused, said; the profile still reads ahead
        t = title()
        out = run(t, param, "wait", "stats", "stop", HOS_PREFETCH="1", TEST_OTHER_BUILD="1")
        need(any("Data.deps refused" in x for x in out) and stats(out)["prefetched"] == 0, "another build's map refused: %r" % out)

    # the file calls ask the module first, and tell it what they read; the game's side tells it the scene
    posix = (ROOT / "host" / "posix" / "win32_posix.c").read_text(encoding="utf-8")
    need("asset_prefetch_open(path, fd, base, size);" in posix and "asset_prefetch_read(fd, f->base, f->size, from, buf, want)" in posix
         and posix.count("asset_prefetch_disk(fd, f->base, done") == 2, "win32_posix.c's file calls tell the module")
    main_c = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    need("asset_prefetch_init(dir);" in main_c and "asset_prefetch_scene(map);" in main_c, "hos_main.c starts it and tells the scene")
    need('"asset_deps.py"' in (ROOT / "ps5" / "builder" / "package.py").read_text(encoding="utf-8"), "the builder ships asset_deps.py")
    need("prefetch_map(a.app)" in (ROOT / "ps5" / "builder" / "game_data.py").read_text(encoding="utf-8"), "step 7 makes Data.deps")
    print("PASS: measuring, learning, reading ahead, letting go, the cap and the memory floor")


if __name__ == "__main__":
    main()
