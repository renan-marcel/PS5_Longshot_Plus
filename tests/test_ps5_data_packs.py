"""Game-free: the PS5 builder's default game data, packs with an index (ps5/builder/data_packs.py, docs/ps5-data-packs.md):
every game file comes back from its pack byte for byte through the index, as nx2/nup.py extracts it; damaged textures point
at a whole one of their kind; large folders split into parts; a stopped build keeps the packs it finished; an incomplete
copy, a pack of another build or a changed index is refused with what is wrong; switching to and from --folder leaves no
mix of the two; the room check counts the drive's clusters. A package is authored here (tests/test_ps5_game_data.py's).
python -I -B tests/test_ps5_data_packs.py"""
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
sys.path.insert(0, str(ROOT / "ps5" / "builder"))
import nup  # noqa: E402
import data_packs  # noqa: E402


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


game_data = load("game_data_packs_under_test", ROOT / "ps5" / "builder" / "game_data.py")
authored = load("authored_package", ROOT / "tests" / "test_ps5_game_data.py")
ROMFS, WHOLE, DAMAGED, author = authored.ROMFS, authored.WHOLE, authored.DAMAGED, authored.author


def build(app, game, *extra):
    argv = ["game_data.py", "--src", str(ROOT), "--app", str(app), "--nup" if os.path.isfile(game) else "--romfs", str(game),
            *extra]
    out = io.StringIO()
    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(out):
        code = game_data.main()
    return code, out.getvalue()


