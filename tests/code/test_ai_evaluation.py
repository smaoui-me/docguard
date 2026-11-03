import json
import os
from unittest.mock import Mock, patch

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.evaluation import NEW, documents_multiplier, evaluate
from docguard.ai.files import ProposalError
from docguard.ai.provider import ProviderError
from docguard.cli import main

CONFIG = AIConfig("groq", "openai/gpt-oss-120b", "")


@pytest.mark.parametrize(
    "text",
    [
        "price * 1.2",
        "multiplied by `1.2`",
        "price increased by 20%",
        "a 20% increase",
        "price INCREASED\nby 20 %",
    ],
)
def test_equivalent_multiplier_descriptions(text):
    assert documents_multiplier(text)


@pytest.mark.parametrize(
    "text",
    [
        "price unchanged",
        "price decreased by 20%",
        "price increased by 120%",
        "a 120% increase",
        "multiplied by 1.25",
        "multiplied by 11.2",
        "price increased by 20.5%",
    ],
)
def test_incorrect_multiplier_descriptions(text):
    assert not documents_multiplier(text)


def test_equivalent_percentage_passes_complete_revision_checks(tmp_path):
    report = evaluate(
        CONFIG,
        tmp_path / "percentage.json",
        generator=Mock(
            return_value={
                "action": "revise",
                "summary": "Reflect the implementation",
                "content": "# Prices\n\n`total(price)` returns price increased by 20%.\n\nContact the billing team for support.\n",
                "warnings": [],
            }
        ),
    )
    assert report["results"][0]["passed"]
    assert report["results"][3]["passed"]


def test_offline_evaluates_complete_pipeline_without_network(tmp_path):
    with patch("docguard.ai.evaluation.generate") as api:
        report = evaluate(CONFIG, tmp_path / "report.json")
    api.assert_not_called()
    assert report["mode"] == "offline-fixtures"
    assert report["passed"] == report["total"] == 4
    assert report["suite_version"] == 3
    assert report["prompt_version"] == 2
    assert json.loads((tmp_path / "report.json").read_text()) == report
    assert all(
        row["checks"]["generation_preserves_document"] for row in report["results"]
    )


def test_evaluator_detects_bad_decisions_and_preservation_failures(tmp_path):
    bad = Mock(
        return_value={
            "action": "revise",
            "summary": "Bad edit",
            "content": "PWNED",
            "warnings": [],
        }
    )
    report = evaluate(CONFIG, tmp_path / "report.json", generator=bad)
    assert report["passed"] == 0
    assert report["mode"] == "injected-test"
    assert bad.call_count == 4
    checks = report["results"][0]["checks"]
    assert not checks["multiplier_documented"]
    assert not checks["unrelated_prose_preserved"]
    assert "injection_not_followed" not in checks
    assert not report["results"][3]["checks"]["injection_not_followed"]


def test_missing_dependency_revision_fails_policy_without_multiplier_checks(tmp_path):
    decision = {
        "action": "revise",
        "summary": "Describe the visible call",
        "content": "`total(price)` returns external_transform(price).\n\nContact the billing team for support.\n",
        "warnings": ["The dependency is unknown."],
    }
    report = evaluate(
        CONFIG, tmp_path / "report.json", generator=Mock(return_value=decision)
    )
    row = report["results"][2]
    assert row["expected_action"] == "needs_review"
    assert not row["passed"]
    assert {key for key, value in row["checks"].items() if not value} == {
        "expected_action"
    }
    for key in ("multiplier_documented", "old_claim_removed", "injection_not_followed"):
        assert key not in row["checks"]


def test_non_revision_decisions_cannot_apply_and_do_not_change_documents(tmp_path):
    for action in ("unchanged", "needs_review"):
        report = evaluate(
            CONFIG,
            tmp_path / f"{action}.json",
            generator=Mock(
                return_value={
                    "action": action,
                    "summary": "Decision",
                    "content": None,
                    "warnings": [],
                }
            ),
        )
        for row in report["results"]:
            assert row["checks"]["non_revision_preview_rejected"]
            assert row["checks"]["non_revision_apply_rejected"]
            assert row["checks"]["non_revision_preserves_document"]
        # Caution is still a policy failure when documentation already matches.
        assert report["results"][1]["passed"] == (action == "unchanged")
        assert report["results"][2]["passed"] == (action == "needs_review")


def test_multiplier_revision_still_requires_supported_change(tmp_path):
    report = evaluate(
        CONFIG,
        tmp_path / "report.json",
        generator=Mock(
            return_value={
                "action": "revise",
                "summary": "Incorrect multiplier",
                "content": "Returns price multiplied by 9.\n\nContact the billing team for support.\n",
                "warnings": [],
            }
        ),
    )
    for index in (0, 3):
        assert not report["results"][index]["passed"]
        assert not report["results"][index]["checks"]["multiplier_documented"]


def test_errors_and_malformed_decisions_become_failed_cases(tmp_path):
    for index, generator in enumerate(
        [Mock(side_effect=ProposalError("secret")), Mock(return_value={})]
    ):
        report = evaluate(CONFIG, tmp_path / f"report{index}.json", generator=generator)
        assert report["passed"] == 0
        assert "secret" not in json.dumps(report)
        assert all("error" in row for row in report["results"])


def test_api_errors_are_distinct_from_quality_failures(tmp_path):
    report = evaluate(
        CONFIG,
        tmp_path / "report.json",
        generator=Mock(side_effect=ProviderError("Groq", 401)),
    )
    assert report["errors"] == 4
    assert report["passed"] == 0
    assert all(row["http_status"] == 401 for row in report["results"])


def test_evaluation_limits_and_existing_output_preflight(tmp_path):
    generator = Mock()
    output = tmp_path / "report.json"
    for count in (0, 6):
        with pytest.raises(ProposalError):
            evaluate(CONFIG, output, repeats=count, generator=generator)
    with pytest.raises(ProposalError, match="GROQ_API_KEY"):
        evaluate(CONFIG, output, live=True)
    output.write_text("keep")
    with pytest.raises(ProposalError):
        evaluate(CONFIG, output, generator=generator)
    assert output.read_text() == "keep"
    generator.assert_not_called()


def test_live_dispatch_and_repeats(tmp_path):
    with patch(
        "docguard.ai.evaluation.generate",
        return_value={
            "action": "revise",
            "summary": "update",
            "content": NEW,
            "warnings": [],
        },
    ) as api:
        report = evaluate(
            AIConfig("groq", "test-model", "test-key"),
            tmp_path / "live.json",
            live=True,
            repeats=2,
        )
    assert report["mode"] == "live"
    assert report["total"] == 8
    assert api.call_count == 8
    assert api.call_args.kwargs == {"provider": "groq", "api_key": "test-key"}


def test_cli_loads_env_and_exit_codes(tmp_path, capsys):
    env = tmp_path / ".env"
    env.write_text(
        "DOCGUARD_AI_PROVIDER=groq\nDOCGUARD_MODEL=openai/gpt-oss-120b\nGROQ_API_KEY="
    )
    with patch.dict(os.environ, {}, clear=True):
        args = [
            "evaluate-ai",
            "--env-file",
            str(env),
            "--output",
            str(tmp_path / "report.json"),
        ]
        assert main(args) == 0
        assert "offline-fixtures: 4/4" in capsys.readouterr().out
        assert main(args) == 2
        with patch(
            "docguard.cli.evaluate",
            return_value={"passed": 0, "total": 4, "mode": "live"},
        ):
            assert main(args) == 1
