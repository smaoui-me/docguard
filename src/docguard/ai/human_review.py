"""Explicit human judgments tied to the exact evaluation report bytes."""

from pathlib import Path
from typing import Any

from docguard.ai.files import (
    ProposalError,
    digest,
    parse_json,
    read_bytes,
    write_new_json,
)

FIELDS = ("supported", "complete", "preserves_unrelated", "accepted")


def _report(path: Path) -> tuple[str, list[dict[str, Any]]]:
    raw = read_bytes(path, 100_000_000)
    data = parse_json(raw.decode("utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ProposalError("Expected an upstream evaluation report")
    rows = data["results"]
    if any(
        not isinstance(row, dict) or not isinstance(row.get("case"), str)
        for row in rows
    ):
        raise ProposalError("Invalid evaluation rows")
    if len({row["case"] for row in rows}) != len(rows):
        raise ProposalError("Duplicate evaluation cases")
    return digest(raw), rows


def review_template(report: Path, output: Path) -> None:
    report_hash, rows = _report(report)
    write_new_json(
        output,
        {
            "schema_version": 1,
            "report_sha256": report_hash,
            "reviews": [
                {
                    "case": row["case"],
                    "reviewer": "",
                    "independent": False,
                    "expected_action": None,
                    **dict.fromkeys(FIELDS),
                    "notes": "",
                }
                for row in rows
                if row.get("status") == "completed"
            ],
        },
    )


def score_review(report: Path, reviews: Path, output: Path) -> dict[str, object]:
    report_hash, rows = _report(report)
    data = parse_json(read_bytes(reviews).decode("utf-8"))
    if (
        not isinstance(data, dict)
        or type(data.get("schema_version")) is not int
        or data["schema_version"] != 1
        or data.get("report_sha256") != report_hash
        or not isinstance(data.get("reviews"), list)
    ):
        raise ProposalError("Review must match the exact report and schema version")
    completed = {row["case"]: row for row in rows if row.get("status") == "completed"}
    seen: set[str] = set()
    judgments: list[dict[str, Any]] = []
    for row in data["reviews"]:
        if not isinstance(row, dict) or set(row) != {
            "case",
            "reviewer",
            "independent",
            "expected_action",
            "notes",
            *FIELDS,
        }:
            raise ProposalError("Invalid human review fields")
        case = row["case"]
        if not isinstance(case, str) or case not in completed or case in seen:
            raise ProposalError("Duplicate, unknown or uncompleted review case")
        seen.add(case)
        if (
            not isinstance(row["reviewer"], str)
            or not isinstance(row["notes"], str)
            or type(row["independent"]) is not bool
        ):
            raise ProposalError(
                "Reviewer/notes must be text and independence a boolean"
            )
        if all(row[key] is None for key in (*FIELDS, "expected_action")):
            continue
        if (
            not row["reviewer"].strip()
            or not row["notes"].strip()
            or any(type(row[key]) is not bool for key in FIELDS)
            or not isinstance(row["expected_action"], str)
            or row["expected_action"] not in {"revise", "unchanged", "needs_review"}
        ):
            raise ProposalError(
                "Complete each judgment with reviewer, rationale, expected action and boolean ratings"
            )
        judgments.append(row)

    def rate(numerator: int, denominator: int) -> dict[str, object]:
        return {
            "numerator": numerator,
            "denominator": denominator,
            "value": numerator / denominator if denominator else None,
        }

    def metrics(items: list[dict[str, Any]]) -> dict[str, object]:
        return {
            "coverage_of_completed": rate(len(items), len(completed)),
            "acceptance": rate(sum(r["accepted"] for r in items), len(items)),
            "supported_claims": rate(sum(r["supported"] for r in items), len(items)),
            "completeness": rate(sum(r["complete"] for r in items), len(items)),
            "unrelated_preservation": rate(
                sum(r["preserves_unrelated"] for r in items), len(items)
            ),
            "label_agreement": rate(
                sum(
                    r["expected_action"] == completed[r["case"]].get("expected_action")
                    for r in items
                ),
                len(items),
            ),
            "action_accuracy_against_reviewer": rate(
                sum(
                    r["expected_action"] == completed[r["case"]].get("action")
                    for r in items
                ),
                len(items),
            ),
        }

    result: dict[str, object] = {
        "schema_version": 1,
        "report_sha256": report_hash,
        "selected_cases": len(rows),
        "completed_cases": len(completed),
        "reviewed_cases": len(judgments),
        "metrics": metrics(judgments),
        "independent_metrics": metrics([r for r in judgments if r["independent"]]),
        "reviews": judgments,
        "note": "Ratings and independence are reviewer attestations, not verified identities. Label disagreements require adjudication; original gold labels are not changed.",
    }
    write_new_json(output, result)
    return result
