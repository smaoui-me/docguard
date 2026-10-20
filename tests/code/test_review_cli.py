import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.code.index import index_repository
from docguard.code.snapshots import save_snapshot


class TestReviewCli(unittest.TestCase):
    def test_json_output_matches_text_findings(self):
        self.source.write_text(self.original.replace("10", "30"), encoding="utf-8")
        result = self.run_cli(
            "review",
            self.baseline,
            "--root",
            self.root,
            "--mapping",
            self.mapping,
            "--format",
            "json",
        )
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(result.stdout)
        self.assertEqual(report["schema_version"], 2)
        self.assertEqual(report["removed_links"], [])
        self.assertEqual(report["documents"][0]["document"], "docs/client.md")
        self.assertEqual(
            report["documents"][0]["reasons"][0]["changed_fields"], ["parameters"]
        )
        self.assertIn("modified: parameters", self.review().stdout)

    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "demo repo"
        (self.root / "docs").mkdir(parents=True)
        self.document = self.root / "docs/client.md"
        self.document.write_text("Client documentation", encoding="utf-8")
        self.source = self.root / "client.py"
        self.original = "def connect(timeout=10): pass\ndef close(): pass\n"
        self.source.write_text(self.original, encoding="utf-8")
        self.baseline = self.base / "baseline.json"
        save_snapshot(index_repository(self.root), self.baseline)
        self.mapping = self.base / "mapping.json"
        self.mapping.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "documents": {
                        "docs/client.md": ["client.py:connect", "client.py:close"],
                    },
                }
            ),
            encoding="utf-8",
        )

    def run_cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "docguard", *map(str, args)],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def review(self):
        return self.run_cli(
            "review", self.baseline, "--root", self.root, "--mapping", self.mapping
        )

    def test_full_workflow_and_no_files_modified(self):
        self.source.write_text(
            "def connect(timeout=30): pass\ndef new(): pass\n", encoding="utf-8"
        )
        paths = [self.source, self.document, self.mapping, self.baseline]
        original = {path: path.read_bytes() for path in paths}
        result = self.review()
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(
            result.stdout,
            "REVIEW docs/client.md\n  client.py:close removed\n  client.py:connect modified: parameters\nUNMAPPED ADDED client.py:new\n1 documents to review, 1 unmapped additions\n",
        )
        self.assertEqual(result.stderr, "")
        self.assertEqual(original, {path: path.read_bytes() for path in paths})

    def test_no_change_and_line_only_change_return_zero(self):
        for prefix in ("", "# Comment\n"):
            with self.subTest(prefix=prefix):
                self.source.write_text(prefix + self.original, encoding="utf-8")
                result = self.review()
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, "No documentation review findings.\n")

    def test_unmapped_addition_alone_returns_one(self):
        self.source.write_text(self.original + "def new(): pass\n", encoding="utf-8")
        result = self.review()
        self.assertEqual(result.returncode, 1)
        self.assertIn("UNMAPPED ADDED client.py:new", result.stdout)
        self.assertNotIn("REVIEW", result.stdout)

    def test_mapping_errors_no_partial_report(self):
        for content in (
            "{",
            '{"schema_version":2,"documents":{}}',
            '{"schema_version":1,"documents":{"docs/client.md":["client.py:typo"]}}',
        ):
            with self.subTest(content=content):
                self.mapping.write_text(content, encoding="utf-8")
                result = self.review()
                self.assertEqual(result.returncode, 2)
                self.assertEqual(result.stdout, "")
                self.assertIn("error:", result.stderr)
                self.assertNotIn("Traceback", result.stderr)

    def test_missing_files_and_bad_source_or_snapshot(self):
        for path, bad in (
            (self.mapping, None),
            (self.document, None),
            (self.baseline, "{"),
            (self.source, "def broken(:"),
        ):
            with self.subTest(path=path):
                original = path.read_bytes()
                try:
                    if bad is None:
                        path.unlink()
                    else:
                        path.write_text(bad, encoding="utf-8")
                    result = self.review()
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertNotIn("Traceback", result.stderr)
                finally:
                    path.write_bytes(original)

    def test_help_and_required_arguments(self):
        result = self.run_cli("review", "--help")
        self.assertEqual(result.returncode, 0)
        self.assertIn("--mapping", result.stdout)
        result = self.run_cli("review", self.baseline, "--root", self.root)
        self.assertEqual(result.returncode, 2)
        self.assertIn("--mapping", result.stderr)
