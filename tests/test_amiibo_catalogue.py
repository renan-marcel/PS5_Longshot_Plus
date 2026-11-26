"""Game-free: the amiibo catalogue writer (ps5/builder/amiibo.py): a fake AmiiboAPI tree with pictures the test draws,
and the index and pack it writes (format: the module's docstring); fetch's failures leave nothing behind.

    python -I -B tests/test_amiibo_catalogue.py
"""
from pathlib import Path
import hashlib
import json
import os
import struct
import sys
import tempfile
import zipfile

RUN_ALL_MODULES = ["PIL", "zstandard"]
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ps5" / "builder"))
import amiibo  # noqa: E402

ZELDA = "0x01000000042e0102"      # (series is the tail's second byte: 0x01)
MARIO = "0x0000000000020202"      # (series 0x02; the name has an accent)
NO_PICTURE = "0x0001000000000002"  # (series 0x00)
RED, GREEN = (200, 30, 40, 255), (10, 200, 90, 255)


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def fake_tree(tree):
    from PIL import Image
    (tree / "database").mkdir(parents=True)
    (tree / "images").mkdir()
    db = {
        "amiibos": {
            MARIO: {"name": "Pokémon Trainer", "release": {}},
            ZELDA: {"name": "Link", "release": {}},
            NO_PICTURE: {"name": "x" * 60, "release": {}},
        },
        "amiibo_series": {"0x01": "The Legend of Zelda", "0x02": "Super Mario Bros.", "0x00": "Unknown"},
        "characters": {"0x0000": "Mario", "0x0100": "Link"},
    }
    (tree / "database" / "amiibo.json").write_text(json.dumps(db), encoding="utf-8")
    Image.new("RGBA", (288, 359), RED).save(tree / "images" / "icon_01000000-042e0102.png")
    Image.new("RGBA", (288, 359), GREEN).save(tree / "images" / "icon_00000000-00020202.png")


def main():
    import zstandard
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        tree, out = tmp / "api", tmp / "out"
        fake_tree(tree)
        n = amiibo.write_catalogue(str(tree), str(out))
        need(n == 3, "count %d, not 3" % n)
        idx = (out / "amiibo.idx").read_bytes()
        need(idx[:8] == b"LSAMIIBO" and struct.unpack("<II", idx[8:16]) == (1, 3), "header")
        need(len(idx) == 16 + 3 * 136, "size %d" % len(idx))
        recs = []
        for i in range(3):
            r = idx[16 + i * 136:16 + (i + 1) * 136]
            off, size, w, h = struct.unpack("<QIHH", r[8:24])
            recs.append(dict(id=r[:8], off=off, size=size, w=w, h=h, raw_name=r[24:72],
                             name=r[24:72].split(b"\0")[0].decode("ascii"),
                             series=r[72:104].split(b"\0")[0].decode("ascii"),
                             character=r[104:136].split(b"\0")[0].decode("ascii")))
        first = recs[0]
        need(first["id"] == bytes.fromhex(ZELDA[2:]) and first["name"] == "Link", "Zelda first: %r" % first)
        need(first["series"] == "The Legend of Zelda" and first["character"] == "Link", "Zelda series and character")
        mario = [r for r in recs if r["id"] == bytes.fromhex(MARIO[2:])][0]
        need(mario["name"] == "Pokemon Trainer", "ASCII name: %r" % mario["name"])
        need(mario["series"] == "Super Mario Bros." and mario["character"] == "Mario", "Mario series and character")
        pak = (out / "figures.pak").read_bytes()
        for r, colour in ((first, RED), (mario, GREEN)):
            need(0 < r["w"] <= 144 and 0 < r["h"] <= 180 and (r["w"] == 144 or r["h"] == 180),
                 "fit %dx%d" % (r["w"], r["h"]))
            px = zstandard.ZstdDecompressor().decompress(pak[r["off"]:r["off"] + r["size"]])
            need(len(px) == r["w"] * r["h"] * 4, "frame size")
            c = ((r["h"] // 2) * r["w"] + r["w"] // 2) * 4
            need(tuple(px[c:c + 4]) == colour, "centre pixel %r" % (tuple(px[c:c + 4]),))
        none = [r for r in recs if r["size"] == 0]
        need(len(none) == 1 and none[0]["w"] == 0 and none[0]["h"] == 0, "no-picture record")
        need(none[0]["name"] == "x" * 47 and none[0]["raw_name"][47] == 0, "a long name is cut to 47 + NUL")

        # fetch: an unreachable URL -> None, nothing written
        cache = tmp / "cache"
        amiibo.API_URL = "http://127.0.0.1:9/x.zip"
        need(amiibo.fetch(str(cache)) is None, "fetch of an unreachable URL")
        need(not cache.exists() or not any(cache.iterdir()), "fetch left files")

        # a wrong SHA-256 -> None, nothing left
        z = tmp / "fake.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("AmiiboAPI-%s/database/amiibo.json" % amiibo.API_COMMIT, "{}")
        amiibo.API_URL = z.as_uri()
        need(amiibo.fetch(str(cache)) is None, "fetch with a wrong SHA-256")
        need(not any(cache.iterdir()), "a wrong SHA-256 left files")

        # the right one -> the tree, unpacked once
        amiibo.API_SHA256 = hashlib.sha256(z.read_bytes()).hexdigest()
        t = amiibo.fetch(str(cache))
        need(t and os.path.isfile(os.path.join(t, "database", "amiibo.json")), "fetch of the fake archive")
        amiibo.API_URL = "http://127.0.0.1:9/x.zip"
        need(amiibo.fetch(str(cache)) == t, "a second fetch uses the unpacked tree")
    print("ok")


main()
