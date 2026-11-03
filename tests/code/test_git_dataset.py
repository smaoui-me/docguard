import json
import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.dataset import evaluate_dataset, load_cases
from docguard.ai.files import ProposalError
from docguard.ai.provider import ProviderError
from docguard.cli import main

DATASET = Path(__file__).resolve().parents[2] / "evaluations/git_cases.toml"
CONFIG = AIConfig("groq", "test-model", "")


@pytest.mark.parametrize(
    "text",
    [
        "schema_version = true\ncases = []",
        "schema_version = 1\ncases = [1]",
        'schema_version = 1\n[[cases]]\nid="invalid"',
    ],
)
def test_invalid_dataset_shape_fails_explicitly(tmp_path, text):
    path = tmp_path / "bad.toml"
    path.write_text(text)
    with pytest.raises(ProposalError):
        load_cases(path)


def test_dataset_provenance_splits_and_gold_checks():
    cases = load_cases(DATASET)
    assert len(cases) == 30
    assert sum(case["split"] == "development" for case in cases) == 20
    assert sum(case["split"] == "reserved" for case in cases) == 10
    assert len({case["category"] for case in cases}) >= 10
    families = [
        {
            entity
            for case in cases
            if case["split"] == split
            for entity in case["entity_ids"]
        }
        for split in ("development", "reserved")
    ]
    assert families[0].isdisjoint(families[1])
    for case in cases:
        assert "synthetic" in case["provenance"]
        assert "pending" in case["review_status"]
        if case["action"] == "revise":
            assert case["required_patterns"]
            assert all(
                re.search(pattern, case["replacement"], re.I | re.S)
                for pattern in case["required_patterns"]
            )
            assert not any(
                re.search(pattern, case["replacement"], re.I | re.S)
                for pattern in case["forbidden_patterns"]
            )


def test_all_30_cases_through_git_offline(tmp_path):
    with patch("docguard.ai.dataset.generate") as api:
        report = evaluate_dataset(
            CONFIG, DATASET, tmp_path / "report.json", split="all"
        )
    assert report["passed"] == report["total"] == 30, report
    assert report["errors"] == report["not_run"] == report["api_requests"] == 0
    assert report["mode"] == "offline-fixtures"
    assert json.loads((tmp_path / "report.json").read_text()) == report
    api.assert_not_called()


def test_wrong_model_decision_is_not_hidden_by_gold_labels(tmp_path):
    seen = []

    def bad(model, context):
        seen.append(context)
        return {
            "action": "unchanged",
            "summary": "Incorrectly abstain",
            "content": None,
            "warnings": [],
            "evidence_ids": [context["evidence"][0]["id"]],
        }

    report = evaluate_dataset(
        CONFIG,
        DATASET,
        tmp_path / "report.json",
        selected=["timeout_parameter"],
        generator=bad,
    )
    assert report["passed"] == report["errors"] == 0
    assert not report["results"][0]["checks"]["expected_action"]
    assert (
        not {
            "rationale",
            "required_patterns",
            "replacement",
            "expected_action",
            "split",
        }
        & seen[0].keys()
    )


def test_auth_and_rate_limits_stop_and_record_not_run(tmp_path):
    for status in (401, 429):
        api = Mock(side_effect=ProviderError("Groq", status))
        report = evaluate_dataset(
            CONFIG,
            DATASET,
            tmp_path / f"{status}.json",
            selected=["timeout_parameter", "retry_default"],
            generator=api,
        )
        assert report["total"] == report["errors"] == report["not_run"] == 1
        assert report["passed"] == 0
        assert api.call_count == 1


def test_split_selection_budget_and_output_preflight(tmp_path):
    api = Mock()
    with patch("docguard.ai.dataset.create_case_repository") as create:
        for kwargs in (
            {"selected": ["not_a_case"]},
            {"selected": ["cache_ttl_default"]},
            {"split": "invalid"},
            {"live": True},
            {"max_requests": 0},
        ):
            with pytest.raises(ProposalError):
                evaluate_dataset(
                    CONFIG, DATASET, tmp_path / "report.json", generator=api, **kwargs
                )
        create.assert_not_called()
        api.assert_not_called()
        output = tmp_path / "exists.json"
        output.write_text("keep")
        with pytest.raises(ProposalError):
            evaluate_dataset(CONFIG, DATASET, output)
        assert output.read_text() == "keep"


def test_cli_offline_selected_case(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DOCGUARD_AI_PROVIDER=groq\nDOCGUARD_MODEL=test-model")
    output = tmp_path / "report.json"
    assert (
        main(
            [
                "evaluate-git",
                "--env-file",
                str(env),
                "--dataset",
                str(DATASET),
                "--case",
                "retry_default",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    assert json.loads(output.read_text())["total"] == 1
