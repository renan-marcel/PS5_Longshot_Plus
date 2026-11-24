"""Game-free: the PS5's texture size by free memory (gpu/vk/ps5_tex_tier.h, used by gpu/vk/vk_texture.cpp).

- roomy above the reserve + RX_VK_TEX_ROOMY_MB + the hysteresis, not roomy below it minus the hysteresis, as it was between;
- the limit: RX_VK_TEX_ROOMY_DIM while roomy, RX_VK_TEX_MAX_DIM otherwise, and never smaller than RX_VK_TEX_MAX_DIM;
- a texture's tier: none when the limit does not touch it (narrow, or too small to cut, or no roomy size set); low or roomy;
- made again: a low one once roomy, a roomy one once not;
- vk_texture.cpp uses it at a texture's making and in evict_textures, PS5 only; the PS5 / PS5 Slim profile turns it on at 1024.

    python -I -B tests/test_ps5_tex_tier.py [--cxx g++]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

PROGRAM = r'''
#include <cstdio>
#include <cstdlib>
#include "gpu/vk/ps5_tex_tier.h"
using namespace mkwvk::tex_tier;
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL:%d %s\n", __LINE__, #x); std::exit(1); } } while (0)
int main() {
    Line l;
    l.reserve = 1800 * kMB;                  // (the PS5 / PS5 Slim profile's HOS_PS5_TEX_RESERVE_MB)
    CHECK(l.margin == 1536 * kMB && l.hysteresis == 256 * kMB);
    // up only past 1800 + 1536 + 256; down only under 1800 + 1536 - 256; between, as it was
    CHECK(!roomy(false, 3592 * kMB, l));
    CHECK(roomy(false, 3593 * kMB, l));
    CHECK(roomy(true, 3593 * kMB, l));
    CHECK(roomy(true, 3080 * kMB, l));
    CHECK(!roomy(true, 3079 * kMB, l));
    CHECK(!roomy(false, 3300 * kMB, l) && roomy(true, 3300 * kMB, l));
    // the limit
    CHECK(dim_now(512, 1024, true) == 1024 && dim_now(512, 1024, false) == 512);
    CHECK(dim_now(512, 0, true) == 512 && dim_now(1024, 512, true) == 1024);   // (off, or not wider: the low limit)
    // the tiers
    CHECK(tier_of(2048, true, 512, 1024, false) == kLow);
    CHECK(tier_of(2048, true, 512, 1024, true) == kRoomy);
    CHECK(tier_of(512, true, 512, 1024, true) == kNone);      // (no wider than the low limit: never cut)
    CHECK(tier_of(2048, false, 512, 1024, true) == kNone);    // (too small to be cut: RX_VK_TEX_SKIP_MB)
    CHECK(tier_of(2048, true, 512, 0, true) == kNone);        // (no roomy size set)
    CHECK(tier_of(768, true, 512, 1024, false) == kLow);      // (cut to 512 now, whole at 1024 later)
    // made again
    CHECK(remake(kLow, true) && !remake(kLow, false));
    CHECK(remake(kRoomy, false) && !remake(kRoomy, true));
    CHECK(!remake(kNone, true) && !remake(kNone, false));
    std::puts("PASS");
}
'''


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default="g++")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="tex-tier-") as tmp:
        src, exe = Path(tmp) / "t.cpp", Path(tmp) / "t"
        src.write_text(PROGRAM, encoding="utf-8")
        r = subprocess.run([a.cxx, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-I", str(ROOT), str(src), "-o", str(exe)],
                           capture_output=True, text=True)
        need(r.returncode == 0, "it compiles: " + r.stderr[-2000:])
        r = subprocess.run([str(exe)], capture_output=True, text=True)
        need(r.returncode == 0 and "PASS" in r.stdout, "the rule: " + r.stderr[-2000:])
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    making = tex[tex.index("const uint32_t max_dim_low"):tex.index("const uint32_t max_dim_low") + 3000]
    need("#ifdef __PROSPERO__" in making and "tex_tier::dim_now(max_dim_low, ps5_tex_roomy_dim(), roomy_now)" in making
         and "#else\n        const uint32_t max_dim = max_dim_low;" in making, "a texture's making takes the size by memory (PS5 only)")
    need("x.tier = tex_tier::tier_of(" in tex, "a texture keeps the tier it was made at")
    evict = tex[tex.index("// (longshot) the size by free memory (ps5_tex_tier.h): while memory is roomy"):]
    need("tex_tier::remake(tex->tier, roomy)" in evict[:2000], "evict_textures makes them again at the other size")
    need("uint8_t tier = 0;" in (ROOT / "gpu/vk/vk_texture.h").read_text(encoding="utf-8"), "Texture has its tier")
    pipe = (ROOT / "ps5/builder/pipeline.py").read_text(encoding="utf-8")
    base = pipe[pipe.index('"base": {'):pipe.index('"pro": {')]
    need('RX_VK_TEX_ROOMY_DIM' not in base and '"RX_VK_TEX_MAX_DIM": "512"' in base and '"HOS_PS5_MEM_FLOOR_MB": "400"' in base,
         "the PS5 / PS5 Slim profile: 512 always (a base console panicked at 1024), the floor at 400 MiB")
    print("PASS: the texture size follows the free memory, with hysteresis, both ways")


if __name__ == "__main__":
    main()
