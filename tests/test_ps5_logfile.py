"""Game-free: the PS5's files in logs/ (host/ps5/ps5_logfile.c), compiled for the PC with a temp folder as the title folder:

- each name its own file, made with its logs/ folder, lines in order and on disk at once;
- a file already past the cap from an earlier run is started over;
- at the cap one last line says the file is full, and nothing after; another file goes on;
- with no title folder known, nothing is written.

nn_nfp.c's logs/nfp.txt goes through it (tests/test_nfp_hle_names.py links the two).

    python -I -B tests/test_ps5_logfile.py [--cc gcc]
"""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

RUN_ALL_ARGS = ["--cc", "{cc}"]
RUN_ALL_SKIP = {"windows": "POSIX file calls, as the PS5's C library: checked on Linux"}
ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="ps5-logfile-") as tmp:
        tmp = Path(tmp)
        exe = tmp / "logfile"
        base = [a.cc, "-std=c11", "-D_GNU_SOURCE", "-Wall", "-Wextra", "-Werror", "-g", "-DPS5_LOGFILE_CAP=1024",
                str(ROOT / "tests" / "ps5_logfile_test.c"), str(ROOT / "host" / "ps5" / "ps5_logfile.c"),
                "-I", str(ROOT / "host" / "ps5"), "-lpthread", "-o", str(exe)]
        r = subprocess.run(base[:1] + ["-fsanitize=address,undefined"] + base[1:], capture_output=True, text=True)
        if r.returncode != 0:   # (a compiler without the sanitizers: the checks still run; a real error repeats)
            r = subprocess.run(base, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit("FAIL: host/ps5/ps5_logfile.c compiles: " + r.stderr[-3000:])
        title = tmp / "title"
        title.mkdir()
        r = subprocess.run([str(exe), str(title)], capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            sys.exit("FAIL:\n" + r.stdout + r.stderr)
    print("ps5 logfile: ok")


if __name__ == "__main__":
    main()
