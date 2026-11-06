"""Compare mapped and automatically expanded evidence without calling an API."""

import argparse
import json
from pathlib import Path

from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository
from docguard.ai.git_proposals import suggest_git


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".docguard-demo-evidence"))
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Output exists; choose a new demo directory")
    case = {
        "before": "def total(price): return price\ndef transform(price): return price\n",
        "after": "def total(price): return transform(price)\ndef transform(price): return price * 1.2\n",
        "before_document": "# Prices\n\ntotal(price) returns the price unchanged.\n",
        "document": "# Prices\n\ntotal(price) returns the price unchanged.\n",
        "entity_ids": ["api.py:total"],
    }
    base, head = create_case_repository(case, args.output)
    config = AIConfig("groq", "openai/gpt-oss-120b", "")
    for policy in ("mapped", "direct"):
        output = args.output / f"{policy}-requests.json"
        suggest_git(
            args.output,
            base,
            head,
            "docguard-map.json",
            output,
            config,
            dry_run=True,
            evidence_policy=policy,
        )
        data = json.loads(output.read_text(encoding="utf-8"))
        context = json.loads(data["requests"][0]["messages"][1]["content"])
        print(f"{policy}: {[entry['id'] for entry in context['evidence']]}")
    print(f"Requests saved in {args.output}. No API calls; source was not executed.")


if __name__ == "__main__":
    main()
