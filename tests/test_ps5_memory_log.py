"""Game-free: the PS5's logs/memory.txt (host/ps5/memory_line.h, written by host/ps5/win32_ps5.c memory_floor_watch):

- a line's format: t, why, scene, zone, free and largest piece, the game's committed pages, the prefetch's bytes, zone_boost,
  then the renderer's own numbers (gpu/vk rx_vk_memory_stats);
- when: at a zone change ("zone"), 5 s after it ("after"), every 60 s ("tick"), and just before a memory floor exit ("floor");
- the watch thread writes them, the zone change reaches it from the prefetch's callback, the renderer's function fills
  every key.

    python -I -B tests/test_ps5_memory_log.py [--cc gcc]
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

DRIVER = r'''
#include <stdio.h>
#include <string.h>
#include "memory_line.h"
int main(void) {
    char line[1024];
    memory_line(line, sizeof line, 12.5, "zone", "A_Adult", "A", 4100, 900, 6200, 12, 1, "vma_block_mb=800 vma_alloc_mb=700");
    if (strcmp(line, "t=12.5 why=zone scene=A_Adult zone=A free_mb=4100 largest_mb=900 committed_mb=6200 prefetch_mb=12 "
                     "zone_boost=1 vma_block_mb=800 vma_alloc_mb=700")) { printf("FAIL line: %s\n", line); return 1; }
    memory_line(line, sizeof line, 1.0, "tick", "", "", 1, 1, 1, 0, 0, "");
    if (strcmp(line, "t=1.0 why=tick scene=- zone=- free_mb=1 largest_mb=1 committed_mb=1 prefetch_mb=0 zone_boost=0")) {
        printf("FAIL empty: %s\n", line); return 1;
    }
    MemSched m = MEM_SCHED_INIT;
    char got[512] = "";
    for (unsigned long long t = 0; t <= 130000; t += 500) {
        const int zone = t == 10000 || t == 70000;
        const char *why = mem_sched_due(&m, t, zone);
        if (why) { char e[32]; snprintf(e, sizeof e, "%s@%llu ", why, t / 1000); strcat(got, e); }
    }
    if (strcmp(got, "tick@0 zone@10 after@15 tick@60 zone@70 after@75 tick@120 ")) { printf("FAIL sched: %s\n", got); return 1; }
    printf("ok\n");
    return 0;
}
'''


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="ps5-memory-") as tmp:
        tmp = Path(tmp)
        (tmp / "d.c").write_text(DRIVER, encoding="utf-8")
        exe = tmp / "d"
        r = subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(tmp / "d.c"), "-I", str(ROOT / "host" / "ps5"),
                            "-o", str(exe)], capture_output=True, text=True)
        need(r.returncode == 0, "host/ps5/memory_line.h compiles: " + r.stderr[-2000:])
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        need(r.returncode == 0, r.stdout + r.stderr)
    win = (ROOT / "host" / "ps5" / "win32_ps5.c").read_text(encoding="utf-8")
    watch = block(win, "static void *memory_floor_watch(void *unused) {")
    write = block(win, "static void mem_write(const char *why, uint64_t room, uint64_t started_ms) {")
    need('hos_ps5_logfile("memory.txt", line);' in write and "memory_line(" in write, "mem_write writes a memory line to logs/memory.txt")
    need("mem_sched_due(" in watch and "mem_write(why, room, started_ms);" in watch, "the watch thread writes it on its schedule")
    floor = watch[watch.index("if (room < floor) {"):]
    need(0 <= floor.find('mem_write("floor"') < floor.index("hos_ps5_exit(3);"), "a floor exit writes its line before the title closes")
    start = block(win, "void hos_ps5_memory_floor_start(void) {")
    need("asset_prefetch_on_zone(" in start, "the zone change reaches the watch thread (the prefetch's callback)")
    vma = (ROOT / "gpu" / "vk" / "vk_vma.cpp").read_text(encoding="utf-8")
    stats = block(vma, 'extern "C" void rx_vk_memory_stats(char* out, size_t n) {')
    for key in ("vma_block_mb=", "vma_alloc_mb=", "tex_n=", "tex_mb=", "mirror_mb="):
        need(key in stats, "the renderer's numbers include " + key)
    print("PASS: logs/memory.txt at each zone change, after it and every minute")


if __name__ == "__main__":
    main()
