"""Game-free: the Insert menu's Amiibo tab (gpu/vk/vk_menu.cpp, the virtual amiibo reader of host/amiibo_core.c).

Read from the source: the tab between Controls and Debug (TAB_AMIIBO 4, TAB_DEBUG 5, TAB_COUNT 6, the titles in order),
its rows with their defaults (vk_menu.h), save() writing the figure by its ID (amiibo_figure_id=, not the Figure row's place)
and menu_init reading it back, the card's status lines.

Then the tab's catalogue and its logic, cut out of vk_menu.cpp (srccut) with the Options and Row of the source and the
amiibo rows of the table, compiled against a stand-in host and run on a small catalogue written here (amiibo.idx, no
pictures): the start sends the switches (amiibo_config) and the saved figure found by its ID (amiibo_select); a change of
Amiibo emulation, Random tag ID or Touch when the game asks calls amiibo_config, a change of Figure or Surprise me calls
amiibo_select and saves the new ID; another Series puts Figure on its first figure; Touch / Remove touches unless the
figure is on the reader or read; a host from before (no amiibo calls) is left alone.

    python -I -B tests/test_amiibo_menu.py [--cxx g++] [--source ROOT]
"""
import argparse
import os
import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import between, block  # noqa: E402

RUN_ALL_ARGS = ["--cxx", "{cxx}"]
ROOT = Path(__file__).resolve().parents[1]

ROWS = [("Amiibo emulation", "&opts.amiibo_on"), ("Series", "&opts.amiibo_series"), ("Figure", "&opts.amiibo_figure"),
        ("Surprise me", "nullptr"), ("Random tag ID", "&opts.amiibo_random"),
        ("Touch when the game asks", "&opts.amiibo_auto"), ("Touch / Remove", "nullptr")]
DEFAULTS = {"amiibo_on": 1, "amiibo_series": 0, "amiibo_figure": -1, "amiibo_random": 1, "amiibo_auto": 1}
STATUS = {"-1": "Not looking for amiibo", "0": "Not looking for amiibo", "1": "The game is looking: touch to use",
          "2": "On the reader", "3": "Removed", "4": "Read"}

# (the catalogue: id, name, series; file order. Series as the menu lists them: All, The Legend of Zelda, then by name)
FIGURES = [("01000000037c0002", "Link (Ocarina of Time)", "The Legend of Zelda"),
           ("0000000000340102", "Mario", "Super Mario Bros."),
           ("01010000034d0002", "Zelda", "The Legend of Zelda"),
           ("0181000100440502", "Isabelle", "Animal Crossing")]


def fail(why):
    raise SystemExit("FAIL: " + why)


def need(ok, why):
    if not ok:
        fail(why)


def catalogue(folder):
    folder.mkdir(parents=True, exist_ok=True)
    data = b"LSAMIIBO" + struct.pack("<II", 1, len(FIGURES))
    for hexid, name, series in FIGURES:
        rec = bytes.fromhex(hexid) + struct.pack("<QIHH", 0, 0, 0, 0)
        rec += name.encode().ljust(48, b"\0") + series.encode().ljust(32, b"\0") + name.encode()[:31].ljust(32, b"\0")
        assert len(rec) == 136
        data += rec
    (folder / "amiibo.idx").write_bytes(data)
    (folder / "figures.pak").write_bytes(b"")


