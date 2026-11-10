"""Paced, resumable upstream pilot with explicit no-edit/review-all baselines."""

import json
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from docguard.ai.claims import CLAIM_GATE_VERSION
from docguard.ai.config import AIConfig
from docguard.ai.evidence import EVIDENCE_VERSION
from docguard.ai.files import ProposalError, digest, parse_json, read_bytes
from docguard.ai.preservation import PRESERVATION_VERSION
from docguard.ai.provider import GIT_PROMPT_VERSION, PROMPT_VERSION, request_payload
from docguard.ai.upstream import _checkpoint, evaluate_pr, load_manifest


def decision_metrics(
    rows: list[dict[str, Any]], prediction: str | None = None
) -> dict[str, object]:
    """Score decisions only, on a common set of completed cases; no semantic claims."""

    def rate(n: int, d: int) -> dict[str, object]:
        return {"numerator": n, "denominator": d, "value": n / d if d else None}

    pairs = [(row["expected_action"], prediction or row["action"]) for row in rows]
    return {
        "action_agreement": rate(sum(a == b for a, b in pairs), len(pairs)),
        "missed_edits": rate(
            sum(a == "revise" and b != "revise" for a, b in pairs),
            sum(a == "revise" for a, _ in pairs),
        ),
        "unnecessary_edits": rate(
            sum(a == "unchanged" and b == "revise" for a, b in pairs),
            sum(a == "unchanged" for a, _ in pairs),
        ),
        "appropriate_abstention": rate(
            sum(a == b == "needs_review" for a, b in pairs),
            sum(a == "needs_review" for a, _ in pairs),
        ),
        "review_routing": rate(sum(b == "needs_review" for _, b in pairs), len(pairs)),
    }


def compare_decisions(rows: list[dict[str, Any]]) -> dict[str, object]:
    completed = [row for row in rows if row.get("status") == "completed"]
    return {
        "completed": len(completed),
        "selected": len(rows),
        "docguard": decision_metrics(completed),
        "leave_docs_unchanged": decision_metrics(completed, "unchanged"),
        "route_every_change_to_review": decision_metrics(completed, "needs_review"),
        "note": "All three policies scored on the same completed cases. Baselines are deterministic decisions, not generated repairs. Check coverage; provisional labels and inspected cases do not establish independent semantic accuracy or time saved.",
    }


