"""PS5: the virtual amiibo's catalogue, from AmiiboAPI (https://github.com/N3evin/AmiiboAPI), into the title folder.

    python -I -u ps5/builder/amiibo.py --app <title folder> --cache <folder for the download>

Writes <title>/amiibo/amiibo.idx (every figure: its 8-byte ID, name, series, character and where its picture is) and
<title>/amiibo/figures.pak (the pictures one after another, each a zstd frame of RGBA8 pixels, fitted inside 144x180).
The renderer reads both (docs/superpowers/specs/2026-11-26-amiibo-design.md). The names and pictures are Nintendo's, so
they are fetched here, onto the player's own PC, and never kept in the repository. A failed download is a warning, not
a failed build: the window then lists no figures.

amiibo.idx, little-endian: b"LSAMIIBO", u32 version (1), u32 count, then count records of 136 bytes:
id[8], u64 pic_offset, u32 pic_size (0: no picture), u16 w, u16 h, name[48], series[32], character[32]
(printable ASCII, NUL-padded, cut to fit). Sorted: "The Legend of Zelda" first, then the series, then the name.
"""
import argparse
import hashlib
import json
import os
import shutil
import struct
import sys
import unicodedata
import urllib.request
import zipfile

API_COMMIT = "6115745c56ff762ce212ced6fbad9ea195d659b3"
API_SHA256 = "5dc0870de75d4f08223f8c467b286f91a66a8500fa3b5cf4473a124b06046f40"
API_URL = "https://codeload.github.com/N3evin/AmiiboAPI/zip/" + API_COMMIT

MAGIC = b"LSAMIIBO"
VERSION = 1
MAX_W, MAX_H = 144, 180
FIRST_SERIES = "The Legend of Zelda"
UNPACKED = ".unpacked"
TIMEOUT = 60   # (seconds a download may wait for the server, each time: a stalled one is a warning, not a hung build)


def say(text):
    print("amiibo: " + text, flush=True)


def ascii_text(text, size):
    """printable ASCII (accents dropped), cut to leave room for the NUL of a field of `size` bytes"""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if " " <= c <= "~")
    return text[:size - 1].encode("ascii").ljust(size, b"\0")


def fetch(cache):
    """The unpacked AmiiboAPI tree in `cache`, downloaded and checked once; None (one warning) when it cannot be had"""
    tree = os.path.join(cache, "AmiiboAPI-" + API_COMMIT)
    if os.path.exists(os.path.join(tree, UNPACKED)):
        return tree
    archive = tree + ".zip"
    part = archive + ".part"
    tmp = tree + ".tmp"
    try:
        if not os.path.exists(archive):
            os.makedirs(cache, exist_ok=True)
            say("downloading " + API_URL)
            h = hashlib.sha256()
            with urllib.request.urlopen(API_URL, timeout=TIMEOUT) as r, open(part, "wb") as f:
                for block in iter(lambda: r.read(1 << 20), b""):
                    h.update(block)
                    f.write(block)
            if h.hexdigest() != API_SHA256:
                raise OSError("its SHA-256 is %s, not the %s named in amiibo.py" % (h.hexdigest(), API_SHA256))
            os.replace(part, archive)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tree, ignore_errors=True)
        os.makedirs(tmp)
        with zipfile.ZipFile(archive) as z:
            z.extractall(tmp)
        inner = os.path.join(tmp, "AmiiboAPI-" + API_COMMIT)
        if not os.path.isdir(inner):
            raise OSError("the archive has no AmiiboAPI-%s folder" % API_COMMIT)
        os.replace(inner, tree)
        shutil.rmtree(tmp, ignore_errors=True)
        open(os.path.join(tree, UNPACKED), "w").close()
        return tree
    except (OSError, zipfile.BadZipFile) as e:
        if os.path.exists(part):
            os.remove(part)
        if isinstance(e, zipfile.BadZipFile) and os.path.exists(archive):
            os.remove(archive)   # (checked but not a zip: the next run downloads again)
        shutil.rmtree(tmp, ignore_errors=True)
        shutil.rmtree(tree, ignore_errors=True)
        say("warning: the amiibo catalogue was not fetched (%s); the window will list no figures" % e)
        return None


