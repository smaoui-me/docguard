import json
import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


class TestOfflineDemo(unittest.TestCase):
    def test_real_commands_create_preview_and_apply_without_a_key(self):
        repo = Path(__file__).resolve().parents[2]
        with TemporaryDirectory() as directory:
            root = Path(directory) / "demo with spaces"
            env = dict(os.environ, OPENAI_API_KEY="")

            def run(*args):
                result = subprocess.run(
                    [sys.executable, *map(str, args)],
                    cwd=repo,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                return result

            run(repo / "examples/ai_demo.py", "--output", root)
            doc = root / "docs/prices.md"
            original = doc.read_bytes()
            run(
                "-m",
                "docguard",
                "suggest",
                root / "baseline.json",
                "--root",
                root,
                "--mapping",
                root / "docguard-map.json",
                "--dry-run",
                "--output",
                root / "requests.json",
            )
            self.assertEqual(
                json.loads((root / "requests.json").read_text())["kind"],
                "docguard.ai.requests",
            )
            result = run(
                "-m",
                "docguard",
                "apply-proposal",
                root / "offline-proposal.json",
                "--root",
                root,
                "--document",
                "docs/prices.md",
                "--check",
            )
            self.assertIn("multiplied by 1.2", result.stdout)
            self.assertEqual(doc.read_bytes(), original)
            run(
                "-m",
                "docguard",
                "apply-proposal",
                root / "offline-proposal.json",
                "--root",
                root,
                "--document",
                "docs/prices.md",
            )
            self.assertIn("multiplied by 1.2", doc.read_text(encoding="utf-8"))
