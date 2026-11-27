"""Game-free: which file a texture came from (host/asset_tags.c), and where the PS5 tags and counts them:

- a romfs read tags its guest range with the file's romfs path; what is made from tagged bytes (a decompression) is
  tagged with the same file; a newer read over a range replaces it for what is made from then on;
- a range over many pages is found anywhere in it; the table's memory is bounded however many reads come;
- the tally: textures tagged, untagged, and tagged with a file the new zone (and its neighbours) does not want;
- on the PS5 the hooks are in host/nn_fs.c (a read), host/hos_zstd.c (every stream call, also with the native decoder
  off) and the renderer counts its textures on its own thread 5 s after a zone change, into logs/memory.txt.

    python -I -B tests/test_asset_tags.py [--cc gcc]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

RUN_ALL_ARGS = ["--cc", "{cc}"]
ROOT = Path(__file__).resolve().parents[1]


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="asset-tags-") as tmp:
        tmp = Path(tmp)
        exe = tmp / "tags"
        base = [a.cc, "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-g", str(ROOT / "tests" / "asset_tags_test.c"),
                str(ROOT / "host" / "asset_tags.c"), "-I", str(ROOT / "host"), "-lpthread", "-o", str(exe)]
        r = subprocess.run(base[:1] + ["-fsanitize=address,undefined"] + base[1:], capture_output=True, text=True)
        if r.returncode != 0:
            r = subprocess.run(base, capture_output=True, text=True)
        need(r.returncode == 0, "host/asset_tags.c compiles: " + r.stderr[-3000:])
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=120)
        need(r.returncode == 0, r.stdout + r.stderr[-2000:])
    fs = block((ROOT / "host" / "nn_fs.c").read_text(encoding="utf-8"),
               "static uint64_t read_at(Ctx *c, uint64_t id, int64_t off, uint64_t buf, uint64_t size, int *oom) {")
    need("asset_tags_read(buf, done, fh->path);" in fs, "a romfs read is tagged (host/nn_fs.c read_at)")
    zs = block((ROOT / "host" / "hos_zstd.c").read_text(encoding="utf-8"), "int hos_zstd_stream(Ctx *c) {")
    need(zs.index("asset_tags_derived(") < zs.index("if (!mode) return 0;"), "every zstd stream call is tagged, the native decoder on or off")
    tex = (ROOT / "gpu" / "vk" / "vk_texture.cpp").read_text(encoding="utf-8")
    need("asset_tags_tally(" in tex and 'hos_ps5_logfile("memory.txt"' in tex, "the renderer counts its textures into logs/memory.txt")
    win = (ROOT / "host" / "ps5" / "win32_ps5.c").read_text(encoding="utf-8")
    need("rx_vk_tags_wanted" in block(win, "static void mem_write(const char *why, uint64_t room, uint64_t started_ms) {"),
         "the watch thread asks for the count 5 s after a zone change")
    print("PASS: which file a texture came from, and what a zone change leaves unwanted")


if __name__ == "__main__":
    main()
