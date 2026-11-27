"""Game-free: the PS5 without its profile, and the memory floor's exit (host/hos_main.c load_longshot_env, host/ps5/win32_ps5.c).

- without longshot_env.txt beside the game, the PS5 / PS5 Slim profile's safe values apply (HOS_PS5_MEM_FLOOR_MB=400,
  RX_VK_TEX_MAX_DIM=512, RX_VK_TEX_SKIP_MB=2, HOS_PS5_TEX_RESERVE_MB=1800), a value already in the environment stays, and
  a notice says to copy the title folder again; with the file, none is added; hos_longshot_env_read says which;
- a memory floor exit logs its breakdown before it writes the report (so the report's log.txt has it), and the floor's
  lines go through the host's log;
- the report says the floor in use and whether longshot_env.txt was read.

load_longshot_env is cut from hos_main.c and compiled with stand-ins; the rest is read from the source.

    python -I -B tests/test_ps5_env_missing.py [--cc gcc]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

RUN_ALL_ARGS = ["--cc", "{cc}"]
RUN_ALL_SKIP = {"windows": "setenv, as the PS5's C library: checked on Linux"}
ROOT = Path(__file__).resolve().parents[1]
SAFE = {"HOS_PS5_MEM_FLOOR_MB": "400", "RX_VK_TEX_MAX_DIM": "512", "RX_VK_TEX_SKIP_MB": "2", "HOS_PS5_TEX_RESERVE_MB": "1800"}

HEAD = r'''
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef unsigned int DWORD;
#define MAX_PATH 260
static char game_path[512];
static DWORD hos_game_path_a(char *buf, DWORD size) { snprintf(buf, size, "%s", game_path); return (DWORD)strlen(buf); }
static char logged[4096];
static void hos_log(const char *fmt, ...) {
    va_list ap; va_start(ap, fmt);
    vsnprintf(logged + strlen(logged), sizeof logged - strlen(logged), fmt, ap);
    va_end(ap);
    strncat(logged, "\n", sizeof logged - strlen(logged) - 1);
}
'''
MAIN = r'''
int main(int argc, char **argv) {
    snprintf(game_path, sizeof game_path, "%s/eboot.bin", argv[1]);
    if (argc > 2) setenv("RX_VK_TEX_MAX_DIM", argv[2], 1);
    load_longshot_env();
    printf("read=%d\n", hos_longshot_env_read());
    const char *names[] = {"HOS_PS5_MEM_FLOOR_MB", "RX_VK_TEX_MAX_DIM", "RX_VK_TEX_SKIP_MB", "HOS_PS5_TEX_RESERVE_MB", "RX_TEST_SWITCH"};
    for (int i = 0; i < 5; i++) printf("%s=%s\n", names[i], getenv(names[i]) ? getenv(names[i]) : "-");
    printf("log=%s", logged);
    return 0;
}
'''


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def run(cc, src, tmp, title, extra=()):
    exe = tmp / "env"
    r = subprocess.run([cc, "-std=c11", "-D_GNU_SOURCE", "-DHOS_ENV_SAFE_TEST", "-Wall", "-Wno-unused-function", "-g",
                        str(src), "-o", str(exe)], capture_output=True, text=True)
    need(r.returncode == 0, "load_longshot_env compiles with the stand-ins: " + r.stderr[-3000:])
    r = subprocess.run([str(exe), str(title)] + list(extra), capture_output=True, text=True, timeout=30)
    need(r.returncode == 0, "it runs: " + r.stderr[-2000:])
    out = {}
    for line in r.stdout.splitlines():
        k, _, v = line.partition("=")
        out.setdefault(k, v)
    out["log"] = r.stdout[r.stdout.index("log=") + 4:]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    hm = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    code = HEAD + block(hm, "static int env_line_allowed(const char *name, const char *value) {") + "\n" + \
        hm[hm.index("static int env_read;"):hm.index("static void load_longshot_env(void) {")] + \
        block(hm, "static void load_longshot_env(void) {") + "\n" + block(hm, "int hos_longshot_env_read(void) {") + MAIN
    with tempfile.TemporaryDirectory(prefix="ps5-env-") as tmp:
        tmp = Path(tmp)
        src = tmp / "env.c"
        src.write_text(code, encoding="utf-8")
        title = tmp / "title"
        title.mkdir()
        got = run(a.cc, src, tmp, title)
        need(got["read"] == "0", "without the file, hos_longshot_env_read is 0")
        for k, v in SAFE.items():
            need(got[k] == v, "without the file %s is the profile's %s (got %s)" % (k, v, got[k]))
        need("longshot_env.txt not found" in got["log"] and "copy the whole title folder again" in got["log"],
             "a notice says the file is missing and what to do")
        got = run(a.cc, src, tmp, title, ["1024"])
        need(got["RX_VK_TEX_MAX_DIM"] == "1024", "a value already in the environment stays")
        (title / "longshot_env.txt").write_text("RX_TEST_SWITCH=1\n", encoding="utf-8")
        got = run(a.cc, src, tmp, title)
        need(got["read"] == "1" and got["RX_TEST_SWITCH"] == "1", "with the file it is read")
        need(all(got[k] == "-" for k in SAFE), "with the file, no safe value is added")
        need("not found" not in got["log"], "with the file, no notice")

    win = (ROOT / "host" / "ps5" / "win32_ps5.c").read_text(encoding="utf-8")
    watch = block(win, "static void *memory_floor_watch(void *unused) {")
    exit_at = watch.index('hos_ps5_bug_report("crash", "MEMORY_FLOOR_EXIT"')
    breakdown = watch.find("closing the title before the console runs out")
    need(0 <= breakdown < exit_at, "the floor exit logs its breakdown before it writes the report")
    need('fprintf(stderr, "[ps5] memory floor' not in watch, "the floor watch's lines go through the host's log, not stderr alone")
    report = block(win, "void hos_ps5_bug_report(const char *kind, const char *reason, const char *detail) {")
    need("Memory floor: %llu MiB" in report and "longshot_env.txt: %s" in report,
         "the report says the floor in use and whether longshot_env.txt was read")
    print("PASS: without its profile the PS5 takes the safe values and says so; a floor exit says why first")


if __name__ == "__main__":
    main()
