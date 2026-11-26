"""Game-free: the PS5 keeps its log for a break's report (host/ps5/ps5_bug_report.c hos_ps5_log_keep, fed by host/hos_thread.c):

- hos_vlog keeps every line on the PS5, outside the Windows-only log thread (the PS5 has none: there the call was never
  compiled, and every report's log.txt was empty);
- many threads keeping lines at once: the report's log.txt is whole lines only, every one a line some thread kept, and
  it is at most 64 KB.

    python -I -B tests/test_ps5_log_keep.py [--cc gcc]
"""
import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))   # (python -I leaves the check's own folder off the path)
from srccut import block  # noqa: E402

RUN_ALL_ARGS = ["--cc", "{cc}"]
RUN_ALL_SKIP = {"windows": "POSIX threads and files, as the PS5's C library: checked on Linux"}
ROOT = Path(__file__).resolve().parents[1]

DRIVER = r'''
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "ps5_bug_report.h"
#define THREADS 8
#define LINES 10000
static void *keep(void *arg) {
    const long t = (long)arg;
    char line[128];
    for (long i = 0; i < LINES; i++) {
        const int n = snprintf(line, sizeof line, "thread %ld line %05ld of the log, kept by many\n", t, i);
        hos_ps5_log_keep(line, (size_t)n);
    }
    return NULL;
}
int main(int argc, char **argv) {
    if (argc < 2) return 2;
    pthread_t th[THREADS];
    for (long t = 0; t < THREADS; t++) pthread_create(&th[t], NULL, keep, (void *)t);
    for (int t = 0; t < THREADS; t++) pthread_join(th[t], NULL);
    char made[1024];
    if (!hos_ps5_bug_report_write(argv[1], "crash", "TEST", "threads", "Version: test\n", made, sizeof made)) return 3;
    printf("%s\n", made);
    return 0;
}
'''


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def check_source():
    src = (ROOT / "host" / "hos_thread.c").read_text(encoding="utf-8")
    vlog = block(src, "static void hos_vlog(int level, const char *fmt, va_list ap) {")
    need(re.search(r"#ifdef __PROSPERO__\s*\n\s*hos_ps5_log_keep\(line, strlen\(line\)\);", vlog),
         "hos_vlog keeps each line on the PS5 (hos_ps5_log_keep under __PROSPERO__)")
    win = src[src.index("#if defined(_WIN32) && !defined(__EMSCRIPTEN__)"):src.index("static int log_queue(const char *line) { (void)line; return 0; }")]
    need("hos_ps5_log_keep" not in win, "no PS5 keep left inside the Windows-only log thread")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    check_source()
    with tempfile.TemporaryDirectory(prefix="ps5-log-keep-") as tmp:
        tmp = Path(tmp)
        (tmp / "d.c").write_text(DRIVER, encoding="utf-8")
        exe = tmp / "d"
        base = [a.cc, "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-g", "-O1", str(tmp / "d.c"),
                str(ROOT / "host/ps5/ps5_bug_report.c"), "-I", str(ROOT / "host/ps5"), "-lpthread", "-o", str(exe)]
        r = subprocess.run(base[:1] + ["-fsanitize=thread"] + base[1:], capture_output=True, text=True)
        if r.returncode != 0:   # (a compiler without ThreadSanitizer: the text checks still run)
            r = subprocess.run(base, capture_output=True, text=True)
        need(r.returncode == 0, "it compiles: " + r.stderr[-3000:])
        title = tmp / "title"
        title.mkdir()
        r = subprocess.run([str(exe), str(title)], capture_output=True, text=True, timeout=120)
        need(r.returncode == 0 and "ThreadSanitizer" not in r.stderr, "many threads keep lines with no race: " + r.stderr[-2000:])
        log = (Path(r.stdout.strip()) / "log.txt").read_bytes()
        need(0 < len(log) <= 64 * 1024, "log.txt holds the last 64 KB at most (%d bytes)" % len(log))
        lines = log.decode("ascii", "replace").split("\n")
        need(lines[-1] == "", "log.txt ends at a line's end")
        bad = [l for l in lines[:-1] if not re.fullmatch(r"thread [0-7] line \d{5} of the log, kept by many", l)]
        need(not bad, "log.txt is whole lines only (%d torn, first: %r)" % (len(bad), bad[:1]))
    print("PASS: the PS5 keeps its log for a break's report, from any thread")


if __name__ == "__main__":
    main()
