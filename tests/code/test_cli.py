import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.code.snapshots import load_snapshot


class TestCli(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "demo repository"
        self.root.mkdir()
        self.source = self.root / "client.py"
        self.source.write_text("def connect(timeout=10):\n    pass\n", encoding="utf-8")
        self.baseline = Path(self.temporary.name) / "baseline.json"

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "docguard", *map(str, args)],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def snapshot(self):
        result = self.run_cli("snapshot", self.root, "--output", self.baseline)
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def test_snapshot_and_unchanged_comparison(self):
        result = self.snapshot()
        self.assertIn("Saved 1 entities", result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertIn("client.py:connect", load_snapshot(self.baseline))
        result = self.run_cli("compare", self.baseline, "--root", self.root)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "No changes detected.\n")

    def test_metadata_changes_and_movement_leave_baseline_unchanged(self):
        self.source.write_text(
            "def connect(timeout=10):\n    pass\ndef gone(): pass\n", encoding="utf-8"
        )
        self.snapshot()
        original = self.baseline.read_bytes()
        self.source.write_text(
            "# Comment\n\ndef connect(timeout=30):\n    pass\ndef added(): pass\n",
            encoding="utf-8",
        )
        result = self.run_cli("compare", self.baseline, "--root", self.root)
        self.assertEqual(result.returncode, 1, result.stderr)
        for expected in (
            "ADDED client.py:added",
            "REMOVED client.py:gone",
            "MODIFIED client.py:connect: parameters",
            "MOVED client.py:connect: lines 1-2 -> 3-4",
            "1 added, 1 removed, 1 modified, 1 moved",
        ):
            self.assertIn(expected, result.stdout)
        self.assertEqual(result.stderr, "")
        self.assertEqual(self.baseline.read_bytes(), original)

    def test_line_only_change_returns_one_without_modification(self):
        self.snapshot()
        self.source.write_text(
            "# Comment\ndef connect(timeout=10):\n    pass\n", encoding="utf-8"
        )
        result = self.run_cli("compare", self.baseline, "--root", self.root)
        self.assertEqual(result.returncode, 1)
        self.assertIn("MOVED", result.stdout)
        self.assertNotIn("MODIFIED", result.stdout)

    def test_help_and_bad_arguments(self):
        for args in (("--help",), ("snapshot", "--help"), ("compare", "--help")):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 0)
                self.assertIn("usage:", result.stdout)
        for args in (
            (),
            ("unknown",),
            ("snapshot", self.root),
            ("compare", self.baseline),
        ):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_missing_paths_and_invalid_snapshot(self):
        cases = (
            ("snapshot", self.root / "missing", "--output", self.baseline),
            (
                "snapshot",
                self.root,
                "--output",
                self.root / "missing" / "snapshot.json",
            ),
            ("compare", self.baseline, "--root", self.root),
        )
        for args in cases:
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertNotIn("Traceback", result.stderr)
        self.baseline.write_text(
            '{"schema_version": 999, "entities": []}', encoding="utf-8"
        )
        result = self.run_cli("compare", self.baseline, "--root", self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unsupported snapshot schema version", result.stderr)

    def test_invalid_source_preserves_existing_snapshot(self):
        self.snapshot()
        original = self.baseline.read_bytes()
        self.source.write_text("def broken(:", encoding="utf-8")
        for args in (
            ("snapshot", self.root, "--output", self.baseline),
            ("compare", self.baseline, "--root", self.root),
        ):
            with self.subTest(args=args):
                result = self.run_cli(*args)
                self.assertEqual(result.returncode, 2)
                self.assertIn("client.py:1:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(self.baseline.read_bytes(), original)

    def test_snapshot_cannot_overwrite_python_source(self):
        original = self.source.read_bytes()
        result = self.run_cli("snapshot", self.root, "--output", self.source)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.source.read_bytes(), original)

    def test_empty_repository(self):
        self.source.unlink()
        self.snapshot()
        self.assertEqual(load_snapshot(self.baseline), {})
        result = self.run_cli("compare", self.baseline, "--root", self.root)
        self.assertEqual(result.returncode, 0)
