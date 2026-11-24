"""Game-free: the PS5 builder puts the game's whole romfs into the title folder's Data/ as plain files
(ps5/builder/game_data.py), and the console reads every game file from there, never from the .nup (host/hos_main.c,
host/posix/win32_posix.c).

A package is authored here (no game data): one title whose romfs holds whole and damaged .zs files and a voice file
under Voice/Resource/Stream; it is extracted the way a build does, then built again, stopped part way, and given another
package. python -I -B tests/test_ps5_game_data.py"""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "nx2"))
import nup  # noqa: E402

spec = importlib.util.spec_from_file_location("game_data_under_test", ROOT / "ps5" / "builder" / "game_data.py")
game_data = importlib.util.module_from_spec(spec)
spec.loader.exec_module(game_data)

# (a zstd magic and a frame header that states no size: nup.py takes it as the game's own .zs, kept as is)
WHOLE = nup.ZSTD + b"\x00" + b"authored whole texture"
DAMAGED = b"\x00\x00\x00\x00authored damaged texture"
ROMFS = {
    "Model/a_Alb.bntx.zs": WHOLE,
    "Model/b_Alb.bntx.zs": DAMAGED,
    "Voice/Resource/Stream/x.bwav": b"authored voice",
    "System/plain.bin": b"authored plain file",
}
EXEFS = {"main": b"NSO0authored"}


def author(path, romfs=ROMFS, exefs=EXEFS):
    """A .nup with one title (nx2/nup.py's layout): root/exefs and root/romfs, every file raw"""
    dirs, files, names = [], [], b""   # dirs: [name, children]; files: [name, data]

    def name(text):
        nonlocal names
        at = len(names)
        names += text.encode()
        return at, len(text.encode())

    def folder(text):
        dirs.append([name(text), []])
        return len(dirs) - 1

    root = folder("")
    tops = {}
    for part, members in (("exefs", exefs), ("romfs", romfs)):
        tops[part] = folder(part)
        dirs[root][1].append(("d", tops[part]))
        made = {"": tops[part]}
        for rel, data in members.items():
            parts = rel.split("/")
            for i in range(1, len(parts)):
                key = "/".join(parts[:i])
                if key not in made:
                    made[key] = folder(parts[i - 1])
                    dirs[made["/".join(parts[:i - 1])]][1].append(("d", made[key]))
            files.append([name(parts[-1]), data])
            dirs[made["/".join(parts[:-1])]][1].append(("f", len(files) - 1))
    nd, nf, nt = len(dirs), len(files), 1
    kids, firsts = [], []
    for _, children in dirs:
        firsts.append(len(kids))
        kids += [i if kind == "d" else nd + i for kind, i in children]
    tables = 0x30 + 0x40 * nt + 24 * nd + 80 * nf + 4 * len(kids)
    soff = tables
    toc_size = soff + len(names)
    blob = (0x80 + toc_size + 15) & ~15
    data, offsets = b"", []
    for _, member in files:
        offsets.append(blob + len(data))
        data += member + b"\x00" * (-len(member) % 16)
    toc = b"TOC\x01" + struct.pack("<IQQQQ", nt, nd, nf, soff, len(names)) + b"\x00" * 8
    toc += struct.pack("<QIIII", 0x0400486024DEC000, root, tops["exefs"], tops["romfs"], 131072).ljust(0x40, b"\x00")
    for ((no, nl), children), first in zip(dirs, firsts):
        toc += struct.pack("<4IQ", no, nl, first, len(children), 0)
    for ((no, nl), member), at in zip(files, offsets):
        toc += struct.pack("<IIQQQ", no, nl, len(member), at, len(member)) + b"\x00" * 48
    toc += struct.pack("<%dI" % len(kids), *kids) + names
    size = blob + len(data)
    head = bytearray(0x80)
    head[:4] = b"NUP\x01"
    struct.pack_into("<QQ", head, 8, 0x80, toc_size)
    struct.pack_into("<Q", head, 0x38, blob)
    struct.pack_into("<Q", head, 0x40, size)
    Path(path).write_bytes(bytes(head) + toc + b"\x00" * (blob - 0x80 - len(toc)) + data)


def build(app, game, **given):
    """The --folder layout (loose files in Data/); the default, packs, is tests/test_ps5_data_packs.py's"""
    argv = ["game_data.py", "--src", str(ROOT), "--app", str(app), "--nup" if os.path.isfile(game) else "--romfs", str(game),
            "--folder"]
    out = io.StringIO()
    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
        code = game_data.main()
    return code, out.getvalue()


