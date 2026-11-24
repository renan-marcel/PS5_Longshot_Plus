"""Game-free: the Debug tab's GPU freeze shader (gpu/vk/gpu_skip.h, gpu/vk/vk_menu.cpp) and the shader probe
(gpu/vk/vk_draw.cpp probe_dispatch, gpu/vk/zone_boost.h, host/ps5/win32_ps5.c).

- gpu_skip.h compiled and run: the skipped list (add, contains, full, clear), its ini text both ways (malformed keys passed
  over), and the program of the last GPU freeze read from a crash trace: a real one from a PS5 that froze twice on the compute
  program 53fcaee4dc45c6ee in a cutscene (its last freeze, the restarts after it), one with no freeze, one whose freeze is its
  last line, one with an earlier run's freeze and restarts after it.
- the builder's list (RX_VK_GPU_SKIP, from ps5/builder/known_gpu_hangs.txt): left out from the start, never in the ini
  text, marked (build) in the row's line, drawn again by the row's Enter for the run.
- zone_boost.h's probe line: written and taken back whole.
- The sources: draws and dispatches of a skipped program left out before they are recorded, the probe after every other
  check that leaves a dispatch out, the two Debug rows and their ini line, the watchdog writing the probe's last line when
  the GPU stops presenting.

    python -I -B tests/test_gpu_skip.py [--cxx g++]
"""
import argparse
import os
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cxx", "{cxx}"]

ROOT = Path(__file__).resolve().parents[1]

TRACE = """\
[PS5-TRACE] BOOT_WATCHDOG_ACTIVE | present=0 | free_mem=0 MiB | zone_boost=0 | last_gfx=0000000000000000 (s0=0000000000000000, s1=0000000000000000) | last_cs=0000000000000000 | is_compute=0 | prog_key=0000000000000000
[PS5-TRACE] GPU_FREEZE_2S | present=4761 | free_mem=2030 MiB | zone_boost=1 | last_gfx=23677364611b9855 (s0=862d6c746cfc0f91, s1=4e91c712aa06361c) | last_cs=6214a97bec4cc0bf | is_compute=0 | prog_key=23677364611b9855
[PS5-TRACE] BOOT_WATCHDOG_ACTIVE | present=0 | free_mem=0 MiB | zone_boost=0 | last_gfx=0000000000000000 (s0=0000000000000000, s1=0000000000000000) | last_cs=0000000000000000 | is_compute=0 | prog_key=0000000000000000
[PS5-TRACE] GPU_FREEZE_2S | present=79976 | free_mem=1887 MiB | zone_boost=1 | last_gfx=37914ae65792d0c8 (s0=f2f1fee734612e86, s1=8a0f095aef5b62f2) | last_cs=53fcaee4dc45c6ee | is_compute=1 | prog_key=53fcaee4dc45c6ee
[PS5-TRACE] BOOT_WATCHDOG_ACTIVE | present=0 | free_mem=0 MiB | zone_boost=0 | last_gfx=0000000000000000 (s0=0000000000000000, s1=0000000000000000) | last_cs=0000000000000000 | is_compute=0 | prog_key=0000000000000000
[PS5-TRACE] GPU_FREEZE_2S | present=6674 | free_mem=2594 MiB | zone_boost=1 | last_gfx=37914ae65792d0c8 (s0=f2f1fee734612e86, s1=8a0f095aef5b62f2) | last_cs=53fcaee4dc45c6ee | is_compute=1 | prog_key=53fcaee4dc45c6ee
[PS5-TRACE] BOOT_WATCHDOG_ACTIVE | present=0 | free_mem=0 MiB | zone_boost=0 | last_gfx=0000000000000000 (s0=0000000000000000, s1=0000000000000000) | last_cs=0000000000000000 | is_compute=0 | prog_key=0000000000000000
"""
BOOT = TRACE.splitlines()[0]

