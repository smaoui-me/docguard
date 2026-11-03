"""Pinned upstream PR projections, explicit variants, and denominator-aware metrics."""

import json
import os
import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from time import monotonic
from typing import Any

from docguard.ai.config import AIConfig
from docguard.ai.files import (
    ProposalError,
    digest,
    read_bytes,
    relative_path,
    write_new_json,
)
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.provider import (
    GIT_PROMPT_VERSION,
    PROMPT_VERSION,
    ProviderError,
    generate,
)


def local_git(root: Path, *args: str) -> bytes:
    """Read local objects only. Acquisition is a separate, explicit user operation."""
    env = dict(
        os.environ,
        GIT_NO_LAZY_FETCH="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
    )
    result = subprocess.run(
        ["git", "-C", str(root), "-c", "core.hooksPath=" + os.devnull, *args],
        env=env,
        capture_output=True,
        timeout=60,
    )
    if result.returncode:
        raise ProposalError(
            "Required local Git operation failed; ensure pinned commits and blobs are downloaded"
        )
    return result.stdout


def load_manifest(path: Path) -> list[dict[str, Any]]:
    data = tomllib.loads(read_bytes(path).decode("utf-8"))
    if (
        type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or not isinstance(data.get("cases"), list)
    ):
        raise ProposalError("Expected version 1 upstream manifest")
    seen: set[str] = set()
    for case in data["cases"]:
        if not isinstance(case, dict):
            raise ProposalError("Invalid upstream case")
        for key in (
            "id",
            "repository_url",
            "pr_url",
            "base",
            "head",
            "license_path",
            "document_path",
            "section",
            "variant",
            "prefix",
            "expected_action",
            "review_status",
            "rationale",
        ):
            if not isinstance(case.get(key), str):
                raise ProposalError(f"Manifest requires string field {key}")
        if not re.fullmatch(r"[a-z0-9_]+", case["id"]) or case["id"] in seen:
            raise ProposalError("Invalid or duplicate case ID")
        seen.add(case["id"])
        if any(
            not re.fullmatch(r"[a-f0-9]{40}|[a-f0-9]{64}", case[key])
            for key in ("base", "head")
        ):
            raise ProposalError("Upstream revisions must be full immutable commit IDs")
        if case["variant"] not in {
            "authentic_head",
            "base_docs",
            "authored_stale_claim",
            "dependency_ablation",
        }:
            raise ProposalError("Unknown upstream variant")
        if case["variant"] in {"authentic_head", "base_docs"} and case["prefix"]:
            raise ProposalError(
                "Authentic/base documentation cannot contain an authored prefix"
            )
        if (
            case["expected_action"] not in {"revise", "unchanged", "needs_review"}
            or type(case.get("expected_detection")) is not bool
        ):
            raise ProposalError("Invalid expected action/detection")
        for key in (
            "source_paths",
            "entity_ids",
            "required_patterns",
            "forbidden_patterns",
            "preserve",
        ):
            if not isinstance(case.get(key), list) or not all(
                isinstance(item, str) for item in case[key]
            ):
                raise ProposalError(f"Manifest requires string array {key}")
        if (
            not case["source_paths"]
            or not case["entity_ids"]
            or len(case["source_paths"]) != len(set(case["source_paths"]))
        ):
            raise ProposalError(
                "Manifest needs unique source paths and mapped entities"
            )
        for name in [
            case["license_path"],
            case["document_path"],
            *case["source_paths"],
        ]:
            relative_path(name)
        if (
            any(not name.endswith(".py") for name in case["source_paths"])
            or Path(case["document_path"]).suffix != ".md"
        ):
            raise ProposalError("Pilot supports Python source and Markdown documents")
        for pattern in case["required_patterns"] + case["forbidden_patterns"]:
            re.compile(pattern)
    return data["cases"]  # type: ignore[no-any-return]


def _blob(repository: Path, revision: str, name: str) -> bytes:
    value = local_git(repository, "show", f"{revision}:{name}")
    if len(value) > 1_000_000:
        raise ProposalError("Upstream blob exceeds 1 MB")
    value.decode("utf-8")
    return value


