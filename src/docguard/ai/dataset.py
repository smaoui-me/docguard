"""Versioned, authored Git cases. Gold labels never enter provider requests."""

import json
import os
import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import cast

from docguard.ai.config import AIConfig
from docguard.ai.files import ProposalError, digest, read_bytes, write_new_json
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.provider import (
    GIT_PROMPT_VERSION,
    PROMPT_VERSION,
    ProviderError,
    generate,
)


def load_cases(path: Path) -> list[dict[str, object]]:
    data = tomllib.loads(read_bytes(path, 2_000_000).decode("utf-8"))
    if (
        type(data.get("schema_version")) is not int
        or data.get("schema_version") != 1
        or not isinstance(data.get("cases"), list)
        or not all(isinstance(case, dict) for case in data["cases"])
    ):
        raise ProposalError("Expected version 1 evaluation dataset")
    cases: list[dict[str, object]] = data["cases"]
    names: set[str] = set()
    for case in cases:
        for key in (
            "id",
            "category",
            "split",
            "difficulty",
            "provenance",
            "review_status",
            "rationale",
            "before",
            "after",
            "before_document",
            "document",
            "action",
            "replacement",
        ):
            if not isinstance(case.get(key), str):
                raise ProposalError(f"Dataset case requires string field {key}")
        name = str(case["id"])
        if name in names or not re.fullmatch(r"[a-z0-9_]+", name):
            raise ProposalError("Dataset IDs must be unique lowercase names")
        names.add(name)
        if case["split"] not in {"development", "reserved"} or case["action"] not in {
            "revise",
            "unchanged",
            "needs_review",
        }:
            raise ProposalError("Invalid case split or action")
        if type(case.get("expect_request")) is not bool:
            raise ProposalError("Dataset case requires expect_request boolean")
        for key in (
            "entity_ids",
            "required_patterns",
            "forbidden_patterns",
            "preserve",
        ):
            values = case.get(key)
            if not isinstance(values, list) or not all(
                isinstance(item, str) for item in values
            ):
                raise ProposalError(f"Dataset case requires string array {key}")
            if key.endswith("patterns"):
                for pattern in values:
                    re.compile(pattern)
        if not case["entity_ids"] or (
            case["action"] == "revise" and not str(case["replacement"]).strip()
        ):
            raise ProposalError(
                "Case requires entity IDs and a nonempty revision fixture"
            )
    return cases


