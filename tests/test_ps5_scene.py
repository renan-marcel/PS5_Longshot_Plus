"""Game-free: the scene is known on the PS5 (host/hos_main.c, host/scene_poll.h, host/ps5/asset_prefetch.c).

The Sequence_CurrentBanc read lived in the Windows/Linux debug tools only, so on the PS5 a break's report said "Scene: not
known yet" and the prefetch never saw a scene change. Now:

- the game-data readers (oot_singleton, oot_gamedata_string) are compiled for every target, outside the debug tools;
- on the PS5 the player's hook polls the scene every 500 ms (host/scene_poll.h) and tells the prefetch on a change, once;
- an empty or unchanged name is no change; the poll's clock lets one read through per 500 ms;
- before the first scene is known, the prefetch's scene is the one whose parameters were last opened.

    python -I -B tests/test_ps5_scene.py [--cc gcc]
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
GUARD = "#if defined(_WIN32) || defined(__linux__)   /* (the debug tools: host/posix has what they call) */"

DRIVER = r'''
#include <stdio.h>
#include <string.h>
#include "scene_poll.h"
int main(void) {
    ScenePoll p = SCENE_POLL_INIT;
    const char *names[] = {"", "SceneA", "SceneA", "SceneB", "", "SceneB", "SceneC"};
    int changes = 0;
    char seen[256] = "";
    for (int i = 0; i < 7; i++)
        if (scene_poll_changed(&p, names[i])) changes++, strcat(seen, names[i]), strcat(seen, ";");
    if (changes != 3 || strcmp(seen, "SceneA;SceneB;SceneC;")) { printf("FAIL changes %d: %s\n", changes, seen); return 1; }
    ScenePoll q = SCENE_POLL_INIT;
    int due = 0;
    for (unsigned long long t = 1000; t < 3000; t += 100) due += scene_poll_due(&q, t);
    if (due != 4) { printf("FAIL due %d (one read per 500 ms over 2 s)\n", due); return 1; }
    printf("ok\n");
    return 0;
}
'''


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def guarded_spans(src):
    """the [start, end) spans of the debug-tools blocks (each GUARD to its matching #endif)"""
    spans, at = [], 0
    while True:
        i = src.find(GUARD, at)
        if i < 0:
            return spans
        depth, j = 0, i
        for line_end in iter(lambda: src.find("\n", j), -1):
            line = src[j:line_end].lstrip()
            if line.startswith("#if"):
                depth += 1
            elif line.startswith("#endif"):
                depth -= 1
                if depth == 0:
                    spans.append((i, line_end))
                    break
            j = line_end + 1
        at = spans[-1][1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    hm = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    spans = guarded_spans(hm)
    for marker in ("static uint64_t oot_singleton(Ctx *c, uint64_t slot) {",
                   "static int oot_gamedata_string(Ctx *c, uint32_t hash, char *buf, size_t size) {"):
        at = hm.index(marker)
        need(not any(s <= at < e for s, e in spans), marker.split("(")[0] + " is compiled for the PS5 (outside the debug tools)")
    lift = block(hm, "void hos_oot_lift_player(Ctx *c, uint64_t actor) {")
    ps5 = lift[lift.index("#else"):]
    need("hos_ps5_scene_poll(c);" in ps5, "on the PS5 the player's hook polls the scene")
    poll = block(hm, "static void hos_ps5_scene_poll(Ctx *c) {")
    need("scene_poll_due(" in poll and "scene_poll_changed(" in poll and "asset_prefetch_scene(" in poll and
         '"map: %s"' in poll, "the poll reads at most every 500 ms and tells the prefetch, and the log, of a change")
    ap_src = (ROOT / "host" / "ps5" / "asset_prefetch.c").read_text(encoding="utf-8")
    now = block(ap_src, "const char *asset_prefetch_scene_now(void) {")
    need("scene_now[0] ? scene_now : scene_loading" in now, "before the first scene, the one being loaded is the scene")
    with tempfile.TemporaryDirectory(prefix="ps5-scene-") as tmp:
        tmp = Path(tmp)
        (tmp / "d.c").write_text(DRIVER, encoding="utf-8")
        exe = tmp / "d"
        r = subprocess.run([a.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", str(tmp / "d.c"), "-I", str(ROOT / "host"),
                            "-o", str(exe)], capture_output=True, text=True)
        need(r.returncode == 0, "host/scene_poll.h compiles: " + r.stderr[-2000:])
        r = subprocess.run([str(exe)], capture_output=True, text=True, timeout=30)
        need(r.returncode == 0, r.stdout + r.stderr)
    print("PASS: the scene is known on the PS5")


if __name__ == "__main__":
    main()