def extract_section(raw: bytes, heading: str) -> tuple[bytes, int, int]:
    """Select an exact ATX heading and descendants, excluding the next peer heading."""
    lines = raw.decode("utf-8").splitlines(keepends=True)
    if not heading:
        return raw, 1, len(lines)
    matches = [i for i, line in enumerate(lines) if line.strip() == heading]
    if len(matches) != 1 or not re.match(r"^#{1,6} ", heading):
        raise ProposalError("Document section heading must match exactly once")
    start = matches[0]
    level = len(heading.split(" ", 1)[0])
    end = len(lines)
    fenced = False
    for i in range(start + 1, len(lines)):
        if lines[i].lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        match = re.match(r"^(#{1,6}) ", lines[i])
        if not fenced and match and len(match[1]) <= level:
            end = i
            break
    return "".join(lines[start:end]).encode("utf-8"), start + 1, end


def materialize_case(
    repository: Path, case: dict[str, Any], root: Path
) -> dict[str, object]:
    """Build a scope-limited projection; copy exact source files and explicit doc inputs."""
    for key in ("base", "head"):
        actual = (
            local_git(
                repository,
                "rev-parse",
                "--verify",
                "--end-of-options",
                case[key] + "^{commit}",
            )
            .decode()
            .strip()
        )
        if actual != case[key]:
            raise ProposalError("Pinned revision did not resolve exactly")
    if (
        local_git(repository, "merge-base", "--all", case["base"], case["head"])
        .decode()
        .strip()
        != case["base"]
    ):
        raise ProposalError("Manifest base must be the unique merge base")
    root.mkdir()
    local_git(root, "init", "-b", "main")
    for key, value in (
        ("user.name", "DocGuard Upstream Pilot"),
        ("user.email", "pilot@example.invalid"),
        ("commit.gpgsign", "false"),
        ("core.autocrlf", "false"),
    ):
        local_git(root, "config", key, value)
    license_raw = _blob(repository, case["head"], case["license_path"])
    (root / "UPSTREAM-LICENSE.txt").write_bytes(license_raw)
    (root / "docguard-map.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "documents": {case["document_path"]: case["entity_ids"]},
            }
        ),
        encoding="utf-8",
    )
    projections: dict[str, object] = {}
    sources: dict[str, object] = {}
    selections: dict[str, object] = {}
    for side in ("base", "head"):
        hashes: dict[str, str] = {}
        for name in case["source_paths"]:
            raw = _blob(repository, case[side], name)
            target = root / relative_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
            hashes[name] = digest(raw)
        sources[side] = hashes
        doc_revision = case["base"] if case["variant"] == "base_docs" else case[side]
        full_doc = _blob(repository, doc_revision, case["document_path"])
        selected, start, end = extract_section(full_doc, case["section"])
        document = case["prefix"].encode("utf-8") + selected
        target = root / relative_path(case["document_path"])
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(document)
        selections[side] = {
            "upstream_revision": doc_revision,
            "path": case["document_path"],
            "start_line": start,
            "end_line": end,
            "upstream_blob_sha256": digest(full_doc),
            "selected_text_sha256": digest(selected),
            "effective_input_sha256": digest(document),
            "authored_prefix": case["prefix"],
        }
        local_git(root, "add", ".")
        local_git(
            root,
            "commit",
            "--allow-empty",
            "-m",
            f"{side} projection of pinned upstream change",
        )
        projections[side] = local_git(root, "rev-parse", "HEAD").decode().strip()
    return {
        "repository_url": case["repository_url"],
        "pr_url": case["pr_url"],
        "upstream_base": case["base"],
        "upstream_head": case["head"],
        "variant": case["variant"],
        "source_sha256": sources,
        "document_selections": selections,
        "projection_commits": projections,
        "scope": "Selected complete source files and selected documentation section; not the full upstream tree",
        "license_path": case["license_path"],
        "license_sha256": digest(license_raw),
        "license_text": license_raw.decode("utf-8"),
    }


