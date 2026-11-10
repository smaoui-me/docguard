import json
from unittest.mock import patch

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.files import ProposalError, digest
from docguard.ai.pilot import compare_decisions, run_pilot

CONFIG = AIConfig("groq", "test", "fake")


def test_comparison_has_common_denominators_and_does_not_hide_failures():
    rows = [
        {"status": "completed", "expected_action": "revise", "action": "revise"},
        {"status": "completed", "expected_action": "unchanged", "action": "revise"},
        {
            "status": "completed",
            "expected_action": "needs_review",
            "action": "needs_review",
        },
        {"status": "api_error", "expected_action": "revise"},
    ]
    result = compare_decisions(rows)
    assert (result["completed"], result["selected"]) == (3, 4)
    assert result["docguard"]["action_agreement"]["numerator"] == 2
    assert result["docguard"]["unnecessary_edits"]["value"] == 1
    assert result["leave_docs_unchanged"]["missed_edits"]["value"] == 1
    assert (
        result["route_every_change_to_review"]["appropriate_abstention"]["value"] == 1
    )
    assert compare_decisions([])["docguard"]["action_agreement"]["value"] is None


def fixtures(tmp_path):
    manifest = tmp_path / "manifest.toml"
    manifest.write_text("fixture manifest")
    cases = [
        dict(
            id=f"case_{n}",
            expected_action="revise",
            pr_url=f"https://github.com/a/b/pull/{n}",
        )
        for n in range(3)
    ]
    calls = []

    def evaluate(config, repo, manifest, output, **kwargs):
        identity = json.loads((output.parent / "report.json").read_text())["identity"]
        case_identity = dict(
            identity,
            cases=kwargs["selected"],
            manifest_sha256=digest(manifest.read_bytes()),
        )
        name = kwargs["selected"][0]
        prior = json.loads(output.read_text()) if output.exists() else None
        count = 0 if prior and prior["results"][0]["status"] == "completed" else 1
        calls.append((name, count, kwargs["max_requests"]))
        report = {
            "identity": case_identity,
            "results": [
                {
                    "case": name,
                    "status": "completed",
                    "expected_action": "revise",
                    "action": "revise",
                    "automatic_pass": True,
                }
            ],
            "session_requests": count,
        }
        output.write_text(json.dumps(report))
        return report

    return manifest, cases, calls, evaluate


def test_budget_resume_and_completed_requests_not_duplicated(tmp_path):
    manifest, cases, calls, evaluator = fixtures(tmp_path)
    output = tmp_path / "run"
    with (
        patch("docguard.ai.pilot.load_manifest", return_value=cases),
        patch("docguard.ai.pilot.evaluate_pr", side_effect=evaluator),
        patch("docguard.ai.pilot.time.sleep") as sleep,
    ):
        report = run_pilot(
            CONFIG,
            [(manifest, tmp_path)],
            output,
            live=True,
            max_requests=1,
            progress=lambda _: None,
        )
        assert report["session_requests"] == 1
        assert [r["status"] for r in report["results"]] == [
            "completed",
            "not_run",
            "not_run",
        ]
        assert report["stop_reason"] == "Session request budget exhausted"
        resumed = run_pilot(
            CONFIG,
            [(manifest, tmp_path)],
            output,
            live=True,
            resume=True,
            max_requests=2,
            progress=lambda _: None,
        )
    assert resumed["comparisons"]["unassisted"]["completed"] == 3
    assert sum(count for _, count, _ in calls) == 3
    assert all(call.args[0] <= 10 for call in sleep.call_args_list)
    assert "provisional" in (output / "summary.md").read_text()
    assert not (output / "pilot.lock").exists()


def test_mismatch_lock_and_modified_case_checkpoint_rejected(tmp_path):
    manifest, cases, _, evaluator = fixtures(tmp_path)
    output = tmp_path / "run"
    with (
        patch("docguard.ai.pilot.load_manifest", return_value=cases),
        patch("docguard.ai.pilot.evaluate_pr", side_effect=evaluator),
    ):
        run_pilot(
            CONFIG,
            [(manifest, tmp_path)],
            output,
            live=True,
            max_requests=1,
            delay_seconds=0,
            progress=lambda _: None,
        )
        with pytest.raises(ProposalError, match="configuration mismatch"):
            run_pilot(
                AIConfig("groq", "other", "fake"),
                [(manifest, tmp_path)],
                output,
                live=True,
                resume=True,
            )
        checkpoint = output / "case_0.json"
        saved = json.loads(checkpoint.read_text())
        saved["identity"]["git_prompt_version"] = -1
        checkpoint.write_text(json.dumps(saved))
        with pytest.raises(ProposalError, match="Invalid case checkpoint"):
            run_pilot(CONFIG, [(manifest, tmp_path)], output, live=True, resume=True)
        (output / "pilot.lock").touch()
        with pytest.raises(ProposalError, match="locked"):
            run_pilot(CONFIG, [(manifest, tmp_path)], output, live=True, resume=True)


