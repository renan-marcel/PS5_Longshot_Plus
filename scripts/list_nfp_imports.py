"""List the nn::nfp / nn::nfc functions a build imports (symbol names only, no game bytes).

Reads <work folder>/lift/sa/gen/a64_stubs.c, where nx2/standalone.py gen_stubs writes `/* <name> */` above each
unimplemented import, and prints `mangled<TAB>demangled` for every name starting with _ZN2nn3nfp or _ZN2nn3nfc.
The demangled column uses c++filt when it is on PATH, else repeats the mangled name.

    python -I scripts/list_nfp_imports.py <work folder>
"""
from pathlib import Path
import re
import shutil
import subprocess
import sys

PREFIXES = ("_ZN2nn3nfp", "_ZN2nn3nfc")
COMMENT = re.compile(r"^/\* (\S+) \*/\s*$")


def names(text):
    """The nfp/nfc names in a stub file, in file order, once each."""
    out = []
    for line in text.splitlines():
        m = COMMENT.match(line)
        if m and m.group(1).startswith(PREFIXES) and m.group(1) not in out:
            out.append(m.group(1))
    return out


def demangle(mangled):
    cxxfilt = shutil.which("c++filt")
    if not cxxfilt or not mangled:
        return list(mangled)
    try:
        r = subprocess.run([cxxfilt], input="\n".join(mangled) + "\n", capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return list(mangled)
    lines = r.stdout.splitlines()
    return lines if r.returncode == 0 and len(lines) == len(mangled) else list(mangled)


def main(argv):
    if len(argv) != 2:
        sys.exit("usage: python -I scripts/list_nfp_imports.py <work folder>")
    stubs = Path(argv[1]) / "lift" / "sa" / "gen" / "a64_stubs.c"
    if not stubs.is_file():
        sys.exit("no %s (build once, then give the build's work folder)" % stubs)
    found = names(stubs.read_text(encoding="utf-8", errors="replace"))
    for m, d in zip(found, demangle(found)):
        print("%s\t%s" % (m, d))


if __name__ == "__main__":
    main(sys.argv)