def _rate(numerator: int, denominator: int) -> dict[str, int | float | None]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def summarize(rows: list[dict[str, Any]], selected: int) -> dict[str, object]:
    completed = [r for r in rows if r["status"] == "completed"]
    prepared = [r for r in rows if "detected" in r]
    predicted = [r for r in completed if r["action"] == "revise"]
    positives = [r for r in completed if r["expected_action"] == "revise"]
    negatives = [r for r in completed if r["expected_action"] == "unchanged"]
    abstentions = [r for r in completed if r["expected_action"] == "needs_review"]
    true_edits = sum(r["expected_action"] == "revise" for r in predicted)
    return {
        "completion_coverage": _rate(len(completed), selected),
        "detection_agreement": _rate(
            sum(r["detected"] == r["expected_detection"] for r in prepared),
            len(prepared),
        ),
        "action_accuracy": _rate(
            sum(r["action"] == r["expected_action"] for r in completed), len(completed)
        ),
        "edit_precision": _rate(true_edits, len(predicted)),
        "edit_recall_completed_cases": _rate(true_edits, len(positives)),
        "unnecessary_edit_rate": _rate(
            sum(r["action"] == "revise" for r in negatives), len(negatives)
        ),
        "required_abstention_recall": _rate(
            sum(r["action"] == "needs_review" for r in abstentions), len(abstentions)
        ),
        "automatic_checks_pass_rate": _rate(
            sum(r["automatic_pass"] for r in completed), len(completed)
        ),
        "citation_validity": _rate(
            sum(r["citations_valid"] for r in rows if "citations_valid" in r),
            sum("citations_valid" in r for r in rows),
        ),
        "semantic_correctness": None,
        "human_acceptance_rate": None,
        "note": "Small provisional pilot. Rates exclude uncompleted model cases; inspect coverage and errors. Text checks and citation existence do not establish semantic correctness.",
    }