PROGRAM = r'''
#include "zone_boost.h"
#include "gpu_skip.h"
#include <cassert>
#include <cstdio>
#include <string>

static std::string text_of(const char* path) {
    std::string t;
    if (FILE* f = fopen(path, "rb")) {
        char b[4096];
        for (size_t n; (n = fread(b, 1, sizeof b, f)) > 0;) t.append(b, n);
        fclose(f);
    }
    return t;
}

int main(int argc, char** argv) {
    // the builder's list, from the environment (the check runs with RX_VK_GPU_SKIP set: main's caller)
    assert(gpu_skip::from_build().size() == 2);   // (a short key and a repeat passed over)
    assert(gpu_skip::contains(0x1111111111111111ull) && gpu_skip::contains(0x2222222222222222ull));
    assert(gpu_skip::from_build_has(0x1111111111111111ull) && gpu_skip::total() == 2);
    assert(gpu_skip::to_text().empty());   // (not the player's: never written to the ini)
    assert(gpu_skip::describe() == "1111111111111111 (build), 2222222222222222 (build)");
    // the player's list
    assert(!gpu_skip::contains(0x53fcaee4dc45c6eeull));
    assert(gpu_skip::add(0x53fcaee4dc45c6eeull));
    assert(!gpu_skip::add(0x53fcaee4dc45c6eeull));   // (once)
    assert(!gpu_skip::add(0));
    assert(gpu_skip::contains(0x53fcaee4dc45c6eeull) && !gpu_skip::contains(0x53fcaee4dc45c6efull));
    assert(gpu_skip::add(0x0123456789abcdefull));
    assert(gpu_skip::to_text() == "53fcaee4dc45c6ee,0123456789abcdef");
    assert(gpu_skip::total() == 4);
    assert(gpu_skip::describe() ==
           "53fcaee4dc45c6ee, 0123456789abcdef, 1111111111111111 (build), 2222222222222222 (build)");
    assert(gpu_skip::add(0x1111111111111111ull) && gpu_skip::total() == 4);   // (a builder's key the player adds: counted once)
    assert(gpu_skip::describe() == "53fcaee4dc45c6ee, 0123456789abcdef, 1111111111111111, 2222222222222222 (build)");
    gpu_skip::clear();
    assert(gpu_skip::count.load() == 0 && !gpu_skip::contains(0x53fcaee4dc45c6eeull) && gpu_skip::to_text().empty());
    assert(gpu_skip::contains(0x1111111111111111ull) && gpu_skip::total() == 2);   // (the player's list only)
    for (uint64_t k = 1; k <= gpu_skip::kMax; k++) assert(gpu_skip::add(k));
    assert(!gpu_skip::add(1000));   // (full)
    // the ini's text: keys of 16 hex digits; a short one, a long one and words passed over
    gpu_skip::from_text("53FCAEE4DC45C6EE, abc,0123456789abcdef0 junk 23677364611b9855\n");
    assert(gpu_skip::to_text() == "53fcaee4dc45c6ee,23677364611b9855");
    gpu_skip::from_text("");
    assert(gpu_skip::count.load() == 0);
    // the row's Enter: every one drawn again, the builder's for this run
    gpu_skip::add(0x53fcaee4dc45c6eeull);
    gpu_skip::restore_all();
    assert(!gpu_skip::contains(0x53fcaee4dc45c6eeull) && !gpu_skip::contains(0x1111111111111111ull));
    assert(gpu_skip::total() == 0 && gpu_skip::describe().empty() && gpu_skip::to_text().empty());
    // the last freeze: argv[1] the real trace, [2] none, [3] a freeze as the last line, [4] restarts after the freeze
    gpu_skip::Freeze f = gpu_skip::last_freeze(text_of(argv[1]));
    assert(f.found && f.key == 0x53fcaee4dc45c6eeull && f.compute && f.present == 6674);
    f = gpu_skip::last_freeze(text_of(argv[2]));
    assert(!f.found);
    f = gpu_skip::last_freeze(text_of(argv[3]));
    assert(f.found && f.key == 0x53fcaee4dc45c6eeull && f.compute && f.present == 6674);
    f = gpu_skip::last_freeze(text_of(argv[4]));
    assert(f.found && f.key == 0x23677364611b9855ull && !f.compute && f.present == 4761);
    // the probe's line
    char out[ZONE_PROBE_LINE];
    assert(!zone_probe_take(out, sizeof out));   // (nothing yet)
    zone_probe_publish("dispatch 53fcaee4dc45c6ee present=1 grid=1,1,1 c3@1000/1024: 00000004");
    assert(zone_probe_take(out, sizeof out) && std::string(out) == "dispatch 53fcaee4dc45c6ee present=1 grid=1,1,1 c3@1000/1024: 00000004");
    const std::string longer(ZONE_PROBE_LINE + 100, 'x');
    zone_probe_publish(longer.c_str());
    assert(zone_probe_take(out, sizeof out) && std::string(out).size() == ZONE_PROBE_LINE - 1);   // (cut to the room)
    char small[8];
    assert(zone_probe_take(small, sizeof small) && std::string(small) == "xxxxxxx");
    puts("gpu_skip: the list, its ini text, the last freeze and the probe's line");
    return 0;
}
'''


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def body(text, head):
    at = text.index(head)
    depth, i = 0, text.index("{", at)
    while True:
        depth += {"{": 1, "}": -1}.get(text[i], 0)
        if depth == 0:
            return text[at:i + 1]
        i += 1


