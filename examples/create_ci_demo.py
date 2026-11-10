"""Create a separate local application repository with CI and four scenario branches.

Does not create a remote, push, open PRs or copy credentials. Target must be new.
"""

import argparse
import json
import os
import re
import subprocess
from pathlib import Path

PIN = "c7c4269529381645ba813d0e4b9ee53750235eb2"


def create_demo(
    output: Path, tool_repository: str = "smaoui-me/docguard", tool_revision: str = PIN
) -> dict[str, str]:
    if output.exists() or output.is_symlink():
        raise ValueError("Choose a new demo directory")
    if not re.fullmatch(
        r"[a-zA-Z0-9][a-zA-Z0-9_.-]*/[a-zA-Z0-9][a-zA-Z0-9_.-]*", tool_repository
    ) or not re.fullmatch(r"[0-9a-f]{40}", tool_revision):
        raise ValueError("Use owner/repository and a full reviewed tool commit SHA")
    output.mkdir(parents=True)

    def write(name: str, value: str) -> None:
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8", newline="\n")

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(output), "-c", "core.hooksPath=" + os.devnull, *args],
            capture_output=True,
            text=True,
            env=dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull),
            timeout=30,
        )
        if result.returncode:
            raise ValueError("Demo Git operation failed")
        return result.stdout.strip()

    def app_test(expected: float) -> str:
        return f"import unittest\nfrom pricing import total\n\nclass PricingTest(unittest.TestCase):\n    def test_total(self):\n        self.assertAlmostEqual(total(10.1), {expected!r})\n"

    def mapping(missing: bool = False) -> str:
        return (
            json.dumps(
                {
                    "schema_version": 2,
                    "documents": {
                        "docs/prices.md": {
                            "entity_ids": ["pricing.py:total"],
                            "section": ["# Billing", "## Prices"],
                            "claims": [
                                {
                                    "id": "price-result",
                                    "quote": "total(price) returns price unchanged.",
                                    "required_evidence": [
                                        "after:pricing.py:total",
                                        "after:math.py:ceil",
                                    ],
                                }
                            ]
                            if missing
                            else [],
                        }
                    },
                },
                indent=2,
            )
            + "\n"
        )

    doc = "# Billing\n\n## Prices\n\ntotal(price) returns price unchanged.\n\n## Support\n\nContact billing@example.invalid.\n"
    write("pricing.py", "def total(price):\n    return price\n")
    write("tests/test_pricing.py", app_test(10.1))
    write("docs/prices.md", doc)
    write("docguard-map.json", mapping())
    write(
        ".gitattributes",
        "* text=auto\n*.md text eol=lf\n*.py text eol=lf\n*.json text eol=lf\n*.yml text eol=lf\n",
    )
    write(".gitignore", ".env\n.env.*\n__pycache__/\n.venv/\n*.json.lock\n")
    write(
        "README.md",
        "# DocGuard integration demo\n\nA small application for CI acceptance testing, not an independent benchmark.\n\nScenario branches: `scenario/stale`, `scenario/already-correct`, `scenario/missing-evidence`, `scenario/no-impact`. Open each against `main`. Application tests pass in all branches; documentation outcomes differ.\n\nThe missing-evidence scenario calls stdlib math.ceil and intentionally requires source unavailable in the repository. It should route to review without an AI request.\n\nRead the DocGuard `docs/ci-benchmark-demo.md` guide before enabling publication. Never add an API key to this repository.\n",
    )
    source = Path(__file__).resolve().parents[1]
    review = (source / ".github/workflows/docguard-review.yml").read_text(
        encoding="utf-8"
    )
    review = review.replace(
        "ref: ${{ steps.source.outputs.base }}",
        f"repository: {tool_repository}\n          ref: {tool_revision}",
        1,
    )
    write(".github/workflows/docguard-review.yml", review)
    repair = (source / ".github/workflows/docguard-repair.yml").read_text(
        encoding="utf-8"
    )
    repair = repair.replace(
        "ref: ${{ github.sha }}",
        f"repository: {tool_repository}\n          ref: {tool_revision}",
    )
    repair = repair.replace("default: README.md", "default: docs/prices.md")
    write(".github/workflows/docguard-repair.yml", repair)
    write(
        ".github/workflows/application.yml",
        """name: Demo application CI
on:
  push:
  pull_request:
  workflow_dispatch:
permissions:
  contents: read
jobs:
  application:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - uses: actions/checkout@v4
        with:
          persist-credentials: false
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: python -m unittest discover -s tests -v
""",
    )
    git("init", "-b", "main")
    for key, value in (
        ("user.name", "DocGuard Demo"),
        ("user.email", "demo@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        git("config", key, value)
    git("add", ".")
    git("commit", "-m", "demo: application and pinned DocGuard CI integration")
    commits = {"main": git("rev-parse", "HEAD")}
    for scenario in ("stale", "already-correct", "missing-evidence", "no-impact"):
        git("checkout", "-b", f"scenario/{scenario}", "main")
        if scenario in {"stale", "already-correct"}:
            write("pricing.py", "def total(price):\n    return price * 1.2\n")
            write("tests/test_pricing.py", app_test(12.12))
            if scenario == "already-correct":
                write(
                    "docs/prices.md",
                    doc.replace(
                        "returns price unchanged", "returns price multiplied by 1.2"
                    ),
                )
        elif scenario == "missing-evidence":
            write(
                "pricing.py",
                "import math\n\ndef total(price):\n    return math.ceil(price)\n",
            )
            write("tests/test_pricing.py", app_test(11))
            write("docguard-map.json", mapping(missing=True))
        else:
            write(
                "pricing.py",
                "# Internal implementation note; no behavior change.\n\ndef total(price):\n    return price\n",
            )
        git("add", ".")
        git("commit", "-m", f"demo: {scenario} documentation scenario")
        commits[f"scenario/{scenario}"] = git("rev-parse", "HEAD")
    git("checkout", "main")
    return commits


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".docguard-demo-ci"))
    parser.add_argument("--tool-repository", default="smaoui-me/docguard")
    parser.add_argument("--tool-revision", default=PIN)
    args = parser.parse_args()
    print(
        json.dumps(
            create_demo(args.output, args.tool_repository, args.tool_revision), indent=2
        )
    )
    print("Created local demo only. No remote, API key, push or PR was created.")


if __name__ == "__main__":
    main()