def markdown_summary(report: dict[str, Any]) -> str:
    lines = [
        "# DocGuard upstream pilot",
        "",
        f"Mode: **{report['mode']}**. Completed {sum(r['status'] == 'completed' for r in report['results'])}/{len(report['results'])} selected variants from {report['distinct_prs']} distinct PRs.",
        "",
        "This is a regression pilot with provisional labels, not an independently reviewed benchmark. No human acceptance or developer-time savings are inferred.",
        "",
    ]
    for group, comparison in report["comparisons"].items():
        lines += [
            f"## {group}",
            "",
            f"Completed {comparison['completed']}/{comparison['selected']}. Common completed-case denominators below.",
            "",
            "| Policy | Action agreement | Missed edits | Unnecessary edits | Appropriate abstention |",
            "| --- | --- | --- | --- | --- |",
        ]
        for policy in (
            "docguard",
            "leave_docs_unchanged",
            "route_every_change_to_review",
        ):
            values = comparison[policy]
            cells = [
                f"{values[key]['numerator']}/{values[key]['denominator']}"
                if values[key]["denominator"]
                else "n/a"
                for key in (
                    "action_agreement",
                    "missed_edits",
                    "unnecessary_edits",
                    "appropriate_abstention",
                )
            ]
            lines.append("| " + policy + " | " + " | ".join(cells) + " |")
        lines.append("")
    lines += [
        "## Case outcomes",
        "",
        "| Case | Status | Expected | Actual | Automatic checks |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in report["results"]:
        lines.append(
            f"| {row['case']} | {row['status']} | {row['expected_action']} | {row.get('action', 'n/a')} | {row.get('automatic_pass', 'n/a')} |"
        )
    lines += [
        "",
        f"API attempts across checkpoints: {report.get('api_requests_total', 'unrecorded')}. Requests this invocation: {report['session_requests']}. Stop reason: {report['stop_reason'] or 'none'}.",
        "",
        "Inspect per-case JSON for citations, edits, failure reasons and token usage. Contract-assisted cases are reported separately; gate readiness proves availability, not truth.",
        "",
    ]
    return "\n".join(lines)


def run_pilot(
    config: AIConfig,
    plans: Sequence[tuple[Path, Path]],
    output: Path,
    *,
    selected: Sequence[str] = (),
    live: bool = False,
    resume: bool = False,
    max_requests: int = 3,
    delay_seconds: float = 65,
    progress: Callable[[str], None] = print,
) -> dict[str, Any]:
    if not 1 <= max_requests <= 100 or not 0 <= delay_seconds <= 600:
        raise ProposalError(
            "Use a request budget of 1..100 and delay of 0..600 seconds"
        )
    cases = [
        (manifest, repo, case)
        for manifest, repo in plans
        for case in load_manifest(manifest)
    ]
    ids = [case["id"] for _, _, case in cases]
    if len(set(ids)) != len(ids) or set(selected) - set(ids):
        raise ProposalError("Duplicate or unknown pilot case IDs")
    cases = [entry for entry in cases if not selected or entry[2]["id"] in selected]
    if not cases:
        raise ProposalError("Select at least one case")
    identity = {
        "version": 1,
        "manifests": {str(p.resolve()): digest(read_bytes(p)) for p, _ in plans},
        "cases": [case["id"] for _, _, case in cases],
        "mode": "live" if live else "preparation-only",
        "provider": config.provider,
        "model": config.model,
        "prompt_version": PROMPT_VERSION,
        "git_prompt_version": GIT_PROMPT_VERSION,
        "evidence_version": EVIDENCE_VERSION,
        "claim_gate_version": CLAIM_GATE_VERSION,
        "preservation_version": PRESERVATION_VERSION,
        "request_sha256": digest(
            json.dumps(
                request_payload(config.model, {"evidence": []}, config.provider),
                sort_keys=True,
            ).encode()
        ),
    }
    if output.is_symlink() or output.exists() != resume:
        raise ProposalError(
            "Use a new output directory, or --resume with the existing directory"
        )
    if not resume:
        output.mkdir(parents=True)
    lock = output / "pilot.lock"
    try:
        with lock.open("x"):
            pass
    except FileExistsError:
        raise ProposalError("Pilot is locked; another run may be active") from None
    try:
        path = output / "report.json"
        if resume:
            saved = parse_json(read_bytes(path, 100_000_000).decode("utf-8"))
            if not isinstance(saved, dict) or saved.get("identity") != identity:
                raise ProposalError("Pilot resume configuration mismatch")
        rows: list[dict[str, Any]] = [
            {
                "case": c["id"],
                "status": "not_run",
                "expected_action": c["expected_action"],
                "pr_url": c["pr_url"],
                "contract_assisted": bool(c.get("claims")),
            }
            for _, _, c in cases
        ]
        report: dict[str, Any] = {
            "schema_version": 1,
            "kind": "docguard.pilot-comparison",
            "identity": identity,
            "mode": identity["mode"],
            "provider": config.provider,
            "model": config.model,
            "distinct_prs": len({c["pr_url"] for _, _, c in cases}),
            "results": rows,
            "session_requests": 0,
            "stop_reason": None,
            "minimum_delay_seconds": delay_seconds,
            "human_acceptance": None,
        }

        def save() -> None:
            attempts = []
            for item in rows:
                case_path = output / f"{item['case']}.json"
                if case_path.exists():
                    case_data = parse_json(
                        read_bytes(case_path, 100_000_000).decode("utf-8")
                    )
                    if isinstance(case_data, dict):
                        attempts.extend(case_data.get("attempts", []))
            report["attempts"] = attempts
            report["api_requests_total"] = len(attempts)
            report["token_usage"] = {
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
            }
            report["comparisons"] = {
                group: compare_decisions(
                    [row for row in rows if row["contract_assisted"] == assisted]
                )
                for group, assisted in (
                    ("unassisted", False),
                    ("contract_assisted", True),
                )
            }
            _checkpoint(path, report)
            (output / "summary.md").write_text(
                markdown_summary(report), encoding="utf-8", newline="\n"
            )

        # Restore known rows even if this invocation's budget stops before reaching them.
        for row, (manifest, _, _) in zip(rows, cases):
            checkpoint = output / f"{row['case']}.json"
            if checkpoint.exists():
                prior = parse_json(read_bytes(checkpoint, 100_000_000).decode("utf-8"))
                expected = {
                    key: identity[key]
                    for key in (
                        "mode",
                        "provider",
                        "model",
                        "prompt_version",
                        "git_prompt_version",
                        "evidence_version",
                        "claim_gate_version",
                        "preservation_version",
                        "request_sha256",
                    )
                }
                expected.update(
                    cases=[row["case"]], manifest_sha256=digest(read_bytes(manifest))
                )
                if (
                    checkpoint.is_symlink()
                    or not isinstance(prior, dict)
                    or any(
                        prior.get("identity", {}).get(key) != value
                        for key, value in expected.items()
                    )
                ):
                    raise ProposalError("Invalid case checkpoint")
                prior_rows = prior.get("results")
                if (
                    not isinstance(prior_rows, list)
                    or len(prior_rows) != 1
                    or not isinstance(prior_rows[0], dict)
                    or prior_rows[0].get("case") != row["case"]
                    or prior_rows[0].get("expected_action") != row["expected_action"]
                ):
                    raise ProposalError("Invalid case checkpoint results")
                row.update(prior_rows[0])
        save()
        for index, (manifest, repo, case) in enumerate(cases):
            if report["session_requests"] >= max_requests:
                report["stop_reason"] = "Session request budget exhausted"
                break
            checkpoint = output / f"{case['id']}.json"
            # Completed checkpoints still pass through evaluate_pr's full identity checks.
            if live and rows[index]["status"] not in {"completed", "validation_error"}:
                remaining = delay_seconds if resume or report["session_requests"] else 0
                while remaining > 0:
                    interval = min(remaining, 10)
                    progress(f"Pacing: {remaining:g}s before {case['id']}")
                    time.sleep(interval)
                    remaining -= interval
            progress(f"Evaluating {case['id']}")
            case_report = evaluate_pr(
                config,
                repo,
                manifest,
                checkpoint,
                selected=[case["id"]],
                live=live,
                max_requests=max_requests - report["session_requests"],
                resume=checkpoint.exists(),
                max_retries=1,
                max_retry_wait=60,
            )
            case_rows = case_report["results"]
            if (
                not isinstance(case_rows, list)
                or len(case_rows) != 1
                or not isinstance(case_rows[0], dict)
            ):
                raise ProposalError("Invalid evaluator results")
            rows[index].update(case_rows[0])
            report["session_requests"] += case_report["session_requests"]
            save()
            progress(
                f"{case['id']}: {rows[index]['status']}, action={rows[index].get('action')}, checks={rows[index].get('automatic_pass')}"
            )
            if rows[index].get("http_status") in {401, 403, 429}:
                report["stop_reason"] = f"Stopped on HTTP {rows[index]['http_status']}"
                break
        save()
        return report
    finally:
        lock.unlink(missing_ok=True)
