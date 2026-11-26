"""Game-free: the virtual amiibo core (host/amiibo_core.c, docs/superpowers/specs/2026-11-26-amiibo-design.md "2. Runtime"),
compiled for the PC with tests/amiibo_core_test.c (AddressSanitizer and UBSan where the compiler has them) and run in an empty
folder that stands for user/amiibo:

- the device states and Fritchii's rules: Initialize, ListDevices (one device; none with emulation off), Start/StopDetection,
  a figure touched only while the game searches (activate signalled, deactivate cleared), Mount/Unmount, removal (deactivate
  signalled; the info calls then say TagRemoved), Finalize;
- the infos from the 8-byte amiibo ID: ModelInfo (Link - Ocarina of Time), TagInfo (TypeA, Type2, a 7-byte UUID of the
  figure's own, or new random bytes on every read), CommonInfo (area size 0xD8), RegisterInfo (a neutral default Mii, the
  name cut to 10 characters);
- the application areas: <dir>/<amiibo id>/<access id>.bin and state.txt, the result codes for none, one already there and too
  big; auto-touch; emulation off.

    python -I -B tests/test_amiibo_core.py [--cc gcc]
"""
import argparse
from pathlib import Path
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "{cc}"]
ROOT = Path(__file__).resolve().parents[1]


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def compile_test(cc, exe, sanitize):
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g"] if sanitize else ["-g"]
    return subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror"] + flags +
                          [str(ROOT / "tests" / "amiibo_core_test.c"), str(ROOT / "host" / "amiibo_core.c"),
                           "-I", str(ROOT / "host"), "-o", str(exe)], capture_output=True, text=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default="gcc")
    a = ap.parse_args()
    with tempfile.TemporaryDirectory(prefix="amiibo-core-") as tmp:
        tmp = Path(tmp)
        exe = tmp / "amiibo_core_test.exe"
        r = compile_test(a.cc, exe, True)
        if r.returncode != 0:   # (a compiler without the sanitizers, llvm-mingw's: the checks still run; a real error repeats)
            r = compile_test(a.cc, exe, False)
        need(r.returncode == 0, "it compiles: " + r.stderr[-3000:])
        work = tmp / "amiibo"
        work.mkdir()
        r = subprocess.run([str(exe), str(work)], capture_output=True, text=True, timeout=60, cwd=str(tmp))
        out = r.stdout + r.stderr
        need("AddressSanitizer" not in out and "runtime error" not in out, "no memory error: " + out[-3000:])
        need(r.returncode == 0 and "PASS" in r.stdout, "the core's checks (exit %d): %s" % (r.returncode, out[-3000:]))
        need((work / "01000000034b0902" / "01006a80.bin").stat().st_size == 0xD8, "the area file, 0xD8 bytes, lower-case hex")
    print("PASS: the nfp state machine, the infos and the application areas")


if __name__ == "__main__":
    main()
