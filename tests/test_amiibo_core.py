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
  big; auto-touch; emulation off;
- the start: amiibo_load_options (hos_main.c, before the game runs) puts longshot_options.ini's Amiibo rows and figure in the
  core, so the game's first Initialize, ListDevices and StartDetection see them before the menu first ticks.

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


def check_seed_keys():
    """the keys amiibo_load_options reads are the ones the menu writes: ini_key of the three rows (their names, lower case,
    spaces as _) and save()'s amiibo_figure_id=; and hos_main.c seeds the core from the options file before the game runs"""
    menu = (ROOT / "gpu" / "vk" / "vk_menu.cpp").read_text(encoding="utf-8")
    core = (ROOT / "host" / "amiibo_core.c").read_text(encoding="utf-8")
    for row, key in (("Amiibo emulation", "amiibo_emulation"), ("Random tag ID", "random_tag_id"),
                     ("Touch when the game asks", "touch_when_the_game_asks")):
        need('{TAB_AMIIBO, "%s", &opts.' % row in menu, "the Amiibo tab has the row " + row)
        need(row.lower().replace(" ", "_") == key and '"%s="' % key in core, "the core reads %s= (the row %s)" % (key, row))
    need('"amiibo_figure_id=%s\\n", opts.amiibo_id' in menu and '"amiibo_figure_id="' in core, "amiibo_figure_id=")
    main_c = (ROOT / "host" / "hos_main.c").read_text(encoding="utf-8")
    at = main_c.find("amiibo_load_options(hos_options_file());")
    need(0 < main_c.find("hos_options_carry();") < at < main_c.find("reserve_guest()"),
         "hos_main.c seeds the core from the options file, after it is carried and before the game is loaded")


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
        # (hos_main.c's start: longshot_options.ini read into the core before the game's first call and the menu's first tick;
        # the keys are the rows' ini_key and save()'s amiibo_figure_id=, the last line of a key counting)
        check_seed_keys()
        seeds = [
            ("amiibo_emulation=0\nrandom_tag_id=1\namiibo_emulation=1\nrandom_tag_id=0\ntouch_when_the_game_asks=1\n"
             "amiibo_figure_id=01000000034B0902\n", ["1", "0", "1", "01000000034b0902"]),
            ("amiibo_emulation=1\nrandom_tag_id=1\ntouch_when_the_game_asks=0\namiibo_figure_id=01000000034b0902\r\n",
             ["1", "1", "0", "01000000034b0902"]),
            ("amiibo_emulation=0\namiibo_figure_id=01000000034b0902\n", ["0", "1", "1", "01000000034b0902"]),
            ("amiibo_figure_id=nothex\n", ["1", "1", "1", "-"]),
            (None, ["1", "1", "1", "-"]),   # (no options file yet: each switch on, no figure)
        ]
        for i, (content, want) in enumerate(seeds):
            ini = tmp / ("seed%d.ini" % i)
            if content is not None:
                ini.write_bytes(content.encode())
            seed_dir = tmp / ("seed%d" % i)
            seed_dir.mkdir()
            r = subprocess.run([str(exe), str(seed_dir), "seed", str(ini)] + want, capture_output=True, text=True,
                               timeout=60, cwd=str(tmp))
            out = r.stdout + r.stderr
            need(r.returncode == 0 and "PASS" in r.stdout,
                 "the options seeded at start, case %d (exit %d): %s" % (i, r.returncode, out[-3000:]))
    print("PASS: the nfp state machine, the infos and the application areas")


if __name__ == "__main__":
    main()
