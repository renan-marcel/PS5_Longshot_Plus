"""Game-free: the amiibo catalogue reader (gpu/vk/amiibo_catalogue.h) compiled with the vendored zstd decoder and run on a
catalogue ps5/builder/amiibo.py wrote from a fake AmiiboAPI tree: names, order, a pixel, and the refusals (an index cut in
a record, a missing pack, a picture running past the pack's end, a wrong size).

    python -I -B tests/test_amiibo_catalogue_reader.py [--cxx g++]
"""
import argparse
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
RUN_ALL_MODULES = ["PIL", "zstandard"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ps5" / "builder"))
import amiibo  # noqa: E402

ZSTD = ROOT / "third_party/zstd/lib"
SOURCES = ["common/debug.c", "common/entropy_common.c", "common/error_private.c", "common/fse_decompress.c", "common/xxhash.c",
           "common/zstd_common.c", "decompress/huf_decompress.c", "decompress/zstd_ddict.c", "decompress/zstd_decompress.c",
           "decompress/zstd_decompress_block.c"]
ZELDA = "0x01000000042e0102"
MARIO = "0x0000000000020202"
NO_PICTURE = "0x0001000000000002"
RED, GREEN = (200, 30, 40, 255), (10, 200, 90, 255)

DRIVER = r"""
#include <cstdio>
#include <cstdlib>
#include <string>
#include <vector>
#include "amiibo_catalogue.h"
using namespace mkwvk::amiibo;
// argv: dir mode  (mode "list": every figure and the centre pixel of its picture; "pic N": whether picture N loads)
int main(int argc, char** argv) {
    if (argc < 3) return 2;
    std::string dir = argv[1], mode = argv[2];
    std::vector<Figure> v;
    const bool ok = load(dir, v);
    printf("load %d %zu\n", ok ? 1 : 0, v.size());
    if (mode == "list") {
        for (size_t i = 0; i < v.size(); i++) {
            std::vector<uint8_t> px;
            const bool p = picture(dir, v[i], px);
            printf("%s|%s|%s|%s|%u|%ux%u|pic %d", id_hex(v[i].id).c_str(), v[i].name.c_str(), v[i].series.c_str(),
                   v[i].character.c_str(), v[i].pic_size, v[i].w, v[i].h, p ? 1 : 0);
            if (p) {
                const size_t c = ((size_t)(v[i].h / 2) * v[i].w + v[i].w / 2) * 4;
                if (px.size() != (size_t)v[i].w * v[i].h * 4) return 3;
                printf(" %d,%d,%d,%d", px[c], px[c + 1], px[c + 2], px[c + 3]);
            }
            printf("\n");
        }
        printf("find %d %d\n", find(v, "0x01000000042e0102"), find(v, "ffffffffffffffff"));
    } else if (mode == "pic") {
        std::vector<uint8_t> px;
        printf("pic %d\n", picture(dir, v.at((size_t)atoi(argv[3])), px) ? 1 : 0);
    }
    return 0;
}
"""


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def fake_tree(tree):
    from PIL import Image
    (tree / "database").mkdir(parents=True)
    (tree / "images").mkdir()
    db = {
        "amiibos": {
            MARIO: {"name": "Pokemon Trainer", "release": {}},
            ZELDA: {"name": "Link", "release": {}},
            NO_PICTURE: {"name": "Nobody", "release": {}},
        },
        "amiibo_series": {"0x01": "The Legend of Zelda", "0x02": "Super Mario Bros.", "0x00": "Unknown"},
        "characters": {"0x0000": "Mario", "0x0100": "Link"},
    }
    (tree / "database" / "amiibo.json").write_text(json.dumps(db), encoding="utf-8")
    Image.new("RGBA", (288, 359), RED).save(tree / "images" / "icon_01000000-042e0102.png")
    Image.new("RGBA", (288, 359), GREEN).save(tree / "images" / "icon_00000000-00020202.png")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cxx", default="g++")
    a = ap.parse_args()
    cc = a.cxx[:-2] if a.cxx.endswith("++") else "cc"
    if Path(cc).name == "g" or cc.endswith("-g"):
        cc += "cc"
    flags = ["-O1", "-DZSTD_DISABLE_ASM", "-DZSTD_LEGACY_SUPPORT=0", "-DZSTD_MULTITHREAD=0", "-I" + str(ZSTD)]
    san = ["-fsanitize=address,undefined", "-fno-sanitize-recover=undefined"]
    with tempfile.TemporaryDirectory(prefix="amiibo-reader-") as tmp:
        tmp = Path(tmp)
        objs = []
        for i, f in enumerate(SOURCES):
            o = tmp / ("z%d.o" % i)
            subprocess.run([cc, "-c", str(ZSTD / f), "-o", str(o), "-w"] + flags, check=True)
            objs.append(str(o))
        (tmp / "driver.cpp").write_text(DRIVER)
        exe = tmp / "driver.exe"
        # (the sanitizers when this compiler ships their runtime; some toolchains do not)
        (tmp / "probe.cpp").write_text("int main() { return 0; }")
        if subprocess.run([a.cxx] + san + [str(tmp / "probe.cpp"), "-o", str(tmp / "probe.exe")],
                          capture_output=True).returncode != 0:
            san = []
        subprocess.run([a.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-D_CRT_SECURE_NO_WARNINGS"] + san
                       + ["-I" + str(ROOT / "gpu/vk"), str(tmp / "driver.cpp"), "-o", str(exe)] + flags + objs, check=True)

        def run(d, *args):
            p = subprocess.run([str(exe), str(d)] + [str(x) for x in args], capture_output=True, text=True)
            need(p.returncode == 0, "driver exit %d: %s%s" % (p.returncode, p.stdout, p.stderr))
            return p.stdout.splitlines()

        tree, out = tmp / "api", tmp / "out"
        fake_tree(tree)
        need(amiibo.write_catalogue(str(tree), str(out)) == 3, "write_catalogue count")

        lines = run(out, "list")
        need(lines[0] == "load 1 3", "load: %r" % lines[0])
        rows = [l.split("|") for l in lines[1:4]]
        need([r[1] for r in rows[:1]] == ["Link"], "Zelda first: %r" % rows)
        need(sorted(r[1] for r in rows) == ["Link", "Nobody", "Pokemon Trainer"], "names %r" % rows)
        link = [r for r in rows if r[1] == "Link"][0]
        need(link[0] == ZELDA[2:] and link[2] == "The Legend of Zelda" and link[3] == "Link", "link fields %r" % link)
        need(link[6].startswith("pic 1 ") and link[6].endswith("200,30,40,255"), "link pixel %r" % link[6])
        mario = [r for r in rows if r[1] == "Pokemon Trainer"][0]
        need(mario[6].endswith("10,200,90,255") and mario[3] == "Mario", "mario %r" % mario)
        nopic = [r for r in rows if r[1] == "Nobody"][0]
        need(nopic[4] == "0" and nopic[6] == "pic 0", "no picture %r" % nopic)
        need(lines[4] == "find 0 -1", "find: %r" % lines[4])

        # amiibo.idx cut in the middle of a record -> load false
        idx = (out / "amiibo.idx").read_bytes()
        cut = tmp / "cut"
        shutil.copytree(out, cut)
        (cut / "amiibo.idx").write_bytes(idx[:16 + 136 + 50])
        need(run(cut, "list")[0] == "load 0 0", "a cut index loads")
        # a version other than 1, a bad magic -> false
        for name, data in (("ver", idx[:8] + struct.pack("<I", 2) + idx[12:]), ("magic", b"XSAMIIBO" + idx[8:])):
            d = tmp / name
            shutil.copytree(out, d)
            (d / "amiibo.idx").write_bytes(data)
            need(run(d, "list")[0] == "load 0 0", name + " loads")
        # a count larger than the file holds
        big = tmp / "big"
        shutil.copytree(out, big)
        (big / "amiibo.idx").write_bytes(idx[:12] + struct.pack("<I", 4) + idx[16:])
        need(run(big, "list")[0] == "load 0 0", "an inflated count loads")

        # figures.pak missing -> load true, picture false
        nopak = tmp / "nopak"
        shutil.copytree(out, nopak)
        (nopak / "figures.pak").unlink()
        l = run(nopak, "list")
        need(l[0] == "load 1 3" and all(x.split("|")[6].startswith("pic 0") for x in l[1:4]), "no pack: %r" % l)

        # a record running past the pack's end, an offset past it, an offset near 2^64
        def patched(name, fn):
            d = tmp / name
            shutil.copytree(out, d)
            b = bytearray(idx)
            fn(b)
            (d / "amiibo.idx").write_bytes(bytes(b))
            return d

        def rec(i):
            return 16 + 136 * i
        pak_len = (out / "figures.pak").stat().st_size
        d = patched("past", lambda b: b.__setitem__(slice(rec(0) + 16, rec(0) + 20), struct.pack("<I", pak_len + 1)))
        need(run(d, "pic", 0)[1] == "pic 0", "size past the pack")
        d = patched("off", lambda b: b.__setitem__(slice(rec(0) + 8, rec(0) + 16), struct.pack("<Q", pak_len)))
        need(run(d, "pic", 0)[1] == "pic 0", "offset at the pack's end")
        d = patched("wrap", lambda b: b.__setitem__(slice(rec(0) + 8, rec(0) + 16), struct.pack("<Q", 2**64 - 4)))
        need(run(d, "pic", 0)[1] == "pic 0", "offset near 2^64")
        # a wrong w/h (the frame is not w*h*4), zero, and over the limit
        for name, w, h in (("wh", 100, 100), ("w0", 0, 100), ("w145", 145, 180), ("h181", 100, 181)):
            d = patched(name, lambda b, w=w, h=h: b.__setitem__(slice(rec(0) + 20, rec(0) + 24), struct.pack("<HH", w, h)))
            need(run(d, "pic", 0)[1] == "pic 0", name)
        # garbage in the pack
        d = tmp / "junk"
        shutil.copytree(out, d)
        (d / "figures.pak").write_bytes(b"\x01" * pak_len)
        need(run(d, "pic", 0)[1] == "pic 0", "junk frame")
        need(run(out, "pic", 0)[1] == "pic 1", "intact picture")
    print("ok")


if __name__ == "__main__":
    main()