def test_contract_results_stay_separate_and_429_stops(tmp_path):
    manifest, cases, _, evaluator = fixtures(tmp_path)
    cases[0]["claims"] = [{"id": "contract"}]

    def limited(*args, **kwargs):
        report = evaluator(*args, **kwargs)
        report["results"][0].update(status="api_error", http_status=429)
        return report

    with (
        patch("docguard.ai.pilot.load_manifest", return_value=cases),
        patch("docguard.ai.pilot.evaluate_pr", side_effect=limited) as api,
    ):
        report = run_pilot(
            CONFIG,
            [(manifest, tmp_path)],
            tmp_path / "run",
            live=True,
            progress=lambda _: None,
        )
    assert api.call_count == 1 and report["stop_reason"] == "Stopped on HTTP 429"
    assert report["comparisons"]["contract_assisted"]["selected"] == 1
    assert report["comparisons"]["unassisted"]["selected"] == 2
    assert report["comparisons"]["contract_assisted"]["completed"] == 0


def test_existing_output_and_unknown_case_rejected(tmp_path):
    manifest, cases, _, _ = fixtures(tmp_path)
    with patch("docguard.ai.pilot.load_manifest", return_value=cases):
        with pytest.raises(ProposalError, match="Unknown|unknown"):
            run_pilot(
                CONFIG, [(manifest, tmp_path)], tmp_path / "run", selected=["missing"]
            )
        with pytest.raises(ProposalError, match="new output"):
            run_pilot(CONFIG, [(manifest, tmp_path)], tmp_path)


def test_interruption_after_case_checkpoint_can_resume_without_new_request(tmp_path):
    manifest, cases, calls, evaluator = fixtures(tmp_path)
    output = tmp_path / "run"

    def interrupted(*args, **kwargs):
        evaluator(*args, **kwargs)
        raise KeyboardInterrupt

    with patch("docguard.ai.pilot.load_manifest", return_value=cases[:1]):
        with patch("docguard.ai.pilot.evaluate_pr", side_effect=interrupted):
            with pytest.raises(KeyboardInterrupt):
                run_pilot(
                    CONFIG,
                    [(manifest, tmp_path)],
                    output,
                    live=True,
                    progress=lambda _: None,
                )
        assert not (output / "pilot.lock").exists()
        with patch("docguard.ai.pilot.evaluate_pr", side_effect=evaluator):
            report = run_pilot(
                CONFIG,
                [(manifest, tmp_path)],
                output,
                live=True,
                resume=True,
                progress=lambda _: None,
            )
    assert report["session_requests"] == 0
    assert sum(count for _, count, _ in calls) == 1
    assert report["results"][0]["status"] == "completed"


def test_manifest_change_and_malformed_checkpoint_fail_before_api(tmp_path):
    manifest, cases, _, evaluator = fixtures(tmp_path)
    output = tmp_path / "run"
    with patch("docguard.ai.pilot.load_manifest", return_value=cases[:1]):
        with patch("docguard.ai.pilot.evaluate_pr", side_effect=evaluator):
            run_pilot(
                CONFIG,
                [(manifest, tmp_path)],
                output,
                live=True,
                progress=lambda _: None,
            )
        checkpoint = output / "case_0.json"
        data = json.loads(checkpoint.read_text())
        data["results"] = []
        checkpoint.write_text(json.dumps(data))
        with patch("docguard.ai.pilot.evaluate_pr") as api:
            with pytest.raises(ProposalError, match="checkpoint results"):
                run_pilot(
                    CONFIG, [(manifest, tmp_path)], output, live=True, resume=True
                )
            manifest.write_text("changed manifest")
            with pytest.raises(ProposalError, match="configuration mismatch"):
                run_pilot(
                    CONFIG, [(manifest, tmp_path)], output, live=True, resume=True
                )
            api.assert_not_called()
