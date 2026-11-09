"""Deterministic availability gates for explicitly declared documentation claims."""

from dataclasses import asdict

from docguard.docs.mapping import ClaimRequirement

CLAIM_GATE_VERSION = 1


def assess_claims(
    claims: tuple[ClaimRequirement, ...],
    document: str,
    evidence: list[dict[str, object]],
) -> dict[str, object]:
    available = {item["id"] for item in evidence if item.get("text")}
    rows = []
    for claim in claims:
        # Detect overlapping matches too; two means ambiguous (two or more).
        first = document.find(claim.quote)
        matches = (
            0 if first < 0 else 1 + int(document.find(claim.quote, first + 1) >= 0)
        )
        missing = sorted(set(claim.required_evidence) - available)
        rows.append(
            {
                **asdict(claim),
                "quote_matches": matches,
                "missing_evidence": missing,
                "status": "ready" if matches == 1 and not missing else "needs_review",
            }
        )
    return {
        "version": CLAIM_GATE_VERSION,
        "claims": rows,
        "status": "needs_review"
        if any(row["status"] == "needs_review" for row in rows)
        else "ready",
    }


def blocked_decision(context: dict[str, object]) -> dict[str, object] | None:
    gate = context.get("claim_requirements")
    if not isinstance(gate, dict) or gate.get("status") != "needs_review":
        return None
    warnings = []
    rows = gate["claims"]
    assert isinstance(rows, list)
    for row in rows:
        if row["status"] == "needs_review":
            warnings.append(
                f"Claim {row['id']}: quote matches={row['quote_matches']}; missing evidence={', '.join(row['missing_evidence']) or 'none'}"
            )
    return {
        "action": "needs_review",
        "summary": "Explicit claim evidence requirements are unmet; AI generation was skipped.",
        "content": None,
        "warnings": warnings,
        "evidence_ids": [],
    }
