import io
import json
import os
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from docguard.ai.files import ProposalError
from docguard.ai.proposals import (
    apply_proposal,
    load_proposals,
    prepare_documents,
    suggest,
)
from docguard.cli import main
from docguard.code.index import index_repository
from docguard.code.snapshots import save_snapshot


class TestAIProposals(unittest.TestCase):
    def setUp(self):
        environment = patch.dict(
            os.environ,
            {"DOCGUARD_AI_PROVIDER": "openai", "DOCGUARD_MODEL": "gpt-4.1-mini"},
        )
        environment.start()
        self.addCleanup(environment.stop)
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "demo repo"
        self.root.mkdir()
        self.source = self.root / "price.py"
        self.source.write_text(
            "def total(price):\n    return price\n", encoding="utf-8"
        )
        (self.root / "docs").mkdir()
        self.doc = self.root / "docs/prices.md"
        self.original = (
            "# Prices\n\nReturns the price unchanged.\n\nContact support for help.\n"
        )
        self.doc.write_text(self.original, encoding="utf-8")
        self.mapping = self.root / "mapping.json"
        self.mapping.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "documents": {
                        "docs/prices.md": ["price.py:total"],
                    },
                }
            ),
            encoding="utf-8",
        )
        self.baseline = self.root / "baseline.json"
        save_snapshot(index_repository(self.root), self.baseline)
        self.source.write_text(
            "def total(price):\n    return price * 1.2\n", encoding="utf-8"
        )
        self.output = self.root / "proposals.json"
        self.updated = self.original.replace(
            "Returns the price unchanged.", "Returns the price multiplied by 1.2."
        )
        self.generator = Mock(
            return_value={
                "action": "revise",
                "summary": "Document the multiplier.",
                "content": self.updated,
                "warnings": [],
            }
        )

    def generate(self, **kwargs):
        return suggest(
            self.root,
            self.baseline,
            self.mapping,
            self.output,
            generator=self.generator,
            **kwargs,
        )

    def test_complete_generate_preview_apply_workflow_preserves_source_and_baseline(
        self,
    ):
        source, baseline = self.source.read_bytes(), self.baseline.read_bytes()
        self.assertEqual(self.generate(), 1)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.original)
        context = self.generator.call_args.args[1]
        self.assertIn("price * 1.2", context["entities"][0]["current_source"])
        self.assertEqual(context["reasons"][0]["changed_fields"], ("body",))
        self.assertIsNotNone(context["entities"][0]["before"])
        diff = apply_proposal(self.output, self.root, "docs/prices.md", check=True)
        self.assertIn("-Returns the price unchanged.", diff)
        self.assertIn("+Returns the price multiplied by 1.2.", diff)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.original)
        apply_proposal(self.output, self.root, "docs/prices.md")
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.updated)
        self.assertEqual(self.source.read_bytes(), source)
        self.assertEqual(self.baseline.read_bytes(), baseline)
        with self.assertRaisesRegex(ProposalError, "Document changed"):
            apply_proposal(self.output, self.root, "docs/prices.md")

    def test_dry_run_contains_exact_request_and_never_calls_provider(self):
        self.generate(dry_run=True)
        self.generator.assert_not_called()
        data = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(data["kind"], "docguard.ai.requests")
        self.assertFalse(data["requests"][0]["store"])
        self.assertTrue(data["requests"][0]["text"]["format"]["strict"])
        self.assertEqual(
            self.doc.read_bytes().decode("utf-8"),
            json.loads(data["requests"][0]["input"])["document_text"],
        )
        with self.assertRaises(ProposalError):
            apply_proposal(self.output, self.root, "docs/prices.md")

    def test_no_findings_makes_no_api_calls(self):
        save_snapshot(index_repository(self.root), self.baseline)
        self.assertEqual(self.generate(), 0)
        self.generator.assert_not_called()
        self.assertEqual(load_proposals(self.output)[1], ())

    def test_refuses_stale_document_and_source_including_global_changes(self):
        self.generate()
        self.doc.write_text("Human edit", encoding="utf-8")
        with self.assertRaisesRegex(ProposalError, "Document changed"):
            apply_proposal(self.output, self.root, "docs/prices.md")
        self.doc.write_text(self.original, encoding="utf-8")
        with self.source.open("a", encoding="utf-8") as stream:
            stream.write("GLOBAL_RATE = 3\n")
        with self.assertRaisesRegex(ProposalError, "Source files changed"):
            apply_proposal(self.output, self.root, "docs/prices.md")

    def test_changes_during_generation_abort_without_artifact(self):
        def mutate(model, context):
            self.doc.write_text("Concurrent edit", encoding="utf-8")
            return {
                "action": "revise",
                "summary": "Edit",
                "content": self.updated,
                "warnings": [],
            }

        self.generator.side_effect = mutate
        with self.assertRaisesRegex(ProposalError, "Document changed"):
            self.generate()
        self.assertFalse(self.output.exists())

    def test_provider_failure_or_invalid_decision_leaves_documents_unchanged(self):
        cases = [
            None,
            {},
            {"action": "delete", "summary": "x", "content": None, "warnings": []},
            {"action": "revise", "summary": "x", "content": "", "warnings": []},
            {
                "action": "revise",
                "summary": "x",
                "content": "a" * 60001,
                "warnings": [],
            },
            {
                "action": "unchanged",
                "summary": "x",
                "content": "Unexpected",
                "warnings": [],
            },
            {"action": "revise", "summary": "", "content": "x", "warnings": []},
            {"action": "revise", "summary": "x", "content": "x", "warnings": [1]},
            {
                "action": "revise",
                "summary": "x",
                "content": "x",
                "warnings": [],
                "document": "other.md",
            },
        ]
        for value in cases:
            with self.subTest(value=str(value)[:70]):
                self.generator.return_value = value
                with self.assertRaises(ProposalError):
                    self.generate()
                self.assertFalse(self.output.exists())
                self.assertEqual(self.doc.read_text(encoding="utf-8"), self.original)
        self.generator.side_effect = ProposalError("API unavailable")
        with self.assertRaises(ProposalError):
            self.generate()
        self.assertFalse(self.output.exists())

    def test_unchanged_and_needs_review_are_not_applicable(self):
        for action in ("unchanged", "needs_review"):
            with self.subTest(action=action):
                self.generator.return_value = {
                    "action": action,
                    "summary": "No supported edit",
                    "content": None,
                    "warnings": ["Missing context"],
                }
                self.generate()
                with self.assertRaisesRegex(
                    ProposalError, "not an applicable revision"
                ):
                    apply_proposal(self.output, self.root, "docs/prices.md")
                self.output.unlink()

    def test_identical_revision_is_normalized_to_unchanged(self):
        self.generator.return_value["content"] = self.original
        self.generate()
        self.assertEqual(load_proposals(self.output)[1][0].action, "unchanged")

    def test_limits_existing_output_and_selection_fail_before_any_api_call(self):
        self.output.write_text("Keep me", encoding="utf-8")
        with self.assertRaises(ProposalError):
            self.generate()
        self.assertEqual(self.output.read_text(), "Keep me")
        self.output.unlink()
        for kwargs in (
            {"max_documents": 0},
            {"max_documents": 21},
            {"selected": ["missing.md"]},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ProposalError):
                self.generate(**kwargs)
        self.doc.write_text("a" * 40001, encoding="utf-8")
        with self.assertRaisesRegex(ProposalError, "Context"):
            self.generate()
        self.generator.assert_not_called()

    def test_multiple_documents_are_preflighted_and_can_be_selected(self):
        data = json.loads(self.mapping.read_text())
        for name in ("b.md", "c.md", "d.md"):
            (self.root / name).write_text("Price docs", encoding="utf-8")
            data["documents"][name] = ["price.py:total"]
        self.mapping.write_text(json.dumps(data), encoding="utf-8")
        with self.assertRaisesRegex(ProposalError, "exceed max-documents"):
            self.generate()
        self.generator.assert_not_called()
        self.generate(selected=["docs/prices.md"])
        self.assertEqual(self.generator.call_count, 1)

    def test_removed_entities_use_before_metadata_without_fake_current_source(self):
        self.source.write_text("", encoding="utf-8")
        _, contexts = prepare_documents(self.root, self.baseline, self.mapping)
        entity = contexts[0].context["entities"][0]
        self.assertIsNotNone(entity["before"])
        self.assertIsNone(entity["after"])
        self.assertIsNone(entity["current_source"])

    def test_unicode_and_crlf_preserved(self):
        original = "# CafÃ©\r\nReturns price unchanged.\r\n"
        self.doc.write_bytes(original.encode("utf-8"))
        self.generator.return_value["content"] = "# CafÃ©\nReturns price times 1.2.\n"
        self.generate()
        apply_proposal(self.output, self.root, "docs/prices.md")
        self.assertEqual(
            self.doc.read_bytes(),
            "# CafÃ©\r\nReturns price times 1.2.\r\n".encode("utf-8"),
        )

    def test_malicious_paths_hashes_and_duplicate_proposals_are_rejected(self):
        self.generate()
        baseline = json.loads(self.output.read_text(encoding="utf-8"))
        for name in (
            "../outside.md",
            "/outside.md",
            "C:/outside.md",
            ".git/config.txt",
            "price.py",
        ):
            with self.subTest(name=name):
                data = json.loads(json.dumps(baseline))
                data["proposals"][0]["document"] = name
                self.output.write_text(json.dumps(data), encoding="utf-8")
                with self.assertRaises(ProposalError):
                    apply_proposal(self.output, self.root, name)
        for change in ("hash", "duplicate", "version"):
            data = json.loads(json.dumps(baseline))
            if change == "hash":
                data["proposals"][0]["original_sha256"] = "0" * 64
            elif change == "duplicate":
                data["proposals"].append(data["proposals"][0])
            else:
                data["schema_version"] = True
            self.output.write_text(json.dumps(data), encoding="utf-8")
            with self.subTest(change=change), self.assertRaises(ProposalError):
                load_proposals(self.output)

    def test_failed_replace_preserves_document_and_cleans_temporary_file(self):
        self.generate()
        with patch(
            "docguard.ai.proposals.os.replace", side_effect=PermissionError("denied")
        ):
            with self.assertRaises(PermissionError):
                apply_proposal(self.output, self.root, "docs/prices.md")
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.original)
        self.assertEqual(list(self.doc.parent.glob(".docguard-*.tmp")), [])

    def test_cli_dry_run_and_preview_apply(self):
        args = [
            "suggest",
            str(self.baseline),
            "--root",
            str(self.root),
            "--mapping",
            str(self.mapping),
            "--output",
            str(self.output),
            "--dry-run",
        ]
        stdout, stderr = io.StringIO(), io.StringIO()
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            self.assertEqual(main(args), 0)
        self.assertIn("no API calls", stdout.getvalue())
        self.output.unlink()
        self.generate()
        args = [
            "apply-proposal",
            str(self.output),
            "--root",
            str(self.root),
            "--document",
            "docs/prices.md",
        ]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(main(args + ["--check"]), 0)
            self.assertEqual(self.doc.read_text(encoding="utf-8"), self.original)
            self.assertEqual(main(args), 0)
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.updated)

    def test_cli_generation_through_openai_adapter_with_fake_http(self):
        envelope = {
            "status": "completed",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(self.generator.return_value),
                        },
                    ],
                }
            ],
        }
        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}),
            patch("docguard.ai.provider.build_opener") as opener,
            redirect_stdout(io.StringIO()),
        ):
            opener.return_value.open.return_value.__enter__.return_value.read.return_value = json.dumps(
                envelope
            ).encode()
            result = main(
                [
                    "suggest",
                    str(self.baseline),
                    "--root",
                    str(self.root),
                    "--mapping",
                    str(self.mapping),
                    "--output",
                    str(self.output),
                ]
            )
        self.assertEqual(result, 0)
        self.assertEqual(load_proposals(self.output)[1][0].action, "revise")
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.original)

    def test_failure_in_second_document_leaves_no_partial_proposal(self):
        (self.root / "other.md").write_text("Other docs", encoding="utf-8")
        data = json.loads(self.mapping.read_text())
        data["documents"]["other.md"] = ["price.py:total"]
        self.mapping.write_text(json.dumps(data), encoding="utf-8")
        self.generator.side_effect = [
            self.generator.return_value,
            ProposalError("second request failed"),
        ]
        with self.assertRaises(ProposalError):
            self.generate()
        self.assertEqual(self.generator.call_count, 2)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.doc.read_text(encoding="utf-8"), self.original)

    def test_source_change_during_generation_prevents_saving(self):
        decision = self.generator.return_value

        def mutate(model, context):
            self.source.write_text("def changed(): pass\n", encoding="utf-8")
            return decision

        self.generator.side_effect = mutate
        with self.assertRaisesRegex(ProposalError, "Source changed"):
            self.generate()
        self.assertFalse(self.output.exists())

    def test_non_utf8_document_and_unsupported_extension_fail_preflight(self):
        self.doc.write_bytes(b"\xff")
        with self.assertRaises(UnicodeDecodeError):
            self.generate()
        (self.root / "docs/config.yml").write_text("key: value", encoding="utf-8")
        self.mapping.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "documents": {
                        "docs/config.yml": ["price.py:total"],
                    },
                }
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(ProposalError, "support only"):
            self.generate()
        self.generator.assert_not_called()

    def test_symlink_document_is_rejected(self):
        real = self.doc.parent / "real.md"
        self.doc.rename(real)
        try:
            self.doc.symlink_to(real)
        except OSError as error:
            self.skipTest(f"Symlinks unavailable: {error}")
        with self.assertRaisesRegex(ProposalError, "Symlink"):
            self.generate()

    def test_missing_key_cli_error_has_no_traceback_or_artifact(self):
        errors = io.StringIO()
        with patch.dict(os.environ, {"OPENAI_API_KEY": ""}), redirect_stderr(errors):
            result = main(
                [
                    "suggest",
                    str(self.baseline),
                    "--root",
                    str(self.root),
                    "--mapping",
                    str(self.mapping),
                    "--output",
                    str(self.output),
                ]
            )
        self.assertEqual(result, 2)
        self.assertIn("OPENAI_API_KEY", errors.getvalue())
        self.assertNotIn("Traceback", errors.getvalue())
        self.assertFalse(self.output.exists())