DRIVER = r'''
#include <algorithm>
#include <chrono>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <random>
#include <string>
#include <vector>
#include "amiibo_catalogue.h"
#define CHECK(x) do { if (!(x)) { std::fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); std::exit(1); } } while (0)
namespace mkwvk {
/* OPTIONS */
Options opts;
/* TABS */
/* ROW */
std::string folder;
std::string game_folder_path() { return folder; }
const char* tx_onoff(int v) { return v ? "On" : "Off"; }
struct Host {
    int (*amiibo_status)(void);
    void (*amiibo_select)(const uint8_t* id, const char* name);
    void (*amiibo_touch)(int on);
    void (*amiibo_config)(int emulation, int random_uid, int auto_touch);
};
int status = -1, configs = 0, selects = 0, touches = 0, saves = 0, cfg[3], touched = -1;
std::string selected_id = "?", selected_name;
int st_status() { return status; }
void st_select(const uint8_t* id, const char* name) {
    selects++;
    selected_id = id ? amiibo::id_hex(id) : "";
    selected_name = name ? name : "";
}
void st_touch(int on) { touches++, touched = on; }
void st_config(int a, int b, int c) { configs++, cfg[0] = a, cfg[1] = b, cfg[2] = c; }
Host full{st_status, st_select, st_touch, st_config}, old{};
const Host* host = &full;
void save() { saves++; }
/* CATALOGUE */
Row rows[] = {
/* ROWS */
};
/* LOGIC */
Row& row(const char* name) {
    for (Row& r : rows) if (!strcmp(r.name, name)) return r;
    CHECK(!"no such row");
    return rows[0];
}
// (menu_init's order: the catalogue and the rows' ranges before the file, the file's lines, the figure found, the host told)
void start(int series, const char* id) {
    opts = Options{};
    amiibo_sent_config[0] = amiibo_sent_config[1] = amiibo_sent_config[2] = -1;
    amiibo_sent_id = "-";
    amiibo_load();
    amiibo_rows_sync();
    opts.amiibo_series = series;
    snprintf(opts.amiibo_id, sizeof opts.amiibo_id, "%s", id);
    amiibo_restore();
    amiibo_tick();
}
}  // namespace mkwvk
using namespace mkwvk;
int main(int, char** argv) {
    folder = argv[1];
    // the defaults, and the catalogue's series: All, The Legend of Zelda first, then by name
    CHECK(opts.amiibo_on == 1 && opts.amiibo_series == 0 && opts.amiibo_figure == -1 && opts.amiibo_random == 1 && opts.amiibo_auto == 1);
    CHECK(!opts.amiibo_id[0]);
    amiibo_load();
    CHECK(amiibo_figs.size() == 4);
    CHECK(!strcmp(tx_amiibo_series(0), "All") && !strcmp(tx_amiibo_series(1), "The Legend of Zelda"));
    CHECK(!strcmp(tx_amiibo_series(2), "Animal Crossing") && !strcmp(tx_amiibo_series(3), "Super Mario Bros."));
    CHECK(!strcmp(tx_amiibo_figure(-1), "None"));

    // the start: the switches and the saved figure (Zelda, in the saved series The Legend of Zelda) sent, nothing saved
    start(1, "01010000034D0002");
    CHECK(configs == 1 && cfg[0] == 1 && cfg[1] == 1 && cfg[2] == 1);
    CHECK(selects == 1 && selected_id == "01010000034d0002" && selected_name == "Zelda");
    CHECK(opts.amiibo_series == 1 && opts.amiibo_figure == 1 && saves == 0);
    CHECK(row("Series").lo == 0 && row("Series").hi == 3 && row("Figure").lo == 0 && row("Figure").hi == 1);
    CHECK(!strcmp(tx_amiibo_figure(opts.amiibo_figure), "Zelda"));
    amiibo_tick();
    CHECK(configs == 1 && selects == 1 && saves == 0);   // (nothing changed: nothing sent)

    // a change of each switch: amiibo_config
    opts.amiibo_random = 0, amiibo_tick();
    CHECK(configs == 2 && cfg[0] == 1 && cfg[1] == 0 && cfg[2] == 1);
    opts.amiibo_on = 0, amiibo_tick();
    CHECK(configs == 3 && cfg[0] == 0);
    opts.amiibo_auto = 0, amiibo_tick();
    CHECK(configs == 4 && cfg[2] == 0 && selects == 1);

    // a change of Figure: amiibo_select, and the ID saved
    opts.amiibo_figure = 0, amiibo_tick();
    CHECK(selects == 2 && selected_id == "01000000037c0002" && saves == 1 && !strcmp(opts.amiibo_id, "01000000037c0002"));
    // another Series: Figure on its first figure
    opts.amiibo_series = 3, amiibo_tick();
    CHECK(opts.amiibo_figure == 0 && selects == 3 && selected_name == "Mario" && saves == 2);
    CHECK(row("Figure").lo == 0 && row("Figure").hi == 0);

    // Surprise me: a figure of the series (All), another than the one shown each time, sent and saved
    opts.amiibo_series = 0, amiibo_tick();
    for (int i = 0; i < 40; i++) {
        const int was = opts.amiibo_figure, sel = selects, sv = saves;
        CHECK(amiibo_press(row("Surprise me")));
        CHECK(opts.amiibo_figure >= 0 && opts.amiibo_figure < 4 && opts.amiibo_figure != was);
        CHECK(selects == sel + 1 && saves == sv + 1);
        CHECK(selected_id == amiibo::id_hex(amiibo_figs[opts.amiibo_figure].id));
    }

    // Touch / Remove: off the reader when on it or read, else on
    const int states[] = {-1, 0, 1, 2, 3, 4, 5, 6}, want[] = {1, 1, 1, 0, 1, 0, 1, 1};
    for (int i = 0; i < 8; i++) {
        status = states[i];
        const int n = touches;
        CHECK(amiibo_press(row("Touch / Remove")));
        CHECK(touches == n + 1 && touched == want[i]);
    }
    CHECK(!amiibo_press(row("Figure")));   // (a row with a value: not an action)

    // a saved ID the catalogue does not have: none chosen, the ID kept for a catalogue that has it
    start(0, "ffffffffffffffff");
    CHECK(opts.amiibo_figure == -1 && !strcmp(opts.amiibo_id, "ffffffffffffffff") && selected_id.empty());
    // a saved series the figure is not in: under All
    start(3, "01000000037c0002");
    CHECK(opts.amiibo_series == 0 && opts.amiibo_figure == 0 && selected_id == "01000000037c0002");

    // a host from before (none of the four calls): nothing called, nothing breaks
    host = &old;
    const int c0 = configs, s0 = selects, t0 = touches;
    opts.amiibo_on = 1, opts.amiibo_figure = 2, amiibo_tick();
    CHECK(amiibo_press(row("Touch / Remove")) && amiibo_press(row("Surprise me")));
    CHECK(configs == c0 && selects == s0 && touches == t0);
    std::puts("ok");
    return 0;
}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cxx", default="g++")
    parser.add_argument("--source", type=Path, default=ROOT)
    args = parser.parse_args()
    src = args.source.resolve()
    menu = (src / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    header = (src / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")

    # the tab strip
    tabs = between(menu, "enum MenuTab {", "};")
    for name, value in (("TAB_CONTROLS", 3), ("TAB_AMIIBO", 4), ("TAB_DEBUG", 5), ("TAB_COUNT", 6)):
        need(re.search(r"\b%s = %d\b" % (name, value), tabs), "MenuTab: %s is not %d" % (name, value))
    titles = re.search(r"tab_titles\[TAB_COUNT\] = \{([^}]*)\}", menu)
    need(titles and re.findall(r'"([^"]*)"', titles.group(1)) == ["Graphics", "Audio", "Gameplay", "Controls", "Amiibo", "Debug"],
         "the tab titles are not Graphics, Audio, Gameplay, Controls, Amiibo, Debug")
    bridge = re.search(r"static const char\* const tabs\[\] = \{([^}]*)\}", menu)
    need(bridge and re.findall(r'"([^"]*)"', bridge.group(1))[4:6] == ["amiibo", "debug"], "the control bridge's tab names")

    # the rows, in order, and their defaults
    table = between(menu, "// (longshot) Amiibo: the host's virtual amiibo reader", "    // Debug: the tools' switch")
    found = re.findall(r'\{TAB_AMIIBO, "([^"]+)", ([^,]+),', table)
    need(found == ROWS, "the Amiibo tab's rows: %r" % (found,))
    need(len(re.findall(r"\{TAB_AMIIBO,", menu)) == len(ROWS), "Amiibo rows outside the tab's block")
    for member, value in DEFAULTS.items():
        need(re.search(r"\bint %s = %d;" % (member, value), header), "vk_menu.h: %s is not %d by default" % (member, value))
    need("char amiibo_id[17]" in header, "vk_menu.h: no amiibo_id")

    # the figure saved by its ID, not by its place; read back by its ID
    save = block(menu, "void save() {")
    need('fprintf(f, "amiibo_figure_id=%s\\n", opts.amiibo_id)' in save, "save() does not write amiibo_figure_id=")
    need('key == "amiibo_figure_id"' in save, "save() keeps an old amiibo_figure_id= line as another's")
    need("r.value != &opts.amiibo_figure" in save, "save() writes the Figure row's place")
    init = block(menu, "void menu_init() {")
    need('!strcmp(line, "amiibo_figure_id")' in init, "menu_init does not read amiibo_figure_id=")
    need("r.value == &opts.amiibo_figure" in init, "menu_init reads a figure= place")
    need(init.find("amiibo_rows_sync();") < init.find('if (FILE* f = fopen(ini_path().c_str(), "r"))'),
         "the Series row's range is not set before the file is read")
    need(re.search(r"amiibo_restore\(\);\s*(//[^\n]*)?\n\s*amiibo_tick\(\);\s*\n\}$", init), "menu_init does not end by restoring and telling the host")
    logic = between(menu, "// ---- (longshot) the Amiibo tab: what its rows say", "// ---- (longshot) the rows that are text fields")
    need("amiibo::find(amiibo_figs, opts.amiibo_id)" in logic, "the saved figure is not found by its ID")
    tick = block(menu, "void menu_tick() {")
    need("amiibo_tick();" in tick and "press[7] && amiibo_press(r)" in tick, "menu_tick does not tick the tab or press its actions")
    need(tick.find("press[7] && amiibo_press(r)") < tick.find("press[7] && !r.value && can_bind()"),
         "Surprise me and Touch / Remove would open the Controls page")

    # the card
    card = between(menu, "// ---- (longshot) the Amiibo tab's figure card", "void draw_options(ui::Ctx& c) {")
    for st, line in STATUS.items():
        need('"%s"' % line in card, "the card has no status line %r" % line)
    need('"No amiibo catalogue: build again with Download amiibo ticked."' in card, "the card's no-catalogue line")
    need("ui::picture_make(" in card and "ui::picture_drop(" in card, "the picture's texture is not made and let go")
    need("ui::kAccent" in card and "ui::kDim" in card, "the card's glow or silhouette")
    draw = block(menu, "void draw_options(ui::Ctx& c) {")
    need("cur_tab == TAB_AMIIBO && !narrow ? amiibo_card(" in draw, "draw_options does not draw the card on the Amiibo tab")
    imgui = (src / "gpu/vk/vk_imgui.cpp").read_text(encoding="utf-8")
    need("ImGui::RegisterUserTexture(tex)" in imgui and "ImGui::UnregisterUserTexture(tex)" in imgui
         and "tex->WantDestroyNextFrame = true" in imgui, "vk_imgui.cpp: the pictures' lifecycle")

    # the logic, compiled and run
    code = DRIVER
    code = code.replace("/* OPTIONS */", between(header, "struct Options {", "\nextern Options opts;"))
    code = code.replace("/* TABS */", between(menu, "enum MenuTab {", "\n};") + "\n};")
    code = code.replace("/* ROW */", between(menu, "struct Row {", "\n};") + "\n};")
    code = code.replace("/* CATALOGUE */", between(menu, "// ---- (longshot) the Amiibo tab's catalogue", "const char* const kFpsDevLineHelp"))
    code = code.replace("/* ROWS */", table)
    code = code.replace("/* LOGIC */", logic)
    with tempfile.TemporaryDirectory(prefix="amiibo-menu-") as tmp:
        tmp = Path(tmp)
        catalogue(tmp / "game" / "amiibo")
        cpp, exe = tmp / "amiibo_menu.cpp", tmp / ("amiibo_menu.exe" if os.name == "nt" else "amiibo_menu")
        cpp.write_text(code, encoding="utf-8")
        cmd = [args.cxx, "-std=c++20", "-Wall", "-Wextra", "-Werror", "-Wno-unused-function", "-D_CRT_SECURE_NO_WARNINGS",
               "-I", str(src / "gpu/vk"), "-I", str(src / "third_party/zstd/lib"), str(cpp), "-o", str(exe)]
        built = subprocess.run(cmd, capture_output=True, text=True)
        if built.returncode:
            fail("the Amiibo tab's logic does not compile:\n" + built.stdout + built.stderr)
        run = subprocess.run([str(exe), str(tmp / "game") + os.sep], capture_output=True, text=True)
        need(run.returncode == 0 and run.stdout.strip() == "ok", "the Amiibo tab's logic:\n" + run.stdout + run.stderr)
    print("ok")


if __name__ == "__main__":
    main()
