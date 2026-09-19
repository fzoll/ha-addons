"""Exercise pinned checkout selection against real local Git history."""
from pathlib import Path
import subprocess
import tempfile
import unittest


class RevisionTest(unittest.TestCase):
    def test_pin_upgrade_rollback_and_reject_unrelated(self):
        script = str(Path(__file__).resolve().parents[1] / "resolve-revision.sh")
        with tempfile.TemporaryDirectory() as directory:
            remote = Path(directory) / "remote"
            remote.mkdir()
            build = Path(directory) / "build"

            def git(*args):
                return subprocess.check_output(
                    ["git", "-C", str(remote), *args],
                    stderr=subprocess.DEVNULL, text=True,
                ).strip()

            git("init", "-b", "fork/cc-runner-support")
            git("config", "user.name", "Test")
            git("config", "user.email", "test@example.invalid")
            (remote / "file").write_text("one")
            git("add", ".")
            git("commit", "-m", "one")
            first = git("rev-parse", "HEAD")
            (remote / "file").write_text("two")
            git("commit", "-am", "two")
            second = git("rev-parse", "HEAD")
            git("checkout", "--orphan", "unrelated")
            git("commit", "-am", "other")
            other = git("rev-parse", "HEAD")
            git("checkout", "fork/cc-runner-support")
            for sha in [first, second, first]:
                result = subprocess.run(
                    ["bash", script, str(build), str(remote), "fork/cc-runner-support", sha],
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                head = subprocess.check_output(
                    ["git", "-C", str(build), "rev-parse", "HEAD"], text=True,
                ).strip()
                self.assertEqual(head, sha)
            for sha in [other, "main"]:
                result = subprocess.run(
                    ["bash", script, str(build), str(remote), "fork/cc-runner-support", sha],
                    capture_output=True, text=True,
                )
                self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
