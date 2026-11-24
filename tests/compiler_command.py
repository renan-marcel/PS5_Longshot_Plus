"""The C or C++ compiler a check builds its fixture with, as a command (a list of words), so a compiler given with its
own arguments or a path with spaces in it works: tests/test_oot_first_night.py.

    parse_compiler("ccache gcc")                -> ["ccache", "gcc"]
    parse_compiler(r"C:\\LLVM\\bin\\clang.exe") -> [r"C:\\LLVM\\bin\\clang.exe"]   (a path that exists is one word)
    compiler_command("CC", "gcc", "clang")      -> $CC's words, else the first of the names on PATH
"""
import os
import shlex
import shutil


def parse_compiler(text):
    """A compiler as the words to start it with: a file that exists as it is (its spaces kept), else split as a shell
    would (posix=False on Windows, where backslashes are a path's)"""
    text = text.strip()
    if not text:
        raise SystemExit("no compiler given")
    if os.path.isfile(text):
        return [text]
    words = shlex.split(text, posix=os.name != "nt")
    return [w[1:-1] if len(w) > 1 and w[0] == w[-1] == '"' else w for w in words]


def compiler_command(env, *names):
    """The environment variable env's compiler when it is set, else the first of names found on PATH"""
    given = os.environ.get(env, "").strip()
    if given:
        return parse_compiler(given)
    for name in names:
        found = shutil.which(name)
        if found:
            return [found]
    raise SystemExit("no compiler: set %s, or put one of %s on PATH" % (env, ", ".join(names)))
