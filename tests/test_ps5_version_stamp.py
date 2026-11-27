"""PS5 version discovery through a Windows Git worktree from WSL.

    python -I -B tests/test_ps5_version_stamp.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "nx2"))
import version  # noqa: E402


def main():
    with tempfile.TemporaryDirectory() as root:
        with open(os.path.join(root, ".git"), "w", encoding="utf-8") as f:
            f.write("gitdir: C:/Users/renan/repo/.git/worktrees/build\n")
        calls = []

        def run(args, **kwargs):
            calls.append((args, kwargs))
            if args[0] == "git":
                return subprocess.CompletedProcess(args, 128, "", "Windows worktree gitdir")
            if args[0] == "git.exe":
                return subprocess.CompletedProcess(args, 0, "v3.1.4-2-gabc123\r\n", "")
            raise AssertionError("unexpected command: %r" % args)

        with mock.patch.dict(os.environ, {"LONGSHOT_VERSION": ""}), \
                mock.patch.object(shutil, "which", return_value="git.exe"), \
                mock.patch.object(version.subprocess, "run", side_effect=run):
            actual = version.release(root)

        assert actual == "v3.1.4-2-gabc123", actual
        assert [c[0][0] for c in calls] == ["git", "git.exe"], calls
        assert calls[1][1]["cwd"] == root, calls
    print("PS5 version stamp: WSL falls back to Git for Windows")


if __name__ == "__main__":
    main()