class Packs(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.app = self.tmp / "out" / "PPSA99198"
        self.app.mkdir(parents=True)
        self.game = self.tmp / "game.nup"
        author(self.game)

    def index(self):
        idx = data_packs.Index(str(self.app))
        self.addCleanup(idx.close)
        return idx

    def test_every_file_comes_back_through_the_index(self):
        code, said = build(self.app, self.game)
        self.assertEqual(code, 0, said)
        idx = self.index()
        got = {path for path, _ in idx.walk()}
        self.assertEqual(got, set(ROMFS))
        for path, data in ROMFS.items():
            if path != "Model/b_Alb.bntx.zs":
                self.assertEqual(idx.read(path), data, path)
        data = self.app / "Data"
        self.assertEqual(sorted(p.name for p in data.iterdir()), ["Model.pak", "System.pak", "Voice.pak"])
        self.assertFalse((self.app / game_data.PROGRESS).exists())
        self.assertEqual((self.app / game_data.DATA_MARK).read_text(encoding="utf-8").strip(),
                         "packs " + game_data.stamp_of(str(self.game)))

    def test_paths_and_listing_as_the_console_reads_them(self):
        build(self.app, self.game)
        idx = self.index()
        self.assertEqual(idx.read("Voice/Resource//Stream/x.bwav"), ROMFS["Voice/Resource/Stream/x.bwav"])   # (#1298)
        self.assertEqual(idx.listdir(""), [("Model", True), ("System", True), ("Voice", True)])
        self.assertEqual(idx.listdir("Model"), [("a_Alb.bntx.zs", False), ("b_Alb.bntx.zs", False)])
        self.assertIsNone(idx.find("model/a_Alb.bntx.zs"))   # (case-sensitive, as the console's romfs)
        self.assertIsNone(idx.find("Model/none.zs"))

    def test_a_damaged_texture_points_at_a_whole_one(self):
        build(self.app, self.game)
        idx = self.index()
        self.assertEqual(idx.read("Model/b_Alb.bntx.zs"), WHOLE)
        flags = dict(idx.walk())
        self.assertEqual(flags["Model/b_Alb.bntx.zs"], data_packs.ALIAS)
        self.assertEqual(flags["Model/a_Alb.bntx.zs"], 0)
        self.assertIn("b_Alb.bntx.zs", (self.app / game_data.DAMAGED_NOTE).read_text(encoding="utf-8"))
        data = struct.unpack_from("<Q", (self.app / "Data" / "Model.pak").read_bytes(), 0x20)[0]
        self.assertLess(data, 2 * 16 + len(WHOLE) + len(DAMAGED) + 1)   # (the bytes not copied twice)

    def test_a_large_folder_splits_into_parts(self):
        many = {"Tex/%02d.bntx.zs" % i: WHOLE + bytes([i]) * 40 for i in range(10)}
        author(self.game, romfs={**ROMFS, **many})
        code, said = build(self.app, self.game, "--pack-limit", "200")
        self.assertEqual(code, 0, said)
        names = sorted(p.name for p in (self.app / "Data").iterdir())
        self.assertIn("Tex.0.pak", names)
        self.assertGreater(sum(n.startswith("Tex.") for n in names), 2)
        self.assertNotIn("Tex.pak", names)
        tex = sorted((n for n in names if n.startswith("Tex.")), key=lambda n: int(n.split(".")[1]))
        for p in (self.app / "Data").iterdir():   # (data at most the limit; the group's index after it, in its last part)
            raw = p.read_bytes()
            data, index_at, index_size = struct.unpack_from("<QQQ", raw, 0x20)
            self.assertLessEqual(data, 200)
            self.assertEqual(bool(index_size), not p.name.startswith("Tex.") or p.name == tex[-1], p.name)
            if index_size:
                self.assertEqual(raw[index_at:index_at + 4], b"LSGI")
        idx = self.index()
        for path, data in many.items():
            self.assertEqual(idx.read(path), data)

    def test_a_stopped_build_keeps_its_finished_packs(self):
        with mock.patch.object(data_packs, "manifest", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                build(self.app, self.game)
        self.assertTrue((self.app / game_data.PROGRESS).exists())
        self.assertFalse((self.app / data_packs.INDEX_NAME).exists())
        code, said = build(self.app, self.game)
        self.assertEqual(code, 0, said)
        self.assertNotIn("pack 1 of", said)   # (none written again)
        self.assertEqual(self.index().read("System/plain.bin"), ROMFS["System/plain.bin"])

    def test_a_pack_cut_short_is_written_again(self):
        with mock.patch.object(data_packs, "manifest", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                build(self.app, self.game)
        pack = self.app / "Data" / "System.pak"
        pack.write_bytes(pack.read_bytes()[:data_packs.PACK_HEAD + 2])   # (its data cut short: written again)
        build(self.app, self.game)
        self.assertEqual(self.index().read("System/plain.bin"), ROMFS["System/plain.bin"])

    def test_a_second_build_from_the_same_file_does_not_open_it(self):
        build(self.app, self.game)
        with mock.patch.object(nup, "Nup", side_effect=AssertionError("the .nup was opened again")):
            code, said = build(self.app, self.game)
        self.assertEqual(code, 0)
        self.assertIn("there already", said)

    def test_an_incomplete_copy_is_refused_with_what_is_wrong(self):
        build(self.app, self.game)
        pack = self.app / "Data" / "Voice.pak"
        pack.write_bytes(pack.read_bytes()[:-1])
        with self.assertRaisesRegex(ValueError, "Voice.pak is .* bytes, the manifest says"):
            data_packs.Index(str(self.app))

    def test_a_pack_of_another_build_is_refused(self):
        build(self.app, self.game)
        pack = self.app / "Data" / "Voice.pak"
        raw = bytearray(pack.read_bytes())
        raw[0x10] ^= 0xff
        pack.write_bytes(bytes(raw))
        with self.assertRaisesRegex(ValueError, "not this manifest's pack"):
            data_packs.Index(str(self.app))

    def test_a_changed_group_index_is_refused(self):
        build(self.app, self.game)
        pack = self.app / "Data" / "Voice.pak"
        raw = bytearray(pack.read_bytes())
        raw[-1] ^= 1   # (the last byte of the group's names)
        pack.write_bytes(bytes(raw))
        with self.assertRaisesRegex(ValueError, "index does not match the manifest"):
            data_packs.Index(str(self.app))

    def test_a_changed_manifest_is_refused(self):
        build(self.app, self.game)
        index = self.app / data_packs.INDEX_NAME
        raw = bytearray(index.read_bytes())
        raw[-1] ^= 1
        index.write_bytes(bytes(raw))
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            data_packs.Index(str(self.app))

    def test_the_layout(self):
        build(self.app, self.game)
        raw = (self.app / data_packs.INDEX_NAME).read_bytes()
        self.assertEqual(raw[:4], b"LSMF")
        self.assertLess(len(raw), 1024)   # (the manifest: groups and packs only)
        groups, packs, nfiles = struct.unpack_from("<IIQ", raw, 0x20)
        self.assertEqual((groups, packs, nfiles), (3, 3, len(ROMFS)))
        for i in range(3):
            off, size = struct.unpack_from("<QQ", raw, 0x30 + 16 * i)
            self.assertEqual(off % 8, 0)
            self.assertLessEqual(off + size, len(raw))
        for name in ("Model.pak", "System.pak", "Voice.pak"):
            pack = (self.app / "Data" / name).read_bytes()
            self.assertEqual(pack[:4], b"LSPK")
            self.assertEqual(struct.unpack_from("<I", pack, 4)[0], data_packs.VERSION)
            self.assertEqual(pack[0x10:0x20], raw[0x10:0x20])
            data, index_at, index_size = struct.unpack_from("<QQQ", pack, 0x20)
            self.assertEqual(index_at % 8, 0)
            self.assertGreaterEqual(index_at, data_packs.PACK_HEAD + data)
            self.assertEqual(index_at + index_size, len(pack))
            self.assertEqual(pack[index_at:index_at + 4], b"LSGI")
            cap = struct.unpack_from("<I", pack, index_at + 0x2c)[0]
            self.assertEqual(cap & (cap - 1), 0)

    def test_folder_then_packs_leaves_no_loose_files(self):
        build(self.app, self.game, "--folder")
        self.assertTrue((self.app / "Data" / "System" / "plain.bin").exists())
        build(self.app, self.game)
        self.assertFalse((self.app / "Data" / "System").exists())
        self.assertEqual(self.index().read("System/plain.bin"), ROMFS["System/plain.bin"])

    def test_packs_then_folder_leaves_no_index(self):
        build(self.app, self.game)
        code, said = build(self.app, self.game, "--folder")
        self.assertEqual(code, 0, said)
        self.assertFalse((self.app / data_packs.INDEX_NAME).exists())
        self.assertFalse(list((self.app / "Data").glob("*.pak")))
        self.assertEqual((self.app / "Data" / "System" / "plain.bin").read_bytes(), ROMFS["System/plain.bin"])

    def test_a_game_folder_makes_the_same_packs(self):
        folder = self.tmp / "unpacked" / "romfs"
        for rel, data in ROMFS.items():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(data)
        code, said = build(self.app, folder)
        self.assertEqual(code, 0, said)
        idx = self.index()
        self.assertEqual(idx.read("Voice/Resource/Stream/x.bwav"), ROMFS["Voice/Resource/Stream/x.bwav"])
        self.assertEqual(idx.read("Model/b_Alb.bntx.zs"), WHOLE)   # (damaged there too: it does not start as zstd)

    def test_too_little_room_stops_before_a_pack_is_written(self):
        with mock.patch.object(game_data.shutil, "disk_usage", return_value=mock.Mock(free=1 << 20)):
            with self.assertRaises(SystemExit) as stop:
                build(self.app, self.game)
        self.assertIn("GB free", str(stop.exception))
        self.assertFalse(list((self.app / "Data").glob("*.pak*")))

    def test_the_folder_room_check_counts_clusters(self):
        # (content of a few dozen bytes, but each of the 4 files takes a whole 256 KB cluster: 1 MB, one byte short here)
        free = game_data.ROOM + (1 << 20) - 1
        with mock.patch.object(game_data, "cluster_size", return_value=256 << 10), \
                mock.patch.object(game_data.shutil, "disk_usage", return_value=mock.Mock(free=free)):
            with self.assertRaises(SystemExit) as stop:
                build(self.app, self.game, "--folder")
        self.assertIn("GB free", str(stop.exception))
        self.assertEqual(game_data.on_disk([1, 256 << 10, (256 << 10) + 1], 256 << 10), 4 * (256 << 10))


class Console(unittest.TestCase):
    """The console reads the packs at every place the romfs is read (docs/ps5-data-packs.md section 5)"""
    def test_the_title_folder_index_is_opened_first(self):
        text = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
        block = text[text.index("#ifdef __PROSPERO__\n                /* (PS5) the title folder"):]
        block = block[:block.index("#elif")]
        self.assertIn('SEP_S "Data.idx"', block)
        self.assertLess(block.index("pak_romfs_open(beside_index, beside_data)"), block.index("hos_romfs_dir = beside_data"))
        self.assertIn('hos_romfs_dir = "/pak/romfs"', block)
        self.assertIn('#define PAK_ROMFS_ROOT "/pak/romfs"', (ROOT / "host" / "ps5" / "pak_romfs.h").read_text(encoding="utf-8"))

    def test_every_file_call_knows_the_packs(self):
        text = (ROOT / "host" / "posix" / "win32_posix.c").read_text(encoding="utf-8")

        def body(head):
            at = text.index(head)
            return text[at:text.index("\n}\n", at)]
        for head, word in (("HANDLE IO_INNER(CreateFileA)(", "pak_romfs_find"), ("IO_INNER(ReadFile)(", "PAK_FILE"),
                           ("IO_INNER(WriteFile)(", "PAK_FILE"), ("BOOL SetFilePointerEx(", "PAK_FILE"),
                           ("BOOL GetFileSizeEx(", "PAK_FILE"), ("BOOL SetEndOfFile(", "PAK_FILE"),
                           ("DWORD GetFileType(", "PAK_FILE"), ("DWORD GetFileAttributesA(", "pak_romfs_find"),
                           ("static BOOL find_next(", "pak_romfs_dir_next"), ("HANDLE FindFirstFileA(", "pak_romfs_find"),
                           ("BOOL CloseHandle(", "PAK_FILE")):
            self.assertIn(word, body(head), head)

    def test_the_menu_font_reads_through_the_packs(self):
        text = (ROOT / "gpu" / "vk" / "vk_game_font.h").read_text(encoding="utf-8")
        read = text[text.index("inline bool read_file("):text.index("fopen(path.c_str()")]
        self.assertIn("pak_romfs_read(", read)

    def test_every_romfs_reader_is_known(self):
        # (a new reader of the romfs root must be added to docs/ps5-data-packs.md section 5.3 and read through the packs)
        known = {"host/hos_main.c", "host/nn_fs.c", "host/prompts.c", "host/rx_backend.c",   # (hos_romfs_dir)
                 "gpu/vk/vk_imgui.cpp"}                                                   # (the host's romfs_dir: the font)
        found = set()
        for folder in ("host", "gpu"):
            for path in (ROOT / folder).rglob("*.[ch]*"):
                text = path.read_text(encoding="utf-8", errors="replace")
                if "hos_romfs_dir" in text or "host->romfs_dir" in text:
                    found.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(found, known)


if __name__ == "__main__":
    unittest.main()
