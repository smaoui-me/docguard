"""Create a disposable AI demo, including a clearly labeled offline proposal."""

import argparse
import json
from pathlib import Path

from docguard.ai.proposals import suggest
from docguard.code.index import index_repository
from docguard.code.snapshots import save_snapshot


def create_demo(root: Path) -> None:
    # Refuse to overwrite an existing experiment.
    root.mkdir(parents=True, exist_ok=False)
    (root / "docs").mkdir()
    source = root / "prices.py"
    source.write_text(
        "def total(price: float) -> float:\n    return price\n", encoding="utf-8"
    )
    original = "# Pricing\n\n`total(price)` returns the price unchanged.\n\nContact the billing team for support.\n"
    (root / "docs/prices.md").write_text(original, encoding="utf-8")
    mapping = root / "docguard-map.json"
    mapping.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "documents": {
                    "docs/prices.md": ["prices.py:total"],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    baseline = root / "baseline.json"
    save_snapshot(index_repository(root), baseline)
    source.write_text(
        "def total(price: float) -> float:\n    return price * 1.2\n", encoding="utf-8"
    )

    def offline_example(model: str, context: dict[str, object]) -> object:
        return {
            "action": "revise",
            "summary": "OFFLINE DEMONSTRATION: hand-written expected edit, not AI output.",
            "content": original.replace(
                "returns the price unchanged", "returns the price multiplied by 1.2"
            ),
            "warnings": [
                "This fixture tests preview/apply plumbing, not model quality."
            ],
        }

    suggest(
        root,
        baseline,
        mapping,
        root / "offline-proposal.json",
        model="offline-demo-not-an-ai-model",
        generator=offline_example,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".docguard-demo"))
    args = parser.parse_args()
    create_demo(args.output)
    print(f"Created demo at {args.output}. No API call was made.")
    print(
        "offline-proposal.json is a hand-written fixture; use suggest for real AI output."
    )