def read_figures(api_dir):
    """[(id bytes, name, series, character, picture path)] from database/amiibo.json, series and character the way
    AmiiboAPI's amiibo/amiibo.py derives them: the series is the tail's second byte (hex digits 4-5), the character the
    head's first 4 hex digits"""
    with open(os.path.join(api_dir, "database", "amiibo.json"), encoding="utf-8") as f:
        db = json.load(f)
    series_names = {k.lower(): v for k, v in db.get("amiibo_series", {}).items()}
    character_names = {k.lower(): v for k, v in db.get("characters", {}).items()}
    figures = []
    for key, info in db["amiibos"].items():
        head, tail = key[2:10].lower(), key[10:18].lower()
        series = series_names.get("0x" + tail[4:6], "")
        character = character_names.get("0x" + head[0:4], "")
        picture = os.path.join(api_dir, "images", "icon_%s-%s.png" % (head, tail))
        figures.append((bytes.fromhex(head + tail), info.get("name", ""), series, character, picture))
    figures.sort(key=lambda f: (f[2] != FIRST_SERIES, f[2], f[1]))
    return figures


def picture_pixels(path):
    """(w, h, RGBA8 bytes) fitted inside MAX_W x MAX_H keeping the aspect, or None when there is no readable picture"""
    from PIL import Image
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            scale = min(MAX_W / im.width, MAX_H / im.height, 1.0)
            w = max(1, min(MAX_W, round(im.width * scale)))
            h = max(1, min(MAX_H, round(im.height * scale)))
            if (w, h) != im.size:
                im = im.resize((w, h), Image.LANCZOS)
            return w, h, im.tobytes()
    except (OSError, ValueError):
        return None


def write_catalogue(api_dir, out_dir):
    """amiibo.idx and figures.pak into `out_dir`; the number of figures"""
    import zstandard
    figures = read_figures(api_dir)
    os.makedirs(out_dir, exist_ok=True)
    comp = zstandard.ZstdCompressor(level=19)
    pak = os.path.join(out_dir, "figures.pak")
    idx = os.path.join(out_dir, "amiibo.idx")
    try:
        _write(figures, comp, pak, idx)
    finally:
        for path in (pak + ".part", idx + ".part"):
            if os.path.exists(path):
                os.remove(path)
    return len(figures)


def _write(figures, comp, pak, idx):
    records = []
    offset = 0
    with open(pak + ".part", "wb") as out:
        for fid, name, series, character, picture in figures:
            pic_offset = pic_size = w = h = 0
            got = picture_pixels(picture) if os.path.exists(picture) else None
            if got:
                w, h, rgba = got
                frame = comp.compress(rgba)
                pic_offset, pic_size = offset, len(frame)
                out.write(frame)
                offset += len(frame)
            records.append(fid + struct.pack("<QIHH", pic_offset, pic_size, w, h) + ascii_text(name, 48)
                           + ascii_text(series, 32) + ascii_text(character, 32))
    with open(idx + ".part", "wb") as f:
        f.write(MAGIC + struct.pack("<II", VERSION, len(records)) + b"".join(records))
    os.replace(pak + ".part", pak)
    os.replace(idx + ".part", idx)
    return len(records)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--app", required=True, help="the title folder")
    ap.add_argument("--cache", required=True, help="a folder for the download")
    args = ap.parse_args()
    api = fetch(args.cache)
    if api is None:
        return 0
    out = os.path.join(args.app, "amiibo")
    try:
        n = write_catalogue(api, out)
    except Exception as e:   # (a catalogue that cannot be made, a missing module: a warning, the build goes on)
        for name in ("figures.pak.part", "amiibo.idx.part"):
            if os.path.exists(os.path.join(out, name)):
                os.remove(os.path.join(out, name))
        if os.path.isdir(out) and not os.listdir(out):
            os.rmdir(out)
        say("warning: the amiibo catalogue was not written (%s: %s); the window will list no figures" % (type(e).__name__, e))
        return 0
    say("%d figures, figures.pak %d bytes" % (n, os.path.getsize(os.path.join(out, "figures.pak"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
