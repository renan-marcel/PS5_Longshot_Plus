"""Game-free: the game's nn::nfp calls answered by the amiibo core (host/nn_nfp.c, docs/amiibo-nfp-calls.md).

- The names: every mangled name in docs/amiibo-nfp-calls.md's table has its HLE(<name>) in host/nn_nfp.c, and the file
  binds no nn::nfp name the table does not list (the table is the game's imports: one more would bind nothing, one fewer
  would leave the game a stub that returns 0). The file includes amiibo_core.h.
- The behaviour (with a compiler): host/nn_nfp.c, unchanged, is compiled with host/amiibo_core.c against a stand-in of
  hos.h (a Ctx with x[], HLE as a plain function, a guest memory array for GP, a log that is kept) and run by
  tests/nfp_hle_test.c: ListDevices writes the handle and the count (0 with emulation off, success), the device calls go
  to the core (DeviceNotFound with emulation off), GetDeviceState gives the state in x0 and logs it only when it changes,
  GetNpadId writes 0, Create/RecreateApplicationArea read {access id @0, data @8, size @0x10} and a size over 0xD8 is
  refused, the settings applet calls return 0 with the handle written (and registered = true and the figure's
  RegisterInfo for StartNicknameAndOwnerSettings), the availability event is the guest's (init, signalled by the core),
  a null guest pointer is never written through, and every log line starts with [NFP].

    python -I -B tests/test_nfp_hle_names.py [--cc gcc]
"""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

RUN_ALL_ARGS = ["--cc", "{cc}"]
ROOT = Path(__file__).resolve().parents[1]

# (the stand-in: what host/nn_nfp.c uses of hos.h, no a64.h and no lifted game)
HOS_H = r"""
#ifndef HOS_H
#define HOS_H
#include <stdint.h>
#include <stddef.h>
typedef struct Ctx { uint64_t x[32]; } Ctx;
#define HLE(sym) void imp_##sym(Ctx *c)
#define ARG(n) (c->x[n])
#define RET(v) (c->x[0] = (uint64_t)(v))
#define TEST_MEM_SIZE 0x10000u
extern uint8_t test_mem[TEST_MEM_SIZE];
#define GP(a) ((void *)(test_mem + (uint64_t)(a)))
#define G64(a) (*(uint64_t *)GP(a))
#define G32(a) (*(uint32_t *)GP(a))
static inline void *hos_guest_range(uint64_t a, uint64_t n) {
    return a < TEST_MEM_SIZE && n <= TEST_MEM_SIZE - a ? GP(a) : (void *)0;
}
void hos_log(const char *fmt, ...);
#endif
"""


def need(cond, what):
    if not cond:
        raise SystemExit("FAIL: " + what)


def table_names():
    text = (ROOT / "docs" / "amiibo-nfp-calls.md").read_text(encoding="utf-8")
    names = re.findall(r"^\| `(_ZN2nn3nf[pc]\w+)` \|", text, re.M)
    need(len(names) == 23 and len(set(names)) == 23, "docs/amiibo-nfp-calls.md lists the 23 imports (found %d)" % len(names))
    return set(names)


def check_names(src):
    want = table_names()
    bound = re.findall(r"^HLE\((\w+)\)", src, re.M)
    need(len(bound) == len(set(bound)), "host/nn_nfp.c binds a name twice")
    missing = sorted(want - set(bound))
    need(not missing, "host/nn_nfp.c does not bind: " + ", ".join(missing))
    extra = sorted(set(bound) - want)
    need(not extra, "host/nn_nfp.c binds names the game does not import (docs/amiibo-nfp-calls.md): " + ", ".join(extra))
    need(re.search(r'^#include "amiibo_core\.h"', src, re.M), "host/nn_nfp.c includes amiibo_core.h")


def compile_test(cc, work, exe, sanitize):
    flags = ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-g"] if sanitize else ["-g"]
    return subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror"] + flags +
                          [str(ROOT / "tests" / "nfp_hle_test.c"), str(work / "nn_nfp.c"), str(work / "amiibo_core.c"),
                           "-I", str(work), "-o", str(exe)], capture_output=True, text=True)


def check_behaviour(cc):
    with tempfile.TemporaryDirectory(prefix="nfp-hle-") as tmp:
        tmp = Path(tmp)
        work = tmp / "src"
        work.mkdir()
        # (copied beside the stand-in: "hos.h" is looked for first in the including file's folder)
        for name in ("nn_nfp.c", "amiibo_core.c", "amiibo_core.h"):
            shutil.copyfile(ROOT / "host" / name, work / name)
        (work / "hos.h").write_text(HOS_H, encoding="utf-8")
        exe = tmp / "nfp_hle_test.exe"
        r = compile_test(cc, work, exe, True)
        if r.returncode != 0:   # (a compiler without the sanitizers: the checks still run; a real error repeats)
            r = compile_test(cc, work, exe, False)
        need(r.returncode == 0, "host/nn_nfp.c compiles against the stand-in: " + r.stderr[-3000:])
        amiibo = tmp / "amiibo"
        amiibo.mkdir()
        r = subprocess.run([str(exe), str(amiibo)], capture_output=True, text=True, timeout=60, cwd=str(tmp))
        out = r.stdout + r.stderr
        need("AddressSanitizer" not in out and "runtime error" not in out, "no memory error: " + out[-3000:])
        need(r.returncode == 0 and "PASS" in r.stdout, "the bindings' checks (exit %d): %s" % (r.returncode, out[-3000:]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cc", default=None, help="a C compiler: also run the bindings (tests/nfp_hle_test.c)")
    a = ap.parse_args()
    path = ROOT / "host" / "nn_nfp.c"
    need(path.exists(), "host/nn_nfp.c exists")
    check_names(path.read_text(encoding="utf-8"))
    if a.cc:
        check_behaviour(a.cc)
        print("PASS: host/nn_nfp.c binds the game's 23 nn::nfp imports, and they answer through the core")
    else:
        print("PASS: host/nn_nfp.c binds the game's 23 nn::nfp imports (no --cc: the bindings were not run)")


if __name__ == "__main__":
    main()
