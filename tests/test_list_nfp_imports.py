"""scripts/list_nfp_imports.py lists the nn::nfp / nn::nfc imports of a build's stub file (symbol names only), game-free:
a made-up lift/sa/gen/a64_stubs.c with two nfp stubs, one nfc and one other namespace.

    python -I -B tests/test_list_nfp_imports.py
"""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "list_nfp_imports.py"

NFP_A = "_ZN2nn3nfp10InitializeEv"
NFP_B = "_ZN2nn3nfp14GetDeviceStateERKNS0_12DeviceHandleE"
NFC = "_ZN2nn3nfc10InitializeEv"
OTHER = "_ZN2nn2os9SleepTickEv"


def stub(name):
    return ("/* %s */\nvoid imp_%s(Ctx *A64_NOESC c) { static int seen; a64_unimplemented(c, \"%s\", &seen); }\n"
            % (name, name, name))


def run(work):
    r = subprocess.run([sys.executable, "-I", str(SCRIPT), str(work)], capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def main():
    with tempfile.TemporaryDirectory() as tmp:
        gen = Path(tmp) / "lift" / "sa" / "gen"
        gen.mkdir(parents=True)
        (gen / "a64_stubs.c").write_text("".join(stub(n) for n in (NFP_A, OTHER, NFC, NFP_B)), encoding="utf-8")
        code, out, err = run(tmp)
        assert code == 0, err
        rows = [line.split("\t") for line in out.splitlines()]
        assert [r[0] for r in rows] == [NFP_A, NFC, NFP_B], rows
        assert all(len(r) == 2 and r[1] for r in rows), rows
        assert OTHER not in out
        # no stub file: a message and a non-zero exit, not a traceback
        code, out, err = run(Path(tmp) / "none")
        assert code != 0 and "a64_stubs.c" in err and "Traceback" not in err, (code, err)
    print("ok")


main()
