"""Game-free: the shaders known to hang the PS5's GPU go into every title folder's longshot_env.txt, left out
(ps5/builder/known_gpu_hangs.txt, pipeline.py known_gpu_hangs and env_text, read by gpu/vk/gpu_skip.h from_build).

- The list shipped with the builder reads, and holds the compute program a cutscene and the Monster Coliseum froze on.
- A line that is not a program key stops the build, naming the file and the line; notes and blank lines are passed over;
  a key listed twice is written once.
- longshot_env.txt has the profile's switches and, after them, RX_VK_GPU_SKIP=<keys>; none with --no-known-skips (an empty
  list); the game takes the line from the file (host/hos_main.c env_line_allowed: an RX_ switch, not a file).
- The builder: --no-known-skips on its command line, the window's "Skip shaders known to hang the GPU" (on unless turned
  off) passing it, the list packaged beside pipeline.py.

    python -I -B tests/test_known_gpu_hangs.py
"""
import os
import re
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "ps5", "builder"), os.path.join(ROOT, "nx2")]
import pipeline  # noqa: E402

PROFILE = {"name": "PS5 / PS5 Slim", "env": {"HOS_PS5_RENDER_MB": "2560", "RX_VK_EXACT_STALE": "1"}}


def read(rel):
    with open(os.path.join(ROOT, rel), encoding="utf-8") as f:
        return f.read()


class List(unittest.TestCase):
    def test_the_shipped_list(self):
        keys = pipeline.known_gpu_hangs()
        self.assertIn("53fcaee4dc45c6ee", keys)
        for k in keys:
            self.assertRegex(k, r"^[0-9a-f]{16}$")
        self.assertEqual(len(keys), len(set(keys)))

    def write(self, text):
        fd, path = tempfile.mkstemp(suffix=".txt")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        self.addCleanup(os.remove, path)
        return path

    def test_notes_blank_lines_and_repeats(self):
        path = self.write("# a note\n\n  53FCAEE4DC45C6EE   compute  a cutscene\n# another\n0123456789abcdef graphics\n"
                          "53fcaee4dc45c6ee again\n")
        self.assertEqual(pipeline.known_gpu_hangs(path), ["53fcaee4dc45c6ee", "0123456789abcdef"])

    def test_a_line_that_is_not_a_key_stops_the_build(self):
        path = self.write("# keys\n53fcaee4dc45c6ee ok\n53fcaee4 short\n")
        with self.assertRaises(pipeline.Stop) as stop:
            pipeline.known_gpu_hangs(path)
        self.assertIn("line 3", str(stop.exception))
        self.assertIn("53fcaee4", str(stop.exception))

    def test_no_list_no_keys(self):
        self.assertEqual(pipeline.known_gpu_hangs(os.path.join(ROOT, "no-such-list.txt")), [])


class EnvFile(unittest.TestCase):
    def test_the_keys_after_the_profile(self):
        text = pipeline.env_text(PROFILE, ["53fcaee4dc45c6ee", "0123456789abcdef"])
        lines = [l for l in text.splitlines() if l and not l.startswith("#")]
        self.assertEqual(lines, ["HOS_PS5_RENDER_MB=2560", "RX_VK_EXACT_STALE=1",
                                 "RX_VK_GPU_SKIP=53fcaee4dc45c6ee,0123456789abcdef"])
        self.assertIn("PS5 / PS5 Slim", text)

    def test_none_without_them(self):
        self.assertNotIn("RX_VK_GPU_SKIP", pipeline.env_text(PROFILE, []))

    def test_title_writes_it_from_the_list(self):
        title = read("ps5/builder/pipeline.py")
        body = title[title.index("def title("):title.index("\ndef ", title.index("def title(") + 1)]
        self.assertIn("hangs = known_gpu_hangs() if known_skips else []", body)
        self.assertIn("f.write(env_text(profile, hangs))", body)

    def test_the_game_takes_the_line(self):
        main = read("host/hos_main.c")
        allowed = main[main.index("static int env_line_allowed("):main.index("static void", main.index("static int env_line_allowed("))]
        self.assertIn('"RX_"', allowed)   # (an RX_ switch, and its name ends in neither _FILE nor _DIR)
        self.assertFalse(re.search(r"_(FILE|DIR)$", "RX_VK_GPU_SKIP"))
        self.assertIn('getenv("RX_VK_GPU_SKIP")', read("gpu/vk/gpu_skip.h"))


class Builder(unittest.TestCase):
    def test_command_line_window_and_package(self):
        pipe = read("ps5/builder/pipeline.py")
        self.assertIn('ap.add_argument("--no-known-skips", action="store_true",', pipe)
        self.assertIn("title(kit, info, work, elf, native, out, a.model, not a.no_known_skips)", pipe)
        app = read("ps5/builder/app.py")
        self.assertIn('self.known_skips = QCheckBox("Skip shaders known to hang the GPU', app)
        self.assertIn('self.settings.value("known_skips", "true")', app)   # (on unless turned off)
        self.assertIn('if not self.known_skips.isChecked():\n            args += ["--no-known-skips"]', app)
        self.assertIn('"known_gpu_hangs.txt"', read("ps5/builder/package.py"))


if __name__ == "__main__":
    unittest.main()
