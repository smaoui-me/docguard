import json
import os
import shutil
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.git_review import GitReviewError, review_git


@unittest.skipUnless(shutil.which("git"), "Git must be installed")
class TestGitReview(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "demo repo"
        self.root.mkdir()
        self.env = dict(
            os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull
        )
        self.git("init", "-b", "main")
        self.git("config", "user.name", "DocGuard Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.source = self.root / "client.py"
        self.original = "def connect(timeout=10): pass\ndef close(): pass\n"
        self.source.write_text(self.original, encoding="utf-8")
        (self.root / "docs").mkdir()
        (self.root / "docs/client.md").write_text("Client docs", encoding="utf-8")
        self.mapping = self.root / "docguard-map.json"
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
        self.base = self.commit("baseline")

    def git(self, *args):
        result = subprocess.run(
            ["git", "-C", str(self.root), *args],
            env=self.env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout.strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("commit", "-m", message)
        return self.git("rev-parse", "HEAD")

    def review(self, base=None, head="HEAD"):
        return review_git(self.root, base or self.base, head, "docguard-map.json")

    def cli(self, *extra):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "docguard",
                "review-git",
                "--root",
                str(self.root),
                "--base",
                self.base,
                "--mapping",
                "docguard-map.json",
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_modification_removal_addition_and_json_provenance(self):
        self.source.write_text(
            "def connect(timeout=30): pass\ndef added(): pass\n", encoding="utf-8"
        )
        head = self.commit("change API")
        result = self.cli("--format", "json")
        self.assertEqual(result.returncode, 1, result.stderr)
        document = json.loads(result.stdout)
        self.assertEqual(document["schema_version"], 2)
        self.assertEqual(
            document["git"], {"base": self.base, "head": head, "merge_base": self.base}
        )
        self.assertEqual(
            document["counts"],
            {"documents": 1, "unmapped_added": 1, "removed_links": 0},
        )
        self.assertEqual(
            document["documents"][0]["reasons"],
            [
                {
                    "entity_id": "client.py:close",
                    "change": "removed",
                    "changed_fields": [],
                },
                {
                    "entity_id": "client.py:connect",
                    "change": "modified",
                    "changed_fields": ["parameters"],
                },
            ],
        )
        self.assertEqual(document["unmapped_added"], ["client.py:added"])

    def test_merge_base_excludes_target_branch_only_changes(self):
        self.git("checkout", "-b", "feature")
        self.source.write_text(self.original.replace("10", "20"), encoding="utf-8")
        head = self.commit("feature")
        self.git("checkout", "main")
        self.source.write_text(
            self.original.replace("close()", "close(force=False)"), encoding="utf-8"
        )
        (self.root / "target_only.py").write_text(
            "def target_only(): pass\n", encoding="utf-8"
        )
        target = self.commit("advance target")
        result = self.review(base=target, head=head)
        self.assertEqual(result.merge_base, self.base)
        self.assertEqual(len(result.report.documents), 1)
        self.assertEqual(result.report.unmapped_added, ())
        self.assertEqual(
            result.report.documents[0].reasons[0].entity_id, "client.py:connect"
        )
        self.assertEqual(self.git("branch", "--show-current"), "main")

    def test_line_only_and_no_changes(self):
        self.assertEqual(self.review().report.documents, ())
        self.source.write_text("# Comment\n" + self.original, encoding="utf-8")
        self.commit("line shift")
        self.assertEqual(self.review().report.documents, ())
        self.assertEqual(self.cli().returncode, 0)

    def test_dirty_and_untracked_files_ignored_without_changing_worktree(self):
        self.source.write_text("invalid syntax !", encoding="utf-8")
        (self.root / "untracked.py").write_text("also invalid !", encoding="utf-8")
        self.git("add", "client.py")
        before = self.git("status", "--porcelain")
        result = self.review()
        self.assertEqual(result.report.documents, ())
        self.assertEqual(result.report.unmapped_added, ())
        self.assertEqual(self.git("status", "--porcelain"), before)
        self.assertEqual(self.source.read_text(encoding="utf-8"), "invalid syntax !")

    def test_advisory_keeps_errors_failing(self):
        self.source.write_text(self.original.replace("10", "30"), encoding="utf-8")
        self.commit("change")
        self.assertEqual(self.cli("--advisory").returncode, 0)
        self.source.write_text("def invalid(:", encoding="utf-8")
        self.commit("broken")
        result = self.cli("--advisory", "--format", "json")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("client.py:1:", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_invalid_mapping_and_missing_committed_mapping(self):
        self.mapping.write_text('{"schema_version":2,"documents":{}}', encoding="utf-8")
        self.commit("invalid mapping")
        self.assertEqual(self.cli("--advisory").returncode, 2)
        self.mapping.unlink()
        self.commit("remove mapping")
        self.assertEqual(self.cli().returncode, 2)

    def test_invalid_revision_and_non_repository(self):
        for revision in ("missing-branch", "--help"):
            with self.subTest(revision=revision), self.assertRaises(GitReviewError):
                self.review(base=revision)
        with self.assertRaises(GitReviewError):
            review_git(self.root.parent, "HEAD", "HEAD", "docguard-map.json")

    def test_unrelated_histories_fail(self):
        self.git("checkout", "--orphan", "unrelated")
        self.commit("unrelated root")
        with self.assertRaises(GitReviewError):
            self.review()

    def test_directory_inside_parent_repository_is_not_a_repository_root(self):
        # Git discovers self.root from this ordinary directory. Reject that
        # discovery before exporting the parent's source or reading a mapping.
        nested = self.root / "ordinary directory"
        nested.mkdir()
        with self.assertRaisesRegex(GitReviewError, "Expected a Git repository root"):
            review_git(nested, "HEAD", "HEAD", "missing-map.json")

    def test_linked_worktree_is_a_valid_repository_root(self):
        worktree = self.root.parent / "linked worktree"
        self.git("worktree", "add", "--detach", str(worktree), self.base)
        result = review_git(worktree, self.base, "HEAD", "docguard-map.json")
        self.assertEqual(result.report.documents, ())
        self.assertEqual(result.report.unmapped_added, ())

    def test_mapping_removal_cannot_silently_suppress_findings(self):
        self.source.write_text(self.original.replace("10", "30"), encoding="utf-8")
        self.mapping.write_text('{"schema_version":1,"documents":{}}', encoding="utf-8")
        self.commit("change mapping and code")
        report = self.review().report
        self.assertEqual(report.documents, ())
        self.assertEqual(
            [link.entity_id for link in report.removed_links],
            ["client.py:close", "client.py:connect"],
        )
        result = self.cli("--format", "json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"]["removed_links"], 2)
        self.assertEqual(self.cli("--advisory").returncode, 0)

    def test_link_removal_with_unchanged_code_reports_in_text_and_summary(self):
        data = json.loads(self.mapping.read_text(encoding="utf-8"))
        data["documents"]["docs/client.md"].remove("client.py:connect")
        self.mapping.write_text(json.dumps(data), encoding="utf-8")
        self.commit("remove one link")
        summary = self.root.parent / "removed-links.md"
        result = self.cli("--summary", str(summary))
        self.assertEqual(result.returncode, 1, result.stderr)
        expected = "REMOVED LINK docs/client.md -> client.py:connect"
        self.assertIn(expected, result.stdout)
        self.assertIn(
            "REMOVED LINK docs/client.md -&gt; client.py:connect",
            summary.read_text(encoding="utf-8"),
        )
        self.assertEqual(self.review().report.documents, ())

    def test_deleted_document_and_its_links_are_reported(self):
        (self.root / "docs/client.md").unlink()
        self.mapping.write_text('{"schema_version":1,"documents":{}}', encoding="utf-8")
        self.commit("remove documentation")
        report = self.review().report
        self.assertEqual(len(report.removed_links), 2)
        self.assertTrue(
            all(link.document == "docs/client.md" for link in report.removed_links)
        )

    def test_new_mapping_without_baseline_mapping_is_supported(self):
        original = self.mapping.read_bytes()
        self.mapping.unlink()
        base = self.commit("before mapping introduced")
        self.mapping.write_bytes(original)
        self.source.write_text(self.original.replace("10", "30"), encoding="utf-8")
        self.commit("introduce mapping")
        report = self.review(base=base).report
        self.assertEqual(report.removed_links, ())
        self.assertEqual(len(report.documents), 1)

    def test_invalid_baseline_mapping_fails_explicitly(self):
        original = self.mapping.read_bytes()
        self.mapping.write_text("{", encoding="utf-8")
        base = self.commit("invalid baseline mapping")
        self.mapping.write_bytes(original)
        self.commit("repair mapping")
        with self.assertRaisesRegex(ValueError, "Invalid mapping"):
            self.review(base=base)

    def test_mapping_changes_only_on_target_branch_are_not_reported(self):
        self.git("checkout", "-b", "feature")
        self.source.write_text("# Comment\n" + self.original, encoding="utf-8")
        head = self.commit("feature comment")
        self.git("checkout", "main")
        (self.root / "docs/extra.md").write_text("Extra docs", encoding="utf-8")
        data = json.loads(self.mapping.read_text(encoding="utf-8"))
        data["documents"]["docs/extra.md"] = ["client.py:connect"]
        self.mapping.write_text(json.dumps(data), encoding="utf-8")
        target = self.commit("target adds mapping")
        self.assertFalse(self.review(base=target, head=head).report.has_findings)

    def test_source_is_never_executed_and_export_ignore_does_not_hide_files(self):
        marker = self.root / "executed.txt"
        self.source.write_text(
            f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
            + self.original,
            encoding="utf-8",
        )
        (self.root / ".gitattributes").write_text(
            "client.py export-ignore\n", encoding="utf-8"
        )
        self.commit("inert source")
        self.assertEqual(self.review().report.documents, ())
        self.assertFalse(marker.exists())

    def test_summary_and_text_agree(self):
        self.source.write_text(self.original.replace("10", "30"), encoding="utf-8")
        self.commit("change")
        summary = self.root.parent / "summary.md"
        result = self.cli("--summary", str(summary))
        self.assertEqual(result.returncode, 1)
        self.assertIn("REVIEW docs/client.md", result.stdout)
        self.assertIn("REVIEW docs/client.md", summary.read_text(encoding="utf-8"))

    def test_mapping_path_cannot_escape_tree(self):
        for mapping in ("../map.json", "/map.json", "C:/map.json", "a\\map.json"):
            with self.subTest(mapping=mapping), self.assertRaises(GitReviewError):
                review_git(self.root, self.base, "HEAD", mapping)

    def test_submodules_fail_explicitly(self):
        self.git("update-index", "--add", "--cacheinfo", f"160000,{self.base},vendor")
        self.git("commit", "-m", "add gitlink")
        with self.assertRaisesRegex(GitReviewError, "Submodules"):
            self.review()

    def test_shallow_clone_missing_history_fails_explicitly(self):
        self.source.write_text(self.original.replace("10", "30"), encoding="utf-8")
        self.commit("change")
        clone = self.root.parent / "shallow"
        self.git("clone", "--depth", "1", self.root.as_uri(), str(clone))
        with self.assertRaises(GitReviewError):
            review_git(clone, self.base, "HEAD", "docguard-map.json")
