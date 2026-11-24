"""Game-free: the PS5's Texture size and Memory margin rows (Graphics tab, gpu/vk/vk_menu.cpp), read from the sources.

- both rows are on the Graphics tab, shown on the PS5 only, off the Quality preset, saved as texture_size= and
  memory_margin= (their names), not restart rows;
- Texture size: Auto keeps RX_VK_TEX_MAX_DIM and the size by free memory, 512 and 1024 fix the limit and turn the size by
  free memory off (vk_texture.cpp ps5_row_low, ps5_tex_roomy_dim);
- Memory margin: Safe keeps 400 MB more for the game and gives the renderer 256 MB less, Performance the other way
  (300 MB less kept, 512 MB more for the renderer); read at each call, so it applies at once; the reserve never under 512 MB.

    python -I -B tests/test_ps5_memory_rows.py
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    need('{TAB_GRAPHICS, "Texture size", &opts.ps5_textures, 0, 2, 1, tx_ps5_textures,' in menu, "the Texture size row")
    need('{TAB_GRAPHICS, "Memory margin", &opts.ps5_memory, 0, 2, 1, tx_ps5_memory,' in menu, "the Memory margin row")
    for name in ("Texture size", "Memory margin"):
        row = menu[menu.index('{TAB_GRAPHICS, "%s"' % name):]
        row = row[:row.index("},") + 2]
        need(row.endswith("nullptr, false, true},"), "%s: not a restart row, off the preset" % name)
    shown = menu[menu.index("bool row_shown(int i) {"):]
    shown = shown[:shown.index("\n}\n")]
    need("#ifdef __PROSPERO__" in shown and "v != &opts.ps5_textures && v != &opts.ps5_memory;" in shown, "PS5 only")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    need("int ps5_textures = 0;" in header and "int ps5_memory = 0;" in header, "Auto and Standard by default")
    tex = (ROOT / "gpu/vk/vk_texture.cpp").read_text(encoding="utf-8")
    need("opts.ps5_textures == 2 && ps5_is_pro() ? std::max(low, 1024u) : low;" in tex, "1024 on a Pro only")
    need("opts.ps5_memory == 2 && ps5_is_pro() ? performance : 0;" in tex, "Performance on a Pro only")
    need("return opts.ps5_textures ? 0 : v;" in tex, "the size by free memory only on Auto")
    need("ps5_row_low(dim_env ?" in tex, "a texture's making takes the row")
    need("ps5_memory_delta(400ll << 20, -(150ll << 20))" in tex and "r > (512ll << 20)" in tex, "the reserve: +400 / -300, >= 512 MB")
    need("line.reserve = ps5_tex_reserve();" in tex, "the size by free memory follows the reserve at once")
    vma = (ROOT / "gpu/vk/vk_vma.cpp").read_text(encoding="utf-8")
    need("ps5_memory_delta(-(256ll << 20), 256ll << 20)" in vma and "ps5_memory_delta(256ll << 20, -(256ll << 20))" in vma,
         "the renderer's cap and reserve follow the row")
    print("PASS: the PS5's Texture size and Memory margin rows")


if __name__ == "__main__":
    main()
