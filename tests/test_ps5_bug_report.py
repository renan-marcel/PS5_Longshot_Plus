"""Game-free: the report a break leaves in bug-reports/ on the PS5 (host/ps5/ps5_bug_report.c), compiled for the PC with
AddressSanitizer.

- a folder bug-reports/<UTC date>_<UTC time>_<kind>, a second one in the same second gets _2;
- report.txt names the kind, the reason, the detail and the facts given; nothing else is needed for it;
- log.txt holds the log's last 64 KB, oldest first, from the start of a line, when more was kept; all of it when less;
- longshot_env.txt, longshot_options.ini and logs/crash_trace.txt are copied when there, and left out when not;
- every break reaches it: the PS5's signal handler, the end of win32_posix.c's (an unhandled one), hos_fatal (a trap of the
  game's code), the memory floor, a GPU freeze (as kind "freeze"); hos_thread.c keeps the log for it.

    python -I -B tests/test_ps5_bug_report.py [--cc gcc]
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "gcc"]
ROOT = Path(__file__).resolve().parents[1]

DRIVER = r'''
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ps5_bug_report.h"
int main(int argc, char **argv) {
    const long lines = atol(argv[2]);
    char line[128];
    for (long i = 0; i < lines; i++) {
        const int n = snprintf(line, sizeof line, "line %06ld of the log\n", i);
        hos_ps5_log_keep(line, (size_t)n);
    }
    char made[1024];
    for (int k = 3; k < argc; k++) {
        if (!hos_ps5_bug_report_write(argv[1], argv[k], "SIGNAL_11", "a memory fault", "Version: test\nScene: KokiriForest_Child\n",
                                      made, sizeof made)) return 3;
        printf("%s\n", made);
    }
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
    with tempfile.TemporaryDirectory(prefix="ps5-bug-report-") as tmp:
        tmp = Path(tmp)
        (tmp / "d.c").write_text(DRIVER, encoding="utf-8")
        exe = tmp / "d"
        r = subprocess.run([a.cc, "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-g", "-fsanitize=address,undefined",
                            str(tmp / "d.c"), str(ROOT / "host/ps5/ps5_bug_report.c"), "-I", str(ROOT / "host/ps5"), "-o", str(exe)],
                           capture_output=True, text=True)
        need(r.returncode == 0, "it compiles: " + r.stderr[-3000:])

        def run(title, lines, *kinds):
            r = subprocess.run([str(exe), str(title), str(lines), *kinds], capture_output=True, text=True,
                               env=dict(os.environ, ASAN_OPTIONS="detect_leaks=1"))
            need(r.returncode == 0 and "Sanitizer" not in r.stderr and "runtime error" not in r.stderr,
                 "it ran: %d %s" % (r.returncode, r.stderr[-2000:]))
            return [Path(p) for p in r.stdout.split()]

        # a title folder with its files: the report copies them
        t1 = tmp / "title1"
        (t1 / "logs").mkdir(parents=True)
        (t1 / "longshot_env.txt").write_text("RX_VK_TEX_MAX_DIM=512\n", encoding="utf-8")
        (t1 / "longshot_options.ini").write_text("resolution=1\n", encoding="utf-8")
        (t1 / "logs" / "crash_trace.txt").write_text("[PS5-TRACE] SIGNAL_11\n", encoding="utf-8")
        made = run(t1, 5000, "crash", "crash", "freeze")
        need(len(made) == 3 and made[0].parent == t1 / "bug-reports", "three folders under bug-reports/: %r" % made)
        need(made[0].name.endswith("_crash") and made[2].name.endswith("_freeze"), "named by kind: %r" % made)
        need(made[1].name.endswith("_crash_2") or made[1].name[:19] != made[0].name[:19], "a second crash in the same second: _2")
        report = (made[0] / "report.txt").read_text(encoding="utf-8")
        need("the title broke (crash)" in report and "SIGNAL_11: a memory fault" in report and "Scene: KokiriForest_Child" in report,
             "the report: " + report)
        log = (made[0] / "log.txt").read_text(encoding="utf-8")
        need(len(log) <= 64 * 1024 and log.startswith("line ") and log.endswith("line 004999 of the log\n"),
             "the log's last 64 KB, from a line's start, to the last line")
        for name, text in (("longshot_env.txt", "RX_VK_TEX_MAX_DIM=512\n"), ("longshot_options.ini", "resolution=1\n"),
                           ("crash_trace.txt", "[PS5-TRACE] SIGNAL_11\n")):
            need((made[0] / name).read_text(encoding="utf-8") == text, "%s copied" % name)

        # a bare folder and a short log: all of it, no copies
        t2 = tmp / "title2"
        t2.mkdir()
        made = run(t2, 3, "crash")
        log = (made[0] / "log.txt").read_text(encoding="utf-8")
        need(log == "".join("line %06d of the log\n" % i for i in range(3)), "a short log whole: %r" % log)
        need(sorted(p.name for p in made[0].iterdir()) == ["log.txt", "report.txt"], "nothing to copy, nothing copied")

    win = (ROOT / "host/ps5/win32_ps5.c").read_text(encoding="utf-8")
    handler = win[win.index("static void ps5_crash_sig_handler(int sig) {"):]
    need('hos_ps5_bug_report("crash", msg' in handler[:600], "the PS5's signal handler writes a report")
    need('hos_ps5_bug_report("freeze", "GPU_FREEZE_2S"' in win and 'hos_ps5_bug_report("crash", "MEMORY_FLOOR_EXIT"' in win,
         "a GPU freeze and the memory floor write one")
    need('hos_ps5_bug_report("crash", "UNHANDLED_SIGNAL", why);' in (ROOT / "host/posix/win32_posix.c").read_text(encoding="utf-8"),
         "an unhandled signal writes one")
    th = (ROOT / "host/hos_thread.c").read_text(encoding="utf-8")
    need('hos_ps5_bug_report("crash", "FATAL", buf);' in th and "hos_ps5_log_keep(lines[i], strlen(lines[i]));" in th,
         "a trap of the game's code writes one, and the log is kept for it")
    print("PASS: a break leaves its report in bug-reports/")


if __name__ == "__main__":
    main()