def sources():
    draw = (ROOT / "gpu/vk/vk_draw.cpp").read_text(encoding="utf-8")
    menu = (ROOT / "gpu/vk/vk_menu.cpp").read_text(encoding="utf-8")
    ps5 = (ROOT / "host/ps5/win32_ps5.c").read_text(encoding="utf-8")
    # draws: left out with the other skips, before anything is recorded
    need('if (skip_live(cp->key)) return;   // (EvilOOT, RX_VK_SKIP_FILE)\n    if (gpu_skip::contains(cp->key)) {' in draw,
         "a skipped program's draws are not left out beside RX_VK_SKIP_FILE's")
    dispatch = body(draw, "void dispatch(VkCommandBuffer cmd, NvnState& s, uint32_t x, uint32_t y, uint32_t z, uint64_t indirect)")
    need("gpu_skip::contains(cp->key)" in dispatch, "a skipped program's dispatches are not left out")
    at_skip = dispatch.index("gpu_skip::contains(cp->key)")
    at_probe = dispatch.index("probe_dispatch(s, *cp")
    need(at_skip < dispatch.index('getenv("RX_VK_SKIP_PROG")') < at_probe and
         dispatch.index('getenv("RX_VK_SKIP_CODE")') < at_probe, "the probe must come after every check that leaves a dispatch out")
    need(at_probe < dispatch.index("ensure_layout(p)"), "the probe must come before the dispatch is recorded")
    probe = body(draw, "void probe_dispatch(")
    need("zone_probe_publish(line)" in probe and "hos_ps5_trace_note(line)" in probe and "constant_buffer_used_sizes" in probe,
         "the probe keeps its line for the watchdog, notes its first ones and logs the banks the program reads")
    wanted = body(draw, "bool probe_wanted(")
    need('getenv("RX_VK_PROBE_PROG")' in wanted and "gpu_skip::last_freeze" in wanted, "the probe's programs: the switch and the last freeze's")
    # (the Debug tab's Shader probe row: off by default, and off nothing is watched, the switch's programs neither, before the
    # list is read)
    need(wanted.index("if (!opts.shader_probe) return false;") < wanted.index("static const std::vector<uint64_t> want"),
         "the probe does not stop first when the Shader probe row is off")
    header = (ROOT / "gpu/vk/vk_menu.h").read_text(encoding="utf-8")
    need("int shader_probe = 0;" in header, "the Shader probe row is not off by default")
    need('{TAB_DEBUG, "Shader probe", &opts.shader_probe, 0, 1, 1, tx_onoff,' in menu, "the Debug tab has no Shader probe row")
    # the menu
    for name in ("GPU freeze shader", "Skipped shaders"):
        need('{TAB_DEBUG, "%s", nullptr, 0, 0, 0, nullptr,' % name in menu, "the Debug tab has no %s row" % name)
    need('mine |= key == "gpu_skip";' in menu and 'fprintf(f, "gpu_skip=%s\\n", gpu_skip::to_text().c_str());' in menu and
         'if (!strcmp(line, "gpu_skip")) gpu_skip::from_text(eq + 1);' in menu, "gpu_skip= is not kept, written and read")
    press = menu[menu.index("else if (press[7] && is_freeze_row(r))"):]
    press = press[:press.index("else if (press[7] && &r == &rows[kBugReportRow])")]
    need("!gpu_skip::contains(key) && gpu_skip::add(key)" in press and "gpu_skip::restore_all()" in press and
         press.count("save()") == 2, "Enter on the rows does not skip, restore (the builder's too) and save")
    need("gpu_skip::total()" in body(menu, "std::string skipped_cell(") and "gpu_skip::describe()" in body(menu, "const char* freeze_hint("),
         "the Skipped shaders row does not count and list the builder's too")
    # the watchdog
    freeze = ps5[ps5.index('ps5_write_crash_trace("GPU_FREEZE_2S", room >> 20);'):]
    freeze = freeze[:freeze.index("zone_boost_update_mem(")]
    need("zone_probe_take(" in freeze and "hos_ps5_trace_note(probe)" in freeze, "a freeze does not write the probe's last line")
    need("const char *hos_ps5_trace_path(void)" in ps5 and "void hos_ps5_trace_note(const char *line)" in ps5,
         "the host gives no trace path or note")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cxx", default="g++")
    a = ap.parse_args()
    sources()
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "t.cpp").write_text(PROGRAM, encoding="utf-8")
        (tmp / "real.txt").write_text(TRACE, encoding="utf-8")
        (tmp / "none.txt").write_text(BOOT + "\n" + BOOT + "\n", encoding="utf-8")
        lines = TRACE.splitlines()
        (tmp / "last.txt").write_text("\n".join(lines[:6]) + "\n", encoding="utf-8")   # (no start after the freeze)
        (tmp / "after.txt").write_text("\n".join(lines[:2] + [BOOT, BOOT, BOOT]) + "\n", encoding="utf-8")
        exe = tmp / "t"
        cc = subprocess.run([a.cxx, "-std=c++17", "-O1", "-Wall", "-Werror", "-I",
                             str(ROOT / "gpu/vk"), str(tmp / "t.cpp"), "-o", str(exe), "-lpthread"], capture_output=True, text=True)
        need(cc.returncode == 0, "gpu_skip.h compiles: " + cc.stderr[-2000:])
        env = dict(os.environ, RX_VK_GPU_SKIP="1111111111111111, abc,2222222222222222,1111111111111111")
        run = subprocess.run([str(exe)] + [str(tmp / n) for n in ("real.txt", "none.txt", "last.txt", "after.txt")],
                             capture_output=True, text=True, env=env)
        need(run.returncode == 0, "gpu_skip.h's checks: " + run.stdout + run.stderr[-2000:])
        print(run.stdout.strip())


if __name__ == "__main__":
    main()
