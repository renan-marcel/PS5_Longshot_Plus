"""PS5: the game's whole romfs into the title folder, so the console reads every game file from there (host/hos_main.c) and
never opens the .nup.

    python -I ps5/builder/game_data.py --src <folder with nx2/> --app <title folder> (--nup <game.nup> | --romfs <folder>)
        [--folder]

By default as packs (ps5/builder/data_packs.py, docs/ps5-data-packs.md): Data/<Top>.pak, a pack per top folder of the
romfs in parts of at most 4 GiB, written straight from the .nup (no extracted copy first), and Data.idx, the index, last.
Nothing is compressed. 53 files of 24.4 GiB on any drive, where 186,583 loose files take 62.5 GiB on exFAT's 256 KB
clusters. A pack already whole from a stopped build of the same game file is kept.

--folder: as plain files in Data/ (for mods and tests): the newest title's romfs is extracted (nx2/nup.py extract) into a
folder beside the title folder, on the same drive, then moved in as <title>/Data. A build stopped part way goes on from
where it stopped: files already written whole are kept.

Either way the dump's damaged .zs files get a whole one of the same kind in their place (nup.stand_in_damaged's rule, as
the PC build does: without them the Water Temple's walls and floors are missing, #1002): copied in a folder, the same
bytes pointed at in packs. DATA_MARK is written last, naming the game file and the layout.
From a folder (a game given unpacked): its romfs/ is the source.
"""
import argparse
from contextlib import suppress
import hashlib
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import data_packs  # noqa: E402

DATA = "Data"                     # (the romfs, in the title folder: host/hos_main.c reads it)
DATA_MARK = "longshot_data.txt"   # (in the title folder, written last: what Data/ was made from)
STAGE = "longshot-ps5-data"       # (beside the title folder: the folder extraction until it is whole)
PROGRESS = "longshot_data_packs.json"   # (in the title folder while packs are written: the ones whole so far)
DAMAGED_NOTE = "longshot_damaged_files.txt"
ROOM = 1 << 30                    # (left free on the drive past what the files take)


def say(text):
    print(text, flush=True)


def read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return None


def write_text(path, text):
    with open(path + ".part", "w", encoding="utf-8", newline="\n") as f:
        f.write(text + "\n")
    os.replace(path + ".part", path)


def stamp_of(path):
    """What a game file or folder is told apart by: its size and time (a .nup), its path (a folder)"""
    if os.path.isdir(path):
        return "folder %s" % os.path.abspath(path)
    return "nup %d %d" % (os.path.getsize(path), int(os.path.getmtime(path)))


def remove_tree(nup, path):
    if os.path.lexists(path):
        say("removing %s" % path)
        shutil.rmtree(nup.long_path(path))


def cluster_size(path):
    """The drive's allocation unit (a file takes whole ones): exFAT's are 128-256 KB on large drives"""
    try:
        if os.name == "nt":
            import ctypes
            spc, bps, free_c, total_c = (ctypes.c_ulong() for _ in range(4))
            root = os.path.splitdrive(os.path.abspath(path))[0] + "\\"
            if ctypes.windll.kernel32.GetDiskFreeSpaceW(root, ctypes.byref(spc), ctypes.byref(bps), ctypes.byref(free_c),
                                                       ctypes.byref(total_c)):
                return spc.value * bps.value or 4096
            return 4096
        st = os.statvfs(path)
        return st.f_frsize or st.f_bsize or 4096
    except (OSError, AttributeError, ValueError):
        return 4096


