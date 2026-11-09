"""Aggregate recorded operations without sending source, secrets, or new requests."""

import math
from collections import Counter
from pathlib import Path
from typing import Any

from docguard.ai.files import (
    ProposalError,
    digest,
    parse_json,
    read_bytes,
    write_new_json,
)


def _rate(numerator: int, denominator: int) -> dict[str, object]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def summarize_evaluation(path: Path, output: Path) -> dict[str, Any]:
    raw = read_bytes(path, 100_000_000)
    report = parse_json(raw.decode("utf-8"))
    if not isinstance(report, dict) or not isinstance(report.get("results"), list):
        raise ProposalError("Expected an evaluation report with results")
    rows = report["results"]
    attempts = report.get("attempts", [])
    if not isinstance(attempts, list) or any(
        not isinstance(row, dict) for row in rows + attempts
    ):
        raise ProposalError("Invalid evaluation rows/attempts")
    if any("status" not in row for row in rows):
        raise ProposalError("Expected upstream evaluation rows with status fields")
    for attempt in attempts:
        delay = attempt.get("retry_delay_seconds", 0)
        if type(delay) not in (int, float) or not math.isfinite(delay) or delay < 0:
            raise ProposalError("Invalid retry delay")
    completed = [row for row in rows if row.get("status") == "completed"]
    durations = sorted(
        float(a["seconds"])
        for a in attempts
        if isinstance(a.get("seconds"), (float, int))
        and not isinstance(a["seconds"], bool)
        and math.isfinite(a["seconds"])
        and a["seconds"] >= 0
    )
    expected_edits = [r for r in completed if r.get("expected_action") == "revise"]
    expected_no_edits = [
        r for r in completed if r.get("expected_action") == "unchanged"
    ]
    abstentions = [r for r in completed if r.get("expected_action") == "needs_review"]
    counts = Counter(str(a.get("case")) for a in attempts)
    result: dict[str, Any] = {
        "schema_version": 1,
        "kind": "docguard.operational-summary",
        "report_sha256": digest(raw),
        "mode": report.get("mode"),
        "provider": report.get("provider"),
        "model": report.get("model"),
        "completion": _rate(len(completed), len(rows)),
        "unnecessary_edits": _rate(
            sum(r.get("action") == "revise" for r in expected_no_edits),
            len(expected_no_edits),
        ),
        "missed_edits": _rate(
            sum(r.get("action") != "revise" for r in expected_edits),
            len(expected_edits),
        ),
        "appropriate_abstention": _rate(
            sum(r.get("action") == "needs_review" for r in abstentions),
            len(abstentions),
        ),
        "case_statuses": dict(
            Counter(str(r.get("status", "unrecorded")) for r in rows)
        ),
        "decision_sources": dict(
            Counter(str(r.get("decision_source", "unrecorded")) for r in completed)
        ),
        "api_attempts_recorded": len(attempts),
        "additional_attempts": sum(max(0, n - 1) for n in counts.values()),
        "http_failures": dict(
            Counter(
                str(a.get("http_status", "unknown"))
                for a in attempts
                if a.get("status") == "api_error"
            )
        ),
        "latency_seconds": {
            "samples": len(durations),
            "p50": durations[math.ceil(len(durations) * 0.5) - 1]
            if durations
            else None,
            "p95": durations[math.ceil(len(durations) * 0.95) - 1]
            if durations
            else None,
            "method": "nearest rank, per API attempt; includes failures with recorded duration",
        },
        "retry_wait_seconds": sum(a.get("retry_delay_seconds", 0) for a in attempts),
        "token_usage": report.get("token_usage"),
        "human_acceptance": None,
        "limitations": "Provisional expected labels; completion and action agreement are not semantic correctness. Missing telemetry remains unknown. Additional attempts include retries and interrupted/resumed calls. Human acceptance requires score-review.",
    }
    if "attempts" not in report:
        for key in (
            "api_attempts_recorded",
            "additional_attempts",
            "http_failures",
            "retry_wait_seconds",
        ):
            result[key] = None
    write_new_json(output, result)
    return result