class Data(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name, "out")
        self.app = self.out / "PPSA99198"
        self.app.mkdir(parents=True)
        self.game = Path(self.tmp.name, "game.nup")
        author(self.game)

    def test_every_game_file_lands_in_data_as_a_plain_file(self):
        code, said = build(self.app, self.game)
        self.assertEqual(code, 0, said)
        data = self.app / game_data.DATA
        got = {p.relative_to(data).as_posix(): p.read_bytes() for p in data.rglob("*") if p.is_file()}
        self.assertEqual(set(got), set(ROMFS))
        self.assertEqual(got["Voice/Resource/Stream/x.bwav"], ROMFS["Voice/Resource/Stream/x.bwav"])
        self.assertEqual(got["System/plain.bin"], ROMFS["System/plain.bin"])
        self.assertFalse((data / "main").exists() or (data / "exefs").exists())

    def test_a_damaged_texture_is_replaced_and_said(self):
        build(self.app, self.game)
        self.assertEqual((self.app / "Data" / "Model" / "b_Alb.bntx.zs").read_bytes(), WHOLE)
        note = (self.app / game_data.DAMAGED_NOTE).read_text(encoding="utf-8")
        self.assertIn("b_Alb.bntx.zs", note)

    def test_the_mark_is_written_and_the_staging_folder_removed(self):
        build(self.app, self.game)
        self.assertEqual((self.app / game_data.DATA_MARK).read_text(encoding="utf-8").strip(), game_data.stamp_of(str(self.game)))
        self.assertFalse((self.out / game_data.STAGE).exists())
        self.assertFalse((self.app / nup.HEADS_NAME).exists())

    def test_a_second_build_from_the_same_file_does_not_open_it(self):
        build(self.app, self.game)
        with mock.patch.object(nup, "Nup", side_effect=AssertionError("the .nup was opened again")):
            code, said = build(self.app, self.game)
        self.assertEqual(code, 0)
        self.assertIn("there already", said)

    def test_a_build_stopped_part_way_goes_on(self):
        stage = self.out / game_data.STAGE
        (stage / "romfs" / "System").mkdir(parents=True)
        (stage / ".from").write_text(game_data.stamp_of(str(self.game)) + "\n", encoding="utf-8")
        (stage / "romfs" / "System" / "plain.bin").write_bytes(b"short")   # (a member cut short: written again)
        (stage / "romfs" / "Model").mkdir()
        kept = stage / "romfs" / "Model" / "a_Alb.bntx.zs"
        kept.write_bytes(WHOLE)
        build(self.app, self.game)
        self.assertEqual((self.app / "Data" / "System" / "plain.bin").read_bytes(), ROMFS["System/plain.bin"])
        self.assertEqual((self.app / "Data" / "Model" / "a_Alb.bntx.zs").read_bytes(), WHOLE)

    def test_moved_in_but_not_marked_is_checked_again(self):
        build(self.app, self.game)
        (self.app / game_data.DATA_MARK).unlink()
        (self.out / game_data.STAGE).mkdir()
        (self.out / game_data.STAGE / ".from").write_text(game_data.stamp_of(str(self.game)) + "\n", encoding="utf-8")
        (self.app / "Data" / "System" / "plain.bin").unlink()
        build(self.app, self.game)
        self.assertEqual((self.app / "Data" / "System" / "plain.bin").read_bytes(), ROMFS["System/plain.bin"])
        self.assertTrue((self.app / game_data.DATA_MARK).exists())

    def test_another_game_file_makes_data_again(self):
        build(self.app, self.game)
        (self.app / "Data" / "stale.bin").write_bytes(b"from another dump")
        other = Path(self.tmp.name, "other.nup")
        author(other, romfs={"System/plain.bin": b"another dump's file"})
        os.utime(other, (1, 1))
        build(self.app, other)
        self.assertFalse((self.app / "Data" / "stale.bin").exists())
        self.assertFalse((self.app / "Data" / "Model").exists())
        self.assertEqual((self.app / "Data" / "System" / "plain.bin").read_bytes(), b"another dump's file")
        self.assertFalse((self.app / game_data.DAMAGED_NOTE).exists())

    def test_a_game_folder_has_its_romfs_copied(self):
        game = Path(self.tmp.name, "unpacked")
        for rel, data in ROMFS.items():
            (game / "romfs" / rel).parent.mkdir(parents=True, exist_ok=True)
            (game / "romfs" / rel).write_bytes(data)
        code, said = build(self.app, game / "romfs")
        self.assertEqual(code, 0, said)
        self.assertEqual((self.app / "Data" / "Voice" / "Resource" / "Stream" / "x.bwav").read_bytes(),
                         ROMFS["Voice/Resource/Stream/x.bwav"])
        self.assertTrue((self.app / game_data.DATA_MARK).exists())

    def test_too_little_room_stops_before_writing(self):
        with mock.patch.object(game_data.shutil, "disk_usage", return_value=mock.Mock(free=1 << 20)):
            with self.assertRaises(SystemExit) as stop:
                build(self.app, self.game)
        self.assertIn("GB free", str(stop.exception))
        self.assertFalse((self.app / "Data").exists())


class Console(unittest.TestCase):
    """The console's runtime reads the romfs from Data/ beside image.bin, and nothing of it from a .nup"""
    def test_no_nup_reader_is_left_in_the_runtime(self):
        for rel in ("host/hos_main.c", "host/posix/win32_posix.c", "host/ps5/win32_ps5.c", "host/ps5/win32_ps5.h"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for word in ("nup_romfs", "hos_ps5_nup", "/nup/romfs"):
                self.assertNotIn(word, text, rel)
        self.assertFalse((ROOT / "host" / "ps5" / "nup_romfs.c").exists())

    def test_the_title_folder_data_is_the_romfs(self):
        text = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
        block = text[text.index("#ifdef __PROSPERO__\n                /* (PS5) the title folder"):]
        block = block[:block.index("#elif")]
        self.assertIn('SEP_S "Data"', block)
        self.assertIn("hos_romfs_dir = beside_data", block)
        self.assertIn('"' + game_data.DATA_MARK + '"', block)


if __name__ == "__main__":
    unittest.main()