def on_disk(sizes, cluster):
    return sum(-(-s // cluster) * cluster for s in sizes)


def check_room(where, need, what):
    free = shutil.disk_usage(where).free
    say("game data: %s; %.1f GB to write on this drive (%d KB clusters), %.1f GB free on %s"
        % (what, need / 1e9, cluster_size(where) >> 10, free / 1e9, where))
    if need + ROOM > free:
        raise SystemExit("the drive of %s has %.1f GB free: the game's data wants %.1f GB more there. Free some room, or "
                         "build into a folder on another drive" % (where, free / 1e9, (need + ROOM) / 1e9))


def write_damaged_note(app, done, base):
    note = os.path.join(app, DAMAGED_NOTE)
    if done:
        lines = ["Your game dump is incomplete: %d game file%s in it %s damaged (a complete dump is about 23.8 GB). Similar "
                 "files are used in their place, with different textures there. Dump the game again for the original files:"
                 % (len(done), "" if len(done) == 1 else "s", "is" if len(done) == 1 else "are")]
        lines += ["  %s: %s" % (os.path.relpath(p, base) if base else p,
                                "in its place " + os.path.basename(o) if o else "no replacement found") for p, o in done]
        for line in lines:
            say(line)
        write_text(note, "\n".join(lines))
    else:
        with suppress(FileNotFoundError):
            os.remove(note)


# ---- the source: the .nup's newest title, or a folder ----

class NupSource:
    def __init__(self, nup, path):
        self.nup, self.pkg = nup, nup.Nup(path)
        title = nup.pick_title(self.pkg, None)
        self.title = "title %d (v%d)" % (title["index"], title["version"])
        digests = {id(r): d[0] for r, d in zip(self.pkg.files, getattr(self.pkg, "file_details", ()))}
        found = [(rel, r[2], r, digests.get(id(r))) for rel, r in self.pkg.walk(title["romfs"])]
        found.sort(key=lambda f: f[0].encode())
        self.files = [(rel, size) for rel, size, _, _ in found]
        self.refs = [(r, d if d and d != bytes(32) else None) for _, _, r, d in found]

    def copy(self, i, sink):
        self.pkg.copy_to(self.refs[i][0], sink, self.files[i][0])

    def expected(self, i):
        return self.refs[i][1]

    def close(self):
        self.pkg.f.close()


class FolderSource:
    def __init__(self, nup, romfs):
        self.root, self.title = romfs, "the folder %s" % romfs
        root = nup.long_path(romfs)
        found = []
        for folder, dirs, names in os.walk(root):
            rel = os.path.relpath(folder, root).replace(os.sep, "/")
            for n in names:
                p = n if rel == "." else rel + "/" + n
                found.append((p, os.path.getsize(os.path.join(folder, n))))
        found.sort(key=lambda f: f[0].encode())
        self.files, self.long = found, root

    def copy(self, i, sink):
        with open(os.path.join(self.long, *self.files[i][0].split("/")), "rb") as f:
            for block in iter(lambda: f.read(8 << 20), b""):
                sink.write(block)

    def expected(self, i):
        return None

    def close(self):
        pass


class PackSink:
    """A file's bytes into its pack: counted, hashed, its first 4 bytes kept (is it zstd?)"""
    def __init__(self, out):
        self.out, self.size, self.head, self.hash = out, 0, b"", hashlib.sha256()

    def write(self, data):
        if len(self.head) < 4:
            self.head += bytes(data[:4 - len(self.head)])
        self.hash.update(data)
        self.size += len(data)
        return self.out.write(data)


# ---- packs (the default) ----

def make_packs(nup, source, app, stamp, limit):
    """The packs, then each group's index into its last part, then the manifest (data_packs.py). A pack's data, once written
    whole, is kept by a later build of the same game file (longshot_data_packs.json); the indexes and the manifest are made
    again each time (seconds)"""
    data = os.path.join(app, DATA)
    index = os.path.join(app, data_packs.INDEX_NAME)
    progress = os.path.join(app, PROGRESS)
    with suppress(FileNotFoundError):   # (the packs are whole only once the manifest is written again)
        os.remove(index)
    files = source.files
    packs = data_packs.plan(files, limit)
    bid = data_packs.build_id("%s %d" % (stamp, limit))
    names = {p.name for p in packs}
    try:
        with open(progress, encoding="utf-8") as f:
            state = json.load(f)
        if state.get("stamp") != stamp or state.get("limit") != limit or state.get("id") != bid.hex():
            state = None
    except (OSError, ValueError):
        state = None
    state = state or {"stamp": stamp, "limit": limit, "id": bid.hex(), "data": {}}
    os.makedirs(data, exist_ok=True)

    def written(p):
        """where a pack whose data is whole already is (X.pak.part, or X.pak from a build stopped after it), else None"""
        if p.name not in state["data"]:
            return None
        for path in (os.path.join(data, p.name + ".part"), os.path.join(data, p.name)):
            with suppress(OSError):
                if os.path.getsize(path) >= data_packs.PACK_HEAD + p.size:
                    return path
        return None

    keep = {os.path.basename(w) for w in map(written, packs) if w}
    for entry in os.listdir(data):   # (a Data folder of loose files, or packs of another layout: made again)
        if entry in keep:
            continue
        path = os.path.join(data, entry)
        if os.path.isdir(path):
            remove_tree(nup, path)
        else:
            os.remove(path)
    groups = []
    for p in packs:
        if not groups or groups[-1][0] != p.group:
            groups.append((p.group, []))
        groups[-1][1].append(p)
    number_of = {g: n for n, (g, _) in enumerate(groups)}
    todo = [p for p in packs if not written(p)]
    check_room(data, on_disk([data_packs.PACK_HEAD + p.size for p in todo], cluster_size(data)) + 128 * len(files),
               "%d files in %d packs (%d to write)" % (len(files), len(packs), len(todo)))
    at = data_packs.places(packs, files)
    damaged = set(int(i) for p in state["data"].values() for i in p["damaged"])
    done = 0
    for number, p in enumerate(packs):
        if written(p):
            continue
        say("pack %d of %d: %s (%d files, %.2f GB)" % (number + 1, len(packs), p.name, len(p.members), p.size / 1e9))
        path = os.path.join(data, p.name + ".part")
        bad = []
        with open(path, "wb") as out:
            out.write(data_packs.pack_header(number, p.part, number_of[p.group], bid, p.size))
            for i in p.members:
                out.write(bytes(at[i][1] - (out.tell() - data_packs.PACK_HEAD)))
                sink = PackSink(out)
                source.copy(i, sink)
                if sink.size != files[i][1]:
                    raise SystemExit("%s came out as %d bytes, %d expected" % (files[i][0], sink.size, files[i][1]))
                expected = source.expected(i)
                if files[i][0].endswith(".zs") and (not data_packs.zstd_start(sink.head) or
                                                    expected is not None and sink.hash.digest() != expected):
                    bad.append(i)
            if out.tell() != data_packs.PACK_HEAD + p.size:
                raise SystemExit("%s came out as %d bytes, %d planned" % (p.name, out.tell(), data_packs.PACK_HEAD + p.size))
        damaged.update(bad)
        state["data"][p.name] = {"damaged": bad}
        with open(progress + ".part", "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.replace(progress + ".part", progress)
        done += p.size
        say("  %.1f GB written" % (done / 1e9))
    aliases = data_packs.stand_ins(files, damaged)
    # (each group's index at the end of its last part; every pack's header says where it is; then each X.pak in place)
    group_rows, pack_rows = [], []
    number = 0
    for g, (group, parts) in enumerate(groups):
        members = [i for p in parts for i in p.members]
        group_rows.append((group, number, len(parts), len(members)))
        for p in parts:
            src = written(p)
            with open(src, "r+b") as f:
                f.truncate(data_packs.PACK_HEAD + p.size)   # (an index from an earlier try is written again)
                index_at = index_size = 0
                digest = None
                if p is parts[-1]:
                    raw = data_packs.group_index(group, g, members, files, at, bid, len(parts), aliases)
                    index_at = -(-(data_packs.PACK_HEAD + p.size) // 8) * 8
                    f.seek(data_packs.PACK_HEAD + p.size)
                    f.write(bytes(index_at - data_packs.PACK_HEAD - p.size) + raw)
                    index_size, digest = len(raw), hashlib.sha256(raw).digest()
                f.seek(0)
                f.write(data_packs.pack_header(number, p.part, g, bid, p.size, index_at, index_size))
            final = os.path.join(data, p.name)
            if src != final:
                os.replace(src, final)
            pack_rows.append((p.name, g, p.part, os.path.getsize(final), index_at, index_size, digest))
            number += 1
    with open(index + ".part", "wb") as f:
        f.write(data_packs.manifest(group_rows, pack_rows, bid, len(files)))
    os.replace(index + ".part", index)
    with suppress(FileNotFoundError):
        os.remove(progress)
    write_damaged_note(app, [(files[d][0], files[aliases[d]][0] if d in aliases else None) for d in sorted(damaged)], None)
    say("game data: %d files in %d packs (%d groups, each with its index), %.2f GB, and the manifest %s"
        % (len(files), len(packs), len(groups), sum(p.size for p in packs) / 1e9, data_packs.INDEX_NAME))


# ---- a folder of loose files (--folder) ----

def from_folder(nup, romfs, app):
    data = os.path.join(app, DATA)
    if not os.path.isdir(romfs):
        raise SystemExit("the game folder has no romfs/ to take the game's data from: %s" % romfs)
    say("copying the game's data from %s to %s" % (romfs, data))
    shutil.copytree(nup.long_path(romfs), nup.long_path(data), dirs_exist_ok=True)


def from_nup(nup, path, app, stamp):
    data = os.path.join(app, DATA)
    stage = os.path.join(os.path.dirname(os.path.abspath(app)), STAGE)
    started = os.path.join(stage, ".from")
    romfs = os.path.join(stage, "romfs")
    if os.path.isdir(data):
        if read_text(started) == stamp and not os.path.exists(romfs):   # (moved in, stopped before its mark: checked again)
            os.replace(nup.long_path(data), nup.long_path(romfs))
        else:
            say("the Data folder there is from another game file or builder: it is made again")
            remove_tree(nup, data)
    if read_text(started) != stamp:
        remove_tree(nup, stage)
        os.makedirs(stage)
        write_text(started, stamp)
    pkg = nup.Nup(path)
    try:
        title = nup.pick_title(pkg, None)
        need, files = [], 0
        for rel, record in pkg.walk(title["romfs"]):
            files += 1
            with suppress(OSError):
                if os.path.getsize(nup.long_path(os.path.join(romfs, *rel.split("/")))) == record[2]:
                    continue
            need.append(record[2])
        check_room(stage, on_disk(need, cluster_size(stage)), "%d files as a folder" % files)
        say("extracting title %d (v%d): every game file, into %s" % (title["index"], title["version"], romfs))
        n, total = nup.extract(pkg, title, stage, only="romfs")
        say("extracted: %d files written now, %.2f GB" % (n, total / 1e9))
    finally:
        pkg.f.close()
    heads = nup.read_heads(os.path.join(stage, nup.HEADS_NAME))
    if heads is None:
        say("checking the game files for damaged textures: every .zs file is opened, which can take minutes")
        done = nup.stand_in_damaged(romfs)
    else:
        done = nup.stand_in_damaged(romfs, damaged=[os.path.normpath(os.path.join(romfs, rel)) for rel in heads])
    write_damaged_note(app, done, romfs)
    os.replace(nup.long_path(romfs), nup.long_path(data))
    return stage


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--src", required=True, help="the folder with nx2/ (the kit's src)")
    ap.add_argument("--app", required=True, help="the title folder")
    game = ap.add_mutually_exclusive_group(required=True)
    game.add_argument("--nup")
    game.add_argument("--romfs")
    ap.add_argument("--folder", action="store_true", help="the game's data as loose files in Data/, not packs")
    ap.add_argument("--pack-limit", type=int, default=data_packs.LIMIT, help=argparse.SUPPRESS)   # (the checks' small packs)
    a = ap.parse_args()
    sys.path.insert(0, os.path.join(a.src, "nx2"))
    import nup
    mark = os.path.join(a.app, DATA_MARK)
    stamp = stamp_of(a.nup or a.romfs)
    if not a.folder:
        stamp = "packs %s" % stamp
    whole = os.path.isfile(os.path.join(a.app, data_packs.INDEX_NAME)) if not a.folder else (
        os.path.isdir(os.path.join(a.app, DATA)) and not os.path.exists(os.path.join(a.app, data_packs.INDEX_NAME)))
    if read_text(mark) == stamp and whole:
        say("the game's data is there already, from this game file")
        return 0
    with suppress(FileNotFoundError):   # (removed first: the data is whole only once it is written again)
        os.remove(mark)
    stage = None
    if a.folder:
        with suppress(FileNotFoundError):   # (a pack index would be read before the folder: host/hos_main.c)
            os.remove(os.path.join(a.app, data_packs.INDEX_NAME))
        stage = from_nup(nup, a.nup, a.app, stamp) if a.nup else from_folder(nup, a.romfs, a.app)
    else:
        source = NupSource(nup, a.nup) if a.nup else FolderSource(nup, a.romfs)
        try:
            say("game data from %s, as packs" % source.title)
            make_packs(nup, source, a.app, stamp, a.pack_limit)
        finally:
            source.close()
    write_text(mark, stamp)
    if stage:
        remove_tree(nup, stage)
    say("game data: %s" % os.path.join(a.app, DATA))
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