def evaluate_pr(
    config: AIConfig,
    repository: Path,
    manifest: Path,
    output: Path,
    *,
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
        raise ProposalError("Output must be a new .json file")
    cases = load_manifest(manifest)
    if set(selected) - {c["id"] for c in cases}:
        raise ProposalError("Unknown upstream case")
    cases = [c for c in cases if not selected or c["id"] in selected]
    if not cases or not 1 <= max_requests <= 100:
        raise ProposalError("Select cases and a request budget between 1 and 100")
    if live and (
        len(cases) > max_requests or (not config.api_key.strip() and generator is None)
    ):
        raise ProposalError(
            "Live mode requires credentials and a request budget covering selected cases"
        )
    results: list[dict[str, Any]] = []
    calls = 0
    with TemporaryDirectory(prefix="docguard-upstream-") as directory:
        prepared = []
        # Pin and preflight every input before the first paid call.
        for case in cases:
            root = Path(directory) / case["id"]
            provenance = materialize_case(repository, case, root)
            commits = provenance["projection_commits"]
            assert isinstance(commits, dict)
            requests_path = Path(directory) / f"{case['id']}-requests.json"
            suggest_git(
                root,
                commits["base"],
                commits["head"],
                "docguard-map.json",
                requests_path,
                config,
                dry_run=True,
            )
            requests = json.loads(requests_path.read_text(encoding="utf-8"))
            prepared.append((case, root, provenance, commits, requests))
        for case, root, provenance, commits, requests in prepared:
            row: dict[str, Any] = {
                "case": case["id"],
                "expected_action": case["expected_action"],
                "expected_detection": case["expected_detection"],
                "review_status": case["review_status"],
                "provenance": provenance,
                "detected": bool(requests["requests"]),
                "status": "prepared",
                "human_review": {
                    "status": "pending",
                    "claim_accuracy": None,
                    "completeness": None,
                    "unrelated_preservation": None,
                    "accepted": None,
                },
            }
            if not live and generator is None:
                row["requests"] = requests["requests"]
                results.append(row)
                continue
            usage: list[dict[str, int]] = []
            started = monotonic()
            model_seconds = 0.0

            def produce(model: str, context: dict[str, object]) -> object:
                nonlocal calls, model_seconds
                if calls >= max_requests:
                    raise ProposalError("Request budget exhausted")
                calls += 1
                timestamp = monotonic()
                try:
                    value = (
                        generator(model, context)
                        if generator
                        else generate(
                            model,
                            context,
                            provider=config.provider,
                            api_key=config.api_key,
                            usage_sink=usage.append,
                        )
                    )
                    # Distinguish a provider response from a validated citation set.
                    from docguard.ai.git_proposals import validate_citations

                    row["citations_valid"] = False
                    if isinstance(value, dict):
                        validate_citations(
                            value.get("evidence_ids"),
                            context["evidence"],
                            str(value.get("action")),
                        )
                        row["citations_valid"] = True
                    return value
                finally:
                    model_seconds += monotonic() - timestamp

            try:
                artifact = Path(directory) / f"{case['id']}-proposal.json"
                original = (root / case["document_path"]).read_bytes()
                suggest_git(
                    root,
                    commits["base"],
                    commits["head"],
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
                    "expected_action": decision["action"] == case["expected_action"],
                    "expected_detection": row["detected"] == case["expected_detection"],
                    "generation_preserves_document": (
                        root / case["document_path"]
                    ).read_bytes()
                    == original,
                }
                if decision["action"] == "revise":
                    text = decision["content"]
                    assert isinstance(text, str)
                    checks["required_claims"] = all(
                        re.search(p, text, re.I | re.S)
                        for p in case["required_patterns"]
                    )
                    checks["forbidden_claims_absent"] = not any(
                        re.search(p, text, re.I | re.S)
                        for p in case["forbidden_patterns"]
                    )
                    checks["unrelated_prose_preserved"] = all(
                        p in text for p in case["preserve"]
                    )
                    apply_git_proposal(
                        artifact, root, case["document_path"], check=True
                    )
                    checks["preview_preserves_document"] = (
                        root / case["document_path"]
                    ).read_bytes() == original
                row.update(
                    status="completed",
                    action=decision["action"],
                    decision=decision,
                    checks=checks,
                    automatic_pass=all(checks.values()),
                    proposal=bundle,
                )
            except ProviderError as error:
                row.update(
                    status="api_error", error=str(error), http_status=error.status
                )
            except (OSError, ValueError):
                row.update(
                    status="validation_error",
                    error="Proposal/evidence validation failed",
                )
            row.update(
                seconds=round(monotonic() - started, 3),
                model_seconds=round(model_seconds, 3),
                token_usage=usage or None,
            )
            results.append(row)
            if row.get("http_status") in {401, 403, 429}:
                break
        finished = {row["case"] for row in results}
        for case, root, provenance, commits, requests in prepared:
            if case["id"] not in finished:
                results.append(
                    {
                        "case": case["id"],
                        "status": "not_run",
                        "expected_action": case["expected_action"],
                        "expected_detection": case["expected_detection"],
                        "detected": bool(requests["requests"]),
                        "provenance": provenance,
                        "review_status": case["review_status"],
                        "reason": "Stopped after an operational API error",
                    }
                )
    report: dict[str, object] = {
        "schema_version": 1,
        "suite": "upstream-pr-pilot-v1",
        "mode": "injected-test"
        if generator
        else "live"
        if live
        else "preparation-only",
        "provider": config.provider,
        "model": config.model,
        "prompt_version": PROMPT_VERSION,
        "git_prompt_version": GIT_PROMPT_VERSION,
        "manifest_sha256": digest(read_bytes(manifest)),
        "selected": len(cases),
        "not_run": sum(row["status"] == "not_run" for row in results),
        "api_requests": calls if live and generator is None else 0,
        "errors": sum(r["status"].endswith("error") for r in results),
        "metrics": summarize(results, len(cases)),
        "metrics_by_variant": {
            variant: summarize(
                [row for row in results if row["provenance"]["variant"] == variant],
                sum(case["variant"] == variant for case in cases),
            )
            for variant in sorted({case["variant"] for case in cases})
        },
        "model_seconds": round(
            sum(row.get("model_seconds", 0.0) for row in results), 3
        ),
        "token_usage": {
            key: sum(
                entry[key]
                for row in results
                for entry in (row.get("token_usage") or [])
                if key in entry
            )
            if any(
                key in entry
                for row in results
                for entry in (row.get("token_usage") or [])
            )
            else None
            for key in ("input_tokens", "output_tokens", "total_tokens")
        },
        "cost_usd": None,
        "results": results,
    }
    write_new_json(output, report)
    return report
