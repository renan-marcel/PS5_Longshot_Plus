"""Game-free: the console's pack reader (host/ps5/pak_romfs.c), compiled for the PC with AddressSanitizer, reads the packs
the builder makes (ps5/builder/game_data.py, from a package authored here: tests/test_ps5_game_data.py's) and gives back
each game file byte for byte, as the builder's reference reader does (ps5/builder/data_packs.py Index): files of every
folder, a damaged texture pointing at a whole one, a path with '//' (the game's voices, #1298), case, folder listings in
order, files in a pack split into parts; and refuses, saying why, a pack cut short, a pack of another build and an index
cut short, a group index changed, and an older builder's index.
python -I -B tests/test_pak_romfs.py [--cc gcc]"""
import argparse
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
from unittest import mock

RUN_ALL_ARGS = ["--cc", "gcc"]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
sys.path.insert(0, str(ROOT / "ps5" / "builder"))
import data_packs  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


game_data = load("game_data_for_pak_romfs", ROOT / "ps5" / "builder" / "game_data.py")
authored = load("authored_package_for_pak_romfs", ROOT / "tests" / "test_ps5_game_data.py")


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def make(app, romfs, *extra):
    game = app.parent / ("game-%d.nup" % len(list(app.parent.glob("game-*.nup"))))
    authored.author(game, romfs=romfs)
    argv = ["game_data.py", "--src", str(ROOT), "--app", str(app), "--nup", str(game), *extra]
    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
        need(game_data.main() == 0, "the builder made the packs")


def run(exe, app, out, paths):
    r = subprocess.run([str(exe), str(app / "Data.idx"), str(app / "Data"), str(out), *paths], capture_output=True, text=True,
                       env=dict(os.environ, ASAN_OPTIONS="detect_leaks=0:abort_on_error=0"))
    need(r.returncode in (0, 3), "the reader ran (exit %d): %s" % (r.returncode, r.stderr[-1500:]))
    need("ERROR: AddressSanitizer" not in r.stderr and "runtime error" not in r.stderr, "no memory error: " + r.stderr[-1500:])
    return r.returncode, r.stdout


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        exe = tmp / "pak_romfs_test"
        cc = subprocess.run([a.cc, "-std=c11", "-O1", "-g", "-Wall", "-Werror", "-fsanitize=address,undefined",
                             "-fno-sanitize-recover=undefined", "-I", str(ROOT / "host" / "ps5"),
                             str(ROOT / "host" / "ps5" / "pak_romfs.c"), str(ROOT / "tests" / "pak_romfs_test.c"), "-o",
                             str(exe)], capture_output=True, text=True)
        need(cc.returncode == 0, "pak_romfs.c compiles: " + cc.stderr[-2000:])

        romfs = dict(authored.ROMFS)
        romfs.update({"Tex/%02d.bntx.zs" % i: authored.WHOLE + bytes([i]) * 50 for i in range(8)})
        romfs["Event/Movie/Long Name - ÜTF8.webm"] = bytes(range(256)) * 9
        app = tmp / "t1" / "PPSA99198"
        app.mkdir(parents=True)
        make(app, romfs, "--pack-limit", "300")
        packs = sorted(p.name for p in (app / "Data").iterdir())
        need(sum(n.startswith("Tex.") for n in packs) > 1, "Tex split into parts: %s" % packs)
        idx = data_packs.Index(str(app))
        paths = [p for p, _ in idx.walk()]
        asks = paths + ["Voice/Resource//Stream/x.bwav", "model/a_Alb.bntx.zs", "Model/none.zs", "Model", "", "/System//plain.bin",
                        "/", "Model/", "Voice/Resource/", "Event/Movie/", "Nope/"]
        out = tmp / "out1"
        out.mkdir()
        code, said = run(exe, app, out, asks)
        need(code == 0, "the packs open: " + said)
        lines = said.splitlines()
        for i, path in enumerate(asks):
            line = lines[i]
            if path.endswith("/"):
                continue
            if idx.find(path) != "file":
                need(line == "missing " + path, "%r is not a file: %r" % (path, line))
                continue
            data = idx.read(path)
            need(line == "file %s %d" % (path, len(data)), "%r: %r" % (path, line))
            need((out / ("%d.bin" % (i + 4))).read_bytes() == data, "%r comes back byte for byte" % path)
        need((out / "4.bin").exists(), "files written")
        need(idx.read("Model/b_Alb.bntx.zs") == authored.WHOLE, "the damaged texture reads as the whole one")
        listing = {l.split(":")[0][4:]: l.split(":", 1)[1].split() for l in lines if l.startswith("dir ")}
        need(listing["/"] == ["Event/", "Model/", "System/", "Tex/", "Voice/"], "root listing in order: %s" % listing["/"])
        need(listing["Model/"] == ["a_Alb.bntx.zs", "b_Alb.bntx.zs"], "Model listing: %s" % listing["Model/"])
        need(listing["Voice/Resource/"] == ["Stream/"], "nested folder listing: %s" % listing["Voice/Resource/"])
        need(listing["Nope/"] == [], "no such folder lists nothing")
        need(lines[-1] == "outside: 0 0", "paths outside the root are not the packs': " + lines[-1])
        idx.close()

        def refused(change, words):
            bad = tmp / ("bad-%d" % len(list(tmp.glob("bad-*")))) / "PPSA99198"
            bad.mkdir(parents=True)
            make(bad, authored.ROMFS)
            change(bad)
            code, said = run(exe, bad, tmp, ["System/plain.bin"])
            need(code == 3 and words in said, "refused (%s): %r" % (words, said))

        def cut(path, n):
            path.write_bytes(path.read_bytes()[:-n])

        def flip(path, at):
            raw = bytearray(path.read_bytes())
            raw[at] ^= 0xff
            path.write_bytes(bytes(raw))

        refused(lambda b: cut(b / "Data" / "Voice.pak", 1), "incomplete copy")
        refused(lambda b: flip(b / "Data" / "Voice.pak", 0x10), "another build")
        refused(lambda b: (b / "Data" / "Voice.pak").unlink(), "is missing")
        refused(lambda b: cut(b / "Data.idx", 64), "outside the file")
        refused(lambda b: flip(b / "Data.idx", 0), "not a data manifest")

        def index_magic(b):   # (the group index's own header, at the end of the group's last pack)
            pack = b / "Data" / "Voice.pak"
            flip(pack, struct.unpack_from("<Q", pack.read_bytes(), 0x28)[0])
        refused(index_magic, "the index of group")

        def version_1(b):   # (a manifest from before the groups: an older builder's)
            raw = bytearray((b / "Data.idx").read_bytes())
            raw[0:4] = b"LSIX"
            (b / "Data.idx").write_bytes(bytes(raw))
        refused(version_1, "older builder")
    print("pak_romfs: every file byte for byte through the C reader; refusals said")


if __name__ == "__main__":
    main()
