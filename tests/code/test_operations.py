import json
from pathlib import Path
from unittest.mock import patch

import pytest

from docguard.ai.benchmark import audit_benchmark, collect_candidates
from docguard.ai.files import ProposalError
from docguard.ai.operations import summarize_evaluation


def test_metrics_denominators_retries_failures_and_no_human_invention(tmp_path):
    path, output = tmp_path / "report.json", tmp_path / "summary.json"
    path.write_text(
        json.dumps(
            {
                "mode": "injected-test",
                "source": "private-source-marker",
                "results": [
                    {
                        "status": "completed",
                        "expected_action": "revise",
                        "action": "needs_review",
                    },
                    {
                        "status": "completed",
                        "expected_action": "unchanged",
                        "action": "revise",
                    },
                    {
                        "status": "completed",
                        "expected_action": "needs_review",
                        "action": "needs_review",
                        "decision_source": "deterministic_gate",
                    },
                    {"status": "api_error"},
                ],
                "attempts": [
                    {
                        "case": "a",
                        "status": "api_error",
                        "http_status": 429,
                        "seconds": 1,
                        "retry_delay_seconds": 2,
                    },
                    {"case": "a", "status": "response_received", "seconds": 3},
                    {"case": "b", "status": "response_received", "seconds": 2},
                ],
            }
        )
    )
    report = summarize_evaluation(path, output)
    assert report["completion"]["value"] == 0.75
    assert report["missed_edits"]["value"] == 1
    assert report["unnecessary_edits"]["value"] == 1
    assert report["appropriate_abstention"]["value"] == 1
    assert report["http_failures"] == {"429": 1}
    assert report["additional_attempts"] == 1
    assert report["retry_wait_seconds"] == 2
    assert report["latency_seconds"]["p50"] == 2
    assert report["latency_seconds"]["p95"] == 3
    assert report["human_acceptance"] is None and report["token_usage"] is None
    assert "private-source-marker" not in output.read_text()


def test_empty_report_does_not_claim_perfect_results(tmp_path):
    path, output = tmp_path / "report.json", tmp_path / "summary.json"
    path.write_text('{"results": []}')
    report = summarize_evaluation(path, output)
    assert report["completion"]["value"] is None
    assert report["latency_seconds"]["p95"] is None
    with pytest.raises(FileExistsError):
        summarize_evaluation(path, output)


def test_candidate_mining_deduplicates_prs_without_inventing_labels(tmp_path):
    record = (
        "\x1e"
        + "a" * 40
        + "\x1f"
        + "b" * 40
        + "\x1fFeature (#123)\n\napi.py\ndocs/api.md\n"
    )
    with patch(
        "docguard.ai.benchmark._git", side_effect=[(record * 2).encode(), b"a" * 40]
    ):
        result = collect_candidates(
            tmp_path, "owner/repo", tmp_path / "candidates.json", 1
        )
    assert len(result["candidates"]) == 1
    case = result["candidates"][0]
    assert case["expected_action"] is None and not case["admitted"]
    assert case["split"] == "unassigned" and case["reviewer"] is None
    assert len(case["base"]) == 40
    with patch("docguard.ai.benchmark._git", return_value=record.encode()):
        with pytest.raises(ProposalError, match="Only 1"):
            collect_candidates(tmp_path, "owner/repo", tmp_path / "too-many.json", 2)


def test_checked_in_intake_has_thirty_distinct_pinned_pending_prs():
    cases = []
    for path in Path("evaluations/candidates").glob("*.json"):
        cases.extend(json.loads(path.read_text())["candidates"])
    assert len(cases) == 30
    assert len({c["pr_url"] for c in cases}) == 30
    assert all(c["review_status"] == "pending" and not c["admitted"] for c in cases)
    assert all(len(c["base"]) == len(c["head"]) == 40 for c in cases)


def test_audit_counts_distinct_prs_and_rejects_cross_file_leakage(tmp_path):
    one = {
        "id": "one",
        "pr_url": "https://github.com/owner/repo/pull/1",
        "repository_url": "https://github.com/owner/repo",
        "group": "related",
        "split": "development",
    }
    two = dict(one, id="two")
    with patch("docguard.ai.benchmark.load_manifest", side_effect=[[one], [two]]):
        result = audit_benchmark([Path("one"), Path("two")], tmp_path / "audit.json")
    assert result["cases"] == 2 and result["distinct_prs"] == 1
    assert result["independent_labels_verified"] is False
    two["split"] = "held_out"
    with patch("docguard.ai.benchmark.load_manifest", side_effect=[[one], [two]]):
        with pytest.raises(ProposalError, match="cross dataset splits"):
            audit_benchmark([Path("one"), Path("two")], tmp_path / "invalid.json")


@pytest.mark.parametrize(
    "attempts",
    [None, {}, [{"retry_delay_seconds": -1}], [{"retry_delay_seconds": "secret"}]],
)
def test_invalid_telemetry_rejected(tmp_path, attempts):
    path = tmp_path / "report.json"
    path.write_text(json.dumps({"results": [], "attempts": attempts}))
    with pytest.raises(ProposalError):
        summarize_evaluation(path, tmp_path / "out.json")
