"""Run a real Git section-repair demo; offline fixture unless --live (one API call)."""

import argparse
import json
from pathlib import Path
from time import monotonic

from docguard.ai.config import AIConfig, load_config
from docguard.ai.dataset import create_case_repository
from docguard.ai.files import ProposalError, write_new_json
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.provider import generate
from docguard.docs.sections import select_section
from docguard.git_review import _git
from docguard.publication import publish_proposal


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".docguard-demo-sections"))
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        parser.error("Choose a new demo directory")
    root = args.output / "repo"
    original = b"# Billing\r\nUnrelated intro.\n## Prices\r\n`total(price)` returns price unchanged.\r\n\r\n## Support\nContact billing. \t\n"
    base, _ = create_case_repository(
        {
            "before": "def total(price): return price\n",
            "after": "def total(price): return price * 1.2\n",
            "before_document": original.decode(),
            "document": original.decode(),
            "entity_ids": ["api.py:total"],
        },
        root,
    )
    (root / "README.md").write_bytes(original)
    (root / "docguard-map.json").write_text(
        json.dumps(
            {
                "schema_version": 2,
                "documents": {
                    "README.md": {
                        "entity_ids": ["api.py:total"],
                        "claims": [],
                        "section": ["# Billing", "## Prices"],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    _git(root, "-c", "core.autocrlf=false", "add", "README.md", "docguard-map.json")
    _git(root, "commit", "-m", "map prices section")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    artifact = args.output / "proposal.json"
    config = load_config() if args.live else AIConfig("groq", "offline-fixture", "")
    usage: list[dict[str, int]] = []

    def generator(model: str, context: dict[str, object]) -> object:
        if args.live:
            return generate(
                model,
                context,
                provider=config.provider,
                api_key=config.api_key,
                usage_sink=usage.append,
            )
        return {
            "action": "revise",
            "summary": "Document multiplication",
            "content": "## Prices\n`total(price)` returns price multiplied by 1.2.\n\n",
            "warnings": [],
            "evidence_ids": ["after:api.py:total"],
        }

    started = monotonic()
    suggest_git(
        root, base, head, "docguard-map.json", artifact, config, generator=generator
    )
    generation_seconds = round(monotonic() - started, 3)
    checks = {
        "generation_preserves_document": (root / "README.md").read_bytes() == original
    }
    print(apply_git_proposal(artifact, root, "README.md", check=True))
    checks["preview_preserves_document"] = (root / "README.md").read_bytes() == original
    plan = publish_proposal(artifact, root, "README.md", "example/docguard-demo", 1)
    write_new_json(args.output / "publication-preview.json", plan)
    apply_git_proposal(artifact, root, "README.md")
    actual = (root / "README.md").read_bytes()
    old_section = select_section(original, ("# Billing", "## Prices"))
    new_section = select_section(actual, ("# Billing", "## Prices"))
    checks["outside_bytes_identical"] = (
        original[: old_section.start] == actual[: new_section.start]
        and original[old_section.end :] == actual[new_section.end :]
    )
    checks["multiplier_mentioned"] = "1.2" in new_section.text(actual)
    checks["stale_reapply_rejected"] = False
    try:
        apply_git_proposal(artifact, root, "README.md")
    except ProposalError:
        checks["stale_reapply_rejected"] = True
    result = {
        "mode": "live" if args.live else "offline-fixture",
        "provider": config.provider,
        "model": config.model,
        "api_requests": int(args.live),
        "generation_seconds": generation_seconds,
        "token_usage": usage or None,
        "checks": checks,
        "passed": all(checks.values()),
        "github_writes": 0,
    }
    write_new_json(args.output / "evaluation.json", result)
    print(json.dumps(result, indent=2))
    print(f"Inspect {artifact} and {root / 'README.md'}. No GitHub writes occurred.")
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