def create_case_repository(case: dict[str, object], root: Path) -> tuple[str, str]:
    """Create a disposable real Git repository; fixture source is never executed."""
    root.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

    def git(*args: str) -> str:
        result = subprocess.run(
            ["git", "-C", str(root), "-c", "core.hooksPath=" + os.devnull, *args],
            env=env,
            capture_output=True,
            timeout=30,
        )
        if result.returncode:
            raise ProposalError("Unable to construct evaluation Git repository")
        return result.stdout.decode().strip()

    git("init", "-b", "main")
    for key, value in (
        ("user.name", "DocGuard Evaluation"),
        ("user.email", "evaluation@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        git("config", key, value)
    source, doc = root / "api.py", root / "README.md"
    (root / "docguard-map.json").write_text(
        json.dumps(
            {"schema_version": 1, "documents": {"README.md": case["entity_ids"]}}
        ),
        encoding="utf-8",
    )
    source.write_text(str(case["before"]), encoding="utf-8", newline="\n")
    doc.write_text(str(case["before_document"]), encoding="utf-8", newline="\n")
    git("add", ".")
    git("commit", "-m", "baseline")
    base = git("rev-parse", "HEAD")
    source.write_text(str(case["after"]), encoding="utf-8", newline="\n")
    doc.write_text(str(case["document"]), encoding="utf-8", newline="\n")
    git("add", ".")
    git("commit", "--allow-empty", "-m", "proposed change")
    return base, git("rev-parse", "HEAD")


def evaluate_dataset(
    config: AIConfig,
    dataset: Path,
    output: Path,
    *,
    split: str = "development",
    selected: Sequence[str] = (),
    live: bool = False,
    max_requests: int = 3,
    generator: Callable[[str, dict[str, object]], object] | None = None,
) -> dict[str, object]:
    if (
        output.exists()
        or output.is_symlink()
        or output.suffix.lower() != ".json"
        or not output.parent.is_dir()
    ):
        raise ProposalError("Evaluation output must be a new .json file")
    if split not in {"development", "reserved", "all"} or not 1 <= max_requests <= 100:
        raise ProposalError("Invalid split or request budget (1-100)")
    all_cases = load_cases(dataset)
    cases = [case for case in all_cases if split == "all" or case["split"] == split]
    if set(selected) - {str(case["id"]) for case in cases}:
        raise ProposalError("Unknown case or case outside selected split")
    cases = [case for case in cases if not selected or case["id"] in selected]
    if not cases:
        raise ProposalError("No dataset cases selected")
    if live and (len(cases) > max_requests or not config.api_key.strip()):
        raise ProposalError(
            "Live evaluation needs credentials and a request budget at least as large as the selected case count"
        )
    results: list[dict[str, object]] = []
    requests = 0
    for case in cases:
        started = monotonic()
        row: dict[str, object] = {
            "case": case["id"],
            "category": case["category"],
            "split": case["split"],
            "expected_action": case["action"],
            "provenance": case["provenance"],
            "review_status": case["review_status"],
            "difficulty": case["difficulty"],
        }
        with TemporaryDirectory(prefix="docguard-dataset-") as directory:
            root = Path(directory) / "repo"
            before, head = create_case_repository(case, root)
            artifact = Path(directory) / "proposal.json"
            original = (root / "README.md").read_bytes()
            called = 0

            def produce(model: str, context: dict[str, object]) -> object:
                nonlocal called, requests
                called += 1
                if generator:
                    return generator(model, context)
                if live:
                    if requests >= max_requests:
                        raise ProposalError("Evaluation request budget exceeded")
                    requests += 1
                    return generate(
                        model, context, provider=config.provider, api_key=config.api_key
                    )
                entries = cast(list[dict[str, object]], context["evidence"])
                preferred = [
                    e for e in entries if str(e["id"]).startswith("after:")
                ] or entries
                return {
                    "action": case["action"],
                    "summary": "OFFLINE authored fixture, not model output",
                    "content": case["replacement"]
                    if case["action"] == "revise"
                    else None,
                    "warnings": [],
                    "evidence_ids": [preferred[0]["id"]],
                }

            try:
                suggest_git(
                    root,
                    before,
                    head,
                    "docguard-map.json",
                    artifact,
                    config,
                    generator=produce,
                )
                bundle = json.loads(artifact.read_text(encoding="utf-8"))
                proposals = bundle["proposals"]
                decision = (
                    proposals[0]["proposal"]
                    if proposals
                    else {"action": "unchanged", "content": None}
                )
                checks = {
                    "expected_action": decision["action"] == case["action"],
                    "expected_request": bool(called) == case["expect_request"],
                    "generation_preserves_document": (root / "README.md").read_bytes()
                    == original,
                }
                if decision["action"] == "revise":
                    content = decision["content"]
                    assert isinstance(content, str)
                    checks["required_claims"] = all(
                        re.search(pattern, content, re.I | re.S)
                        for pattern in cast(list[str], case["required_patterns"])
                    )
                    checks["forbidden_claims_absent"] = not any(
                        re.search(pattern, content, re.I | re.S)
                        for pattern in cast(list[str], case["forbidden_patterns"])
                    )
                    checks["unrelated_prose_preserved"] = all(
                        text in content for text in cast(list[str], case["preserve"])
                    )
                    apply_git_proposal(artifact, root, "README.md", check=True)
                    checks["preview_preserves_document"] = (
                        root / "README.md"
                    ).read_bytes() == original
                    apply_git_proposal(artifact, root, "README.md")
                    checks["apply_matches_proposal"] = (
                        root / "README.md"
                    ).read_bytes().decode("utf-8") == content
                row.update(
                    passed=all(checks.values()),
                    checks=checks,
                    decision=decision,
                    evidence_ids=proposals[0]["evidence_ids"] if proposals else [],
                )
            except ProviderError as error:
                row.update(passed=False, error=str(error), http_status=error.status)
            except (OSError, ValueError):
                row.update(
                    passed=False,
                    error="Generation, evidence validation or application failed",
                )
        row.update(seconds=round(monotonic() - started, 3), requests=called)
        results.append(row)
        if row.get("http_status") in {401, 403, 429}:
            break  # Preserve partial results; do not spend more calls on a systemic failure.
    report: dict[str, object] = {
        "schema_version": 1,
        "suite": "git-corpus-v1",
        "prompt_version": PROMPT_VERSION,
        "git_prompt_version": GIT_PROMPT_VERSION,
        "mode": "injected-test"
        if generator
        else "live"
        if live
        else "offline-fixtures",
        "provider": config.provider,
        "model": config.model,
        "dataset_sha256": digest(read_bytes(dataset)),
        "selected": len(cases),
        "total": len(results),
        "not_run": len(cases) - len(results),
        "passed": sum(row["passed"] is True for row in results),
        "errors": sum("error" in row for row in results),
        "api_requests": requests,
        "results": results,
    }
    write_new_json(output, report)
    return report
