"""Pinned upstream PR projections, explicit variants, and denominator-aware metrics."""

import json
import os
import re
import subprocess
import tomllib
from collections.abc import Callable, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile, TemporaryDirectory
from time import monotonic, sleep
from typing import Any

from docguard.ai.config import AIConfig
from docguard.ai.evidence import EVIDENCE_VERSION
from docguard.ai.files import (
    ProposalError,
    digest,
    parse_json,
    read_bytes,
    relative_path,
)
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.preservation import PRESERVATION_VERSION, inspect_preservation
from docguard.ai.provider import (
    GIT_PROMPT_VERSION,
    PROMPT_VERSION,
    ProviderError,
    generate,
    request_payload,
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
    groups: dict[str, str] = {}
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
        if case.get("evidence_policy", "mapped") not in ("mapped", "direct"):
            raise ProposalError("Unknown evidence policy")
        split = case.get("split", "development")
        group = case.get("group", case["pr_url"])
        if (
            split not in {"development", "held_out"}
            or not isinstance(group, str)
            or not group
        ):
            raise ProposalError("Invalid benchmark split/group")
        for grouping in (case["pr_url"], case["repository_url"] + ":" + group):
            if grouping in groups and groups[grouping] != split:
                raise ProposalError("Related PR cases cannot cross dataset splits")
            groups[grouping] = split
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
        if not isinstance(case.get("base_section", case["section"]), str):
            raise ProposalError("base_section must be a string")
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
        selected, start, end = extract_section(
            full_doc,
            case.get("base_section", case["section"])
            if doc_revision == case["base"]
            else case["section"],
        )
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


def _checkpoint(path: Path, report: dict[str, object]) -> None:
    """Replace a report only after the entire next checkpoint is on disk."""
    temporary = None
    try:
        with NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            json.dump(report, stream, ensure_ascii=False, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


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
    resume: bool = False,
    max_retries: int = 2,
    max_retry_wait: float = 30,
) -> dict[str, object]:
    """Single-writer evaluation. A hard crash can leave a lock for manual inspection."""
    lock = output.with_name(output.name + ".lock")
    try:
        stream = lock.open("x")
    except FileExistsError:
        raise ProposalError(
            "Evaluation is locked; check for another process before removing its .lock file"
        ) from None
    try:
        with stream:
            stream.write(str(os.getpid()))
        return _evaluate_pr(
            config,
            repository,
            manifest,
            output,
            selected=selected,
            live=live,
            max_requests=max_requests,
            generator=generator,
            resume=resume,
            max_retries=max_retries,
            max_retry_wait=max_retry_wait,
        )
    finally:
        lock.unlink(missing_ok=True)


def _evaluate_pr(
    config: AIConfig,
    repository: Path,
    manifest: Path,
    output: Path,
    *,
    selected: Sequence[str] = (),
    live: bool = False,
    max_requests: int = 3,
    generator: Callable[[str, dict[str, object]], object] | None = None,
    resume: bool = False,
    max_retries: int = 2,
    max_retry_wait: float = 30,
) -> dict[str, object]:
    if not 0 <= max_retries <= 5 or not 0 <= max_retry_wait <= 60:
        raise ProposalError("Retry bounds: 0..5 retries and 0..60 seconds wait")
    if (
        (output.exists() != resume)
        or output.is_symlink()
        or output.suffix.lower() != ".json"
        or not output.parent.is_dir()
    ):
        raise ProposalError(
            "Output must be a new .json file, or an existing report with --resume"
        )
    cases = load_manifest(manifest)
    if set(selected) - {c["id"] for c in cases}:
        raise ProposalError("Unknown upstream case")
    cases = [c for c in cases if not selected or c["id"] in selected]
    if not cases or not 1 <= max_requests <= 100:
        raise ProposalError("Select cases and a request budget between 1 and 100")
    if live and not config.api_key.strip() and generator is None:
        raise ProposalError("Live mode requires credentials")
    identity = {
        "manifest_sha256": digest(read_bytes(manifest)),
        "cases": [case["id"] for case in cases],
        "provider": config.provider,
        "model": config.model,
        "mode": "injected-test"
        if generator
        else "live"
        if live
        else "preparation-only",
        "prompt_version": PROMPT_VERSION,
        "git_prompt_version": GIT_PROMPT_VERSION,
        "request_sha256": digest(
            json.dumps(
                request_payload(config.model, {"evidence": []}, config.provider),
                sort_keys=True,
            ).encode()
        ),
        "suite": "upstream-pr-pilot-v2",
        "evidence_version": EVIDENCE_VERSION,
        "preservation_version": PRESERVATION_VERSION,
    }
    results: list[dict[str, Any]] = []
    attempts: list[dict[str, Any]] = []
    calls = 0
    session_calls = 0
    if resume:
        previous = parse_json(read_bytes(output, limit=100_000_000).decode("utf-8"))
        if not isinstance(previous, dict) or previous.get("identity") != identity:
            raise ProposalError(
                "Resume configuration mismatch: dataset, selection, mode, provider, model or prompt changed"
            )
        results = previous.get("results", [])
        attempts = previous.get("attempts", [])
        if (
            not isinstance(results, list)
            or not isinstance(attempts, list)
            or any(not isinstance(row, dict) for row in results)
            or [row.get("case") for row in results] != identity["cases"]
        ):
            raise ProposalError("Invalid checkpoint results")
        if any(not isinstance(attempt, dict) for attempt in attempts):
            raise ProposalError("Invalid checkpoint attempts")
        statuses = {
            "not_run",
            "prepared",
            "running",
            "api_error",
            "validation_error",
            "completed",
        }
        try:
            for saved_row, case in zip(results, cases):
                if (
                    saved_row.get("status") not in statuses
                    or not isinstance(saved_row.get("provenance"), dict)
                    or saved_row["provenance"].get("variant") != case["variant"]
                    or saved_row.get("expected_action") != case["expected_action"]
                    or saved_row.get("expected_detection") != case["expected_detection"]
                ):
                    raise ValueError
                if saved_row["status"] == "completed" and (
                    saved_row.get("action")
                    not in {"revise", "unchanged", "needs_review"}
                    or type(saved_row.get("automatic_pass")) is not bool
                    or not isinstance(saved_row.get("checks"), dict)
                    or not isinstance(saved_row.get("proposal"), dict)
                ):
                    raise ValueError
            for attempt in attempts:
                if attempt.get("case") not in identity["cases"] or attempt.get(
                    "status"
                ) not in {"in_flight", "response_received", "api_error"}:
                    raise ValueError
            summarize(results, len(cases))
        except (ValueError, TypeError, KeyError):
            raise ProposalError("Invalid checkpoint results or attempts") from None
        calls = len(attempts)

    def checkpoint() -> dict[str, object]:
        report: dict[str, object] = {
            "schema_version": 2,
            "identity": identity,
            "attempts": attempts,
            "session_requests": session_calls,
            "suite": "upstream-pr-pilot-v2",
            "mode": "injected-test"
            if generator
            else "live"
            if live
            else "preparation-only",
            "provider": config.provider,
            "model": config.model,
            "prompt_version": PROMPT_VERSION,
            "git_prompt_version": GIT_PROMPT_VERSION,
            "manifest_sha256": identity["manifest_sha256"],
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
                sum(attempt.get("seconds", 0.0) for attempt in attempts), 3
            ),
            "token_usage": {
                key: sum(
                    entry[key]
                    for attempt in attempts
                    for entry in (attempt.get("token_usage") or [])
                    if key in entry
                )
                if any(
                    key in entry
                    for attempt in attempts
                    for entry in (attempt.get("token_usage") or [])
                )
                else None
                for key in ("input_tokens", "output_tokens", "total_tokens")
            },
            "cost_usd": None,
            "results": results,
        }
        _checkpoint(output, report)
        return report

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
                evidence_policy=case.get("evidence_policy", "mapped"),
            )
            requests = json.loads(requests_path.read_text(encoding="utf-8"))
            prepared.append((case, root, provenance, commits, requests))
        if not results:
            results.extend(
                {
                    "case": case["id"],
                    "status": "not_run",
                    "provenance": provenance,
                    "detected": bool(requests["requests"]),
                    "expected_action": case["expected_action"],
                    "expected_detection": case["expected_detection"],
                }
                for case, root, provenance, commits, requests in prepared
            )
        checkpoint()
        for case, root, provenance, commits, requests in prepared:
            position = next(
                i for i, row in enumerate(results) if row["case"] == case["id"]
            )
            if results[position]["status"] in {"completed", "validation_error"}:
                continue
            if session_calls >= max_requests:
                break
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
            results[position] = row
            if not live and generator is None:
                row["requests"] = requests["requests"]
                checkpoint()
                continue
            usage: list[dict[str, int]] = []
            started = monotonic()
            model_seconds = 0.0

            def produce(model: str, context: dict[str, object]) -> object:
                nonlocal calls, session_calls, model_seconds
                try:
                    for retry in range(max_retries + 1):
                        if session_calls >= max_requests:
                            raise ProposalError("Request budget exhausted")
                        calls += 1
                        session_calls += 1
                        attempt: dict[str, Any] = {
                            "case": case["id"],
                            "status": "in_flight",
                        }
                        attempts.append(attempt)
                        row["status"] = "running"
                        checkpoint()
                        attempt_started = monotonic()
                        usage_start = len(usage)
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
                            attempt["status"] = "response_received"
                            break
                        except ProviderError as error:
                            delay = (
                                error.retry_after
                                if error.retry_after is not None
                                else float(2**retry)
                            )
                            attempt.update(
                                status="api_error",
                                http_status=error.status,
                                seconds=round(monotonic() - attempt_started, 3),
                            )
                            checkpoint()
                            if (
                                error.status != 429
                                or retry == max_retries
                                or session_calls >= max_requests
                                or delay > max_retry_wait
                            ):
                                raise
                            attempt["retry_delay_seconds"] = delay
                            checkpoint()
                            sleep(delay)
                        finally:
                            attempt.setdefault(
                                "seconds", round(monotonic() - attempt_started, 3)
                            )
                            attempt["token_usage"] = usage[usage_start:] or None
                            checkpoint()
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
                    model_seconds = sum(
                        a.get("seconds", 0.0)
                        for a in attempts
                        if a["case"] == case["id"]
                    )

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
                    evidence_policy=case.get("evidence_policy", "mapped"),
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
                    row["preservation"] = inspect_preservation(
                        original.decode("utf-8"), text
                    )
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
            checkpoint()
            if (
                row.get("http_status") in {401, 403, 429}
                or session_calls >= max_requests
            ):
                break
    return checkpoint()
