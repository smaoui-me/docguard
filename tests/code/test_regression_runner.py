"""Exercise orchestration without Git, sleeps, credentials, or paid requests."""

import json
import runpy
from pathlib import Path
from unittest.mock import Mock

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.files import digest
from docguard.ai.upstream import summarize


@pytest.fixture
def experiment(tmp_path, monkeypatch):
    main = runpy.run_path(str(Path("examples/evaluate_regression.py").resolve()))[
        "main"
    ]
    monkeypatch.chdir(tmp_path)
    cases = {"httpx": {"id": "a"}, "click": {"id": "b"}}
    reports, rows = [], []
    for name, case in cases.items():
        manifest = Path(f"evaluations/upstream/{name}.toml")
        manifest.parent.mkdir(parents=True, exist_ok=True)
        manifest.write_text("fixture", encoding="utf-8")
        report = Path(f"old-{name}.json")
        report.write_text(
            json.dumps(
                {
                    "identity": {"cases": [case["id"]]},
                    "manifest_sha256": digest(manifest.read_bytes()),
                }
            )
        )
        reports.append(str(report))
        rows.append(
            {
                "case": case["id"],
                "status": "completed",
                "action": "unchanged",
                "expected_action": "unchanged",
                "automatic_pass": True,
            }
        )
    baseline = {
        "provider": "groq",
        "model": "test",
        "results": rows,
        "case_reports": reports,
        "metrics": summarize(rows, 2),
    }
    Path("baseline.json").write_text(json.dumps(baseline))
    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--baseline",
            "baseline.json",
            "--output",
            "candidate.json",
            "--live",
        ],
    )
    monkeypatch.setitem(
        main.__globals__, "load_config", lambda: AIConfig("groq", "test", "secret")
    )
    monkeypatch.setitem(main.__globals__, "load_manifest", lambda p: [cases[p.stem]])
    monkeypatch.setattr("time.monotonic", Mock(side_effect=range(0, 10000, 100)))
    return main, baseline


def test_runner_preserves_baseline_and_resumes_case_checkpoints(
    experiment, monkeypatch
):
    main, baseline = experiment
    original = Path("baseline.json").read_bytes()
    Path("candidate-a.json").write_text("existing checkpoint")

    def evaluate(config, repo, manifest, output, **kwargs):
        row = next(r for r in baseline["results"] if r["case"] == kwargs["selected"][0])
        assert kwargs["resume"] == (row["case"] == "a")
        assert kwargs["max_retries"] == 1
        assert kwargs["max_retry_wait"] == 60
        return {"session_requests": 0 if kwargs["resume"] else 1, "results": [row]}

    api = Mock(side_effect=evaluate)
    monkeypatch.setitem(main.__globals__, "evaluate_pr", api)
    main()
    report = json.loads(Path("candidate.json").read_text())
    assert report["api_requests_this_session"] == 1
    assert report["metrics"]["action_accuracy"]["value"] == 1
    assert len(report["comparison"]) == 2
    assert "secret" not in Path("candidate.json").read_text()
    assert Path("baseline.json").read_bytes() == original


@pytest.mark.parametrize("failure", ["manifest", "model", "existing_output"])
def test_runner_rejects_incompatible_experiment_before_requests(
    experiment, monkeypatch, failure
):
    main, _ = experiment
    if failure == "manifest":
        Path("evaluations/upstream/httpx.toml").write_text("changed gold")
    elif failure == "model":
        monkeypatch.setitem(
            main.__globals__, "load_config", lambda: AIConfig("groq", "different", "")
        )
    else:
        Path("candidate.json").write_text("existing report")
    api = Mock()
    monkeypatch.setitem(main.__globals__, "evaluate_pr", api)
    with pytest.raises(SystemExit):
        main()
    api.assert_not_called()


def test_runner_stops_on_rate_limit_and_counts_unrun_cases(experiment, monkeypatch):
    main, _ = experiment
    api = Mock(
        return_value={
            "session_requests": 2,
            "results": [{"case": "a", "status": "api_error", "http_status": 429}],
        }
    )
    monkeypatch.setitem(main.__globals__, "evaluate_pr", api)
    main()
    report = json.loads(Path("candidate.json").read_text())
    assert report["api_requests_this_session"] == 2
    assert report["results"][-1] == {"case": "b", "status": "not_run"}
    assert report["metrics"]["completion_coverage"]["denominator"] == 2
    assert report["stop_reason"] == "Stopped on HTTP 429"
    api.assert_called_once()
