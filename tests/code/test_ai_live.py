"""Opt-in paid model smoke test. Never enabled by the normal test workflow."""

import os
import unittest
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.ai.config import load_config
from docguard.ai.proposals import load_proposals, suggest
from docguard.ai.provider import generate
from docguard.code.index import index_repository
from docguard.code.snapshots import save_snapshot


@unittest.skipUnless(
    os.environ.get("DOCGUARD_RUN_LIVE_AI") == "1",
    "Live API test is opt-in: set DOCGUARD_RUN_LIVE_AI=1 and configure provider credentials (incurs API cost)",
)
class TestLiveAI(unittest.TestCase):
    def test_model_proposes_supported_edit_preserving_unrelated_prose(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "prices.py"
            source.write_text("def total(price):\n    return price\n", encoding="utf-8")
            original = "# Prices\n\n`total(price)` returns price unchanged.\n\nContact the billing team for support.\n"
            doc = root / "README.md"
            doc.write_text(original, encoding="utf-8")
            mapping = root / "mapping.json"
            mapping.write_text(
                '{"schema_version":1,"documents":{"README.md":["prices.py:total"]}}',
                encoding="utf-8",
            )
            baseline = root / "baseline.json"
            save_snapshot(index_repository(root), baseline)
            source.write_text(
                "def total(price):\n    return price * 1.2\n", encoding="utf-8"
            )
            output = root / "proposals.json"
            config = load_config()
            suggest(
                root,
                baseline,
                mapping,
                output,
                model=config.model,
                provider=config.provider,
                generator=partial(
                    generate, provider=config.provider, api_key=config.api_key
                ),
            )
            _, proposals = load_proposals(output)
            self.assertEqual(len(proposals), 1)
            proposal = proposals[0]
            self.assertEqual(proposal.action, "revise", proposal.summary)
            self.assertIn("1.2", proposal.content)
            self.assertIn("Contact the billing team for support.", proposal.content)
            self.assertEqual(doc.read_text(encoding="utf-8"), original)
