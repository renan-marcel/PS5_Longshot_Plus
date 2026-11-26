"""The builder's Download amiibo option (ps5/builder/pipeline.py, app.py, package.py), with no game, no PyQt and no network:

  - STEPS has the eighth step, "Downloading the amiibo", in the pipeline and in the window;
  - amiibo(): without the option it says the step is skipped and runs nothing; with it, it runs amiibo.py with
    --app <title folder> --cache <work>/amiibo-cache; a failed run is one warning line and False, never pipeline.Stop;
    a run that writes nothing over an earlier build's amiibo/ says that catalogue is kept, not "added";
  - the window has the checkbox, the "amiibo" setting (default off) and passes --amiibo; package.py names pillow
    and copies amiibo.py into the kit.

python -I -B tests/test_builder_amiibo.py
"""
import contextlib
import io
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILDER = os.path.join(ROOT, "ps5", "builder")
sys.path[:0] = [BUILDER, os.path.join(ROOT, "nx2")]
import pipeline  # noqa: E402


def text(name):
    with open(os.path.join(BUILDER, name), encoding="utf-8") as f:
        return f.read()


class Recorder:
    def __init__(self, fail=False, write=True):
        self.calls, self.fail, self.write = [], fail, write

    def __call__(self, cmd, env=None, cwd=None, what=None):
        self.calls.append(cmd)
        if self.fail:
            raise pipeline.Stop("%s failed (exit 1)" % what)
        if self.write:   # (as amiibo.py writes it: amiibo.idx replaced whole)
            out = os.path.join(cmd[cmd.index("--app") + 1], "amiibo")
            os.makedirs(out, exist_ok=True)
            with open(os.path.join(out, "amiibo.idx.part"), "wb") as f:
                f.write(b"LSAMIIBO" + os.urandom(8))
            os.replace(os.path.join(out, "amiibo.idx.part"), os.path.join(out, "amiibo.idx"))


class AmiiboStep(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.app = os.path.join(self.tmp.name, "app")
        self.work = os.path.join(self.tmp.name, "work")
        os.makedirs(self.app)
        self.real = pipeline.run

    def tearDown(self):
        pipeline.run = self.real
        self.tmp.cleanup()

    def call(self, rec, wanted):
        pipeline.run = rec
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            got = pipeline.amiibo(os.path.join(self.tmp.name, "kit"), self.work, self.app, wanted)
        return got, out.getvalue()

    def test_steps(self):
        self.assertEqual(len(pipeline.STEPS), 8)
        self.assertEqual(pipeline.STEPS[7], "Downloading the amiibo")
        self.assertIn('"Downloading the amiibo"', text("app.py"))

    def test_skipped_without_the_option(self):
        rec = Recorder()
        got, out = self.call(rec, False)
        self.assertFalse(got)
        self.assertEqual(rec.calls, [])
        self.assertIn("@@step 8 8 Downloading the amiibo", out)
        self.assertIn("skipped", out)

    def test_runs_amiibo_py(self):
        rec = Recorder()
        got, out = self.call(rec, True)
        self.assertTrue(got)
        cmd = rec.calls[0]
        self.assertEqual(cmd[:3], [sys.executable, "-I", "-u"])
        self.assertEqual(cmd[3], os.path.join(pipeline.HERE, "amiibo.py"))
        self.assertEqual(cmd[cmd.index("--app") + 1], self.app)
        self.assertEqual(cmd[cmd.index("--cache") + 1], os.path.join(self.work, "amiibo-cache"))

    def test_a_failure_is_a_warning(self):
        got, out = self.call(Recorder(fail=True), True)
        self.assertFalse(got)
        self.assertIn("warning", out.lower())

    def test_nothing_written_is_a_warning(self):
        got, out = self.call(Recorder(write=False), True)
        self.assertFalse(got)
        self.assertIn("warning", out.lower())

    def earlier_catalogue(self):
        out = os.path.join(self.app, "amiibo")
        os.makedirs(out)
        with open(os.path.join(out, "amiibo.idx"), "wb") as f:
            f.write(b"LSAMIIBO-earlier")
        return os.path.join(out, "amiibo.idx")

    def test_a_failed_refresh_keeps_the_earlier_catalogue(self):
        # (amiibo.py warns and exits 0 when the download fails: an amiibo/ from an earlier build is still there)
        idx = self.earlier_catalogue()
        got, out = self.call(Recorder(write=False), True)
        self.assertFalse(got)
        self.assertIn("warning", out.lower())
        self.assertIn("keeps the catalogue of an earlier build", out)
        self.assertNotIn("amiibo: added", out)
        with open(idx, "rb") as f:
            self.assertEqual(f.read(), b"LSAMIIBO-earlier")
        got, out = self.call(Recorder(fail=True), True)   # (and a run that fails outright)
        self.assertFalse(got)
        self.assertIn("keeps the catalogue of an earlier build", out)
        self.assertNotIn("amiibo: added", out)

    def test_a_refresh_over_an_earlier_catalogue_is_added(self):
        self.earlier_catalogue()
        got, out = self.call(Recorder(), True)
        self.assertTrue(got)
        self.assertIn("amiibo: added", out)

    def test_build_calls_it_last(self):
        src = text("pipeline.py")
        b = src[src.index("def build(a):"):]
        b = b[:b.index("\ndef main")]
        self.assertLess(b.index("game_data("), b.index("amiibo("))
        self.assertLess(b.index("amiibo("), b.index('say("@@done'))
        self.assertIn("a.amiibo", b)
        self.assertIn('"--amiibo"', src)


class Window(unittest.TestCase):
    def test_checkbox_setting_and_argument(self):
        app = text("app.py")
        self.assertIn("Download amiibo (the catalogue and the figures' pictures, about 42 MB, once)", app)
        self.assertIn('self.settings.value("amiibo", "false")', app)
        self.assertIn('("amiibo", self.amiibo.isChecked())', app)
        self.assertIn('args += ["--amiibo"]', app)
        busy = app[app.index("def busy"):app.index("def start_or_stop")]
        self.assertIn("self.amiibo", busy)

    def test_the_step_count_is_not_a_literal(self):
        app = text("app.py")
        self.assertNotRegex(app, r"of 7|, 7\)|== 7")
        self.assertEqual(re.findall(r"\bABOUT\b", app)[:1], ["ABOUT"])
        self.assertRegex(app, r"\n    8: ")


class Packaging(unittest.TestCase):
    def test_pillow_and_amiibo_py(self):
        pkg = text("package.py")
        self.assertIn('"pillow==13.0.0"', pkg)
        self.assertRegex(pkg, r'"game_data\.py", "amiibo\.py"|"amiibo\.py"')
        self.assertRegex(text("build_kit.sh"), r"PYTHON_PACKAGES=\([^)]*\bpillow\b")
        self.assertIn("amiibo", text("package.py").split('README = """')[1].split('"""')[0].lower())


if __name__ == "__main__":
    unittest.main()
