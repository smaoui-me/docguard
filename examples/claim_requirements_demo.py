"""Demonstrate deterministic review routing and evidence collection with no API calls."""

import argparse
import json
from pathlib import Path

from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository
from docguard.ai.git_proposals import suggest_git
from docguard.git_review import _git


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".docguard-demo-claims"))
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Choose a new demo directory")
    quote = "total(price) returns the price unchanged."
    config = AIConfig("groq", "openai/gpt-oss-120b", "")
    for available in (False, True):
        root = args.output / ("available" if available else "missing")
        base, _ = create_case_repository(
            {
                "before": "def total(price): return price\n",
                "after": "def total(price): return transform(price)\n"
                + ("def transform(price): return price * 1.2\n" if available else ""),
                "before_document": quote + "\n",
                "document": quote + "\n",
                "entity_ids": ["api.py:total"],
            },
            root,
        )
        (root / "docguard-map.json").write_text(
            json.dumps(
                {
                    "schema_version": 2,
                    "documents": {
                        "README.md": {
                            "entity_ids": ["api.py:total"],
                            "claims": [
                                {
                                    "id": "price-result",
                                    "quote": quote,
                                    "required_evidence": [
                                        "after:api.py:total",
                                        "after:api.py:transform",
                                    ],
                                }
                            ],
                        }
                    },
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _git(root, "add", "docguard-map.json")
        _git(root, "commit", "-m", "declare required evidence")
        head = _git(root, "rev-parse", "HEAD").decode().strip()
        output = root / ("requests.json" if available else "proposal.json")
        suggest_git(
            root, base, head, "docguard-map.json", output, config, dry_run=available
        )
        data = json.loads(output.read_text(encoding="utf-8"))
        gate = data["review"]["claim_requirements"]["README.md"]
        print(f"{root.name}: {gate['status']}; base={base}; head={head}")
        print(f"  Artifact: {output}")
        if available:
            assert len(data["requests"]) == 1
        else:
            assert data["proposals"][0]["proposal"]["action"] == "needs_review"
    print(
        "No API calls. 'ready' means evidence is available, not that the claim is true."
    )


if __name__ == "__main__":
    main()
