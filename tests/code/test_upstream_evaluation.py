import json
from unittest.mock import Mock, patch

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository
from docguard.ai.experiment_packet import (
    load_labels,
    load_packet,
    prepare_packet,
    reference_labels,
)
from docguard.ai.files import ProposalError
from docguard.ai.provider import ProviderError
from docguard.ai.upstream import (
    evaluate_pr,
    extract_section,
    load_manifest,
    local_git,
    materialize_case,
    summarize,
)

CONFIG = AIConfig("groq", "test", "fake-key")


def test_review_packet_pins_real_git_evidence_without_leaking_provisional_labels(
    upstream, tmp_path
):
    repository, case = upstream
    manifest = write_manifest(tmp_path / "cases.toml", [case])
    output = tmp_path / "packet.json"
    prepare_packet([(manifest, repository)], output, [case["id"]])
    _, packet = load_packet(output)
    assert len(packet["cases"]) == 1
    row = packet["cases"][0]
    assert row["provenance"]["upstream_head"] == case["head"]
    assert row["contexts"]["mapped"]["document_text"].startswith("## Value")
    assert "expected_action" not in output.read_text()
    assert case["rationale"] not in output.read_text()
    assert row["exposure"] == "previously_inspected_regression"


def write_manifest(path, cases):
    lines = ["schema_version = 1"]
    for case in cases:
        lines.append("[[cases]]")
        lines.extend(
            key + " = " + json.dumps(value)
            for key, value in case.items()
            if key != "claims"
        )
        for claim in case.get("claims", []):
            lines.append("[[cases.claims]]")
            lines.extend(
                key + " = " + json.dumps(value) for key, value in claim.items()
            )
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def test_paired_reference_keeps_corrected_document_out_of_repair_input(
    upstream, tmp_path
):
    repository, case = upstream
    manifest = write_manifest(tmp_path / "paired.toml", [case])
    output = tmp_path / "packet.json"
    prepare_packet([(manifest, repository)], output, [case["id"]], paired_upstream=True)
    packet_hash, packet = load_packet(output)
    before, after = packet["cases"]
    assert before["group"] == after["group"]
    assert (
        before["contexts"]["mapped"]["document_text"] == "## Value\nDefaults to 1.\n\n"
    )
    assert (
        after["contexts"]["mapped"]["document_text"] == "## Value\nDefaults to 2.\n\n"
    )
    reference = before["upstream_reference"]
    assert reference == after["upstream_reference"]
    assert reference["documents"]["head"]["revision"] == case["head"]
    assert reference["documents"]["base"]["revision"] == case["base"]
    assert "Defaults to 2" not in json.dumps(before["contexts"])
    assert "Defaults to 2" in reference["diff"]
    labels = tmp_path / "labels.json"
    reference_labels(output, labels)
    _, rows = load_labels(labels, packet_hash, packet)
    assert [r["mapped"] for r in rows.values()] == ["revise", "unchanged"]
    assert all(
        r["reviewer"] == "" and r["review_level"] == "upstream_reference"
        for r in rows.values()
    )


def test_pair_requires_explicit_seed_and_rejects_ablation(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(
        tmp_path / "cases.toml", [{**case, "variant": "dependency_ablation"}]
    )
    with pytest.raises(ProposalError, match="explicit seed"):
        prepare_packet(
            [(manifest, repo)], tmp_path / "packet.json", [], paired_upstream=True
        )
    with pytest.raises(ProposalError, match="ablation"):
        prepare_packet(
            [(manifest, repo)],
            tmp_path / "packet.json",
            [case["id"]],
            paired_upstream=True,
        )


@pytest.fixture(scope="module")
def upstream(tmp_path_factory):
    root = tmp_path_factory.mktemp("upstream") / "repo"
    base, _ = create_case_repository(
        {
            "before": "def value(n=1):\n    return n\n",
            "after": 'raise RuntimeError("must never execute")\ndef value(n=2):\n    return n\n',
            "before_document": "# API\n\n## Value\nDefaults to 1.\n\n## Other\nKeep other section.\n",
            "document": "# API\n\n## Value\nDefaults to 2.\n\n## Other\nKeep other section.\n",
            "entity_ids": ["api.py:value"],
        },
        root,
    )
    (root / "LICENSE.md").write_text("Test fixture license notice.")
    local_git(root, "add", ".")
    local_git(root, "commit", "-m", "license fixture")
    head = local_git(root, "rev-parse", "HEAD").decode().strip()
    case = {
        "id": "example",
        "repository_url": "https://example.invalid/repo",
        "pr_url": "https://example.invalid/repo/pull/1",
        "base": base,
        "head": head,
        "license_path": "LICENSE.md",
        "document_path": "README.md",
        "section": "## Value",
        "variant": "authentic_head",
        "prefix": "",
        "source_paths": ["api.py"],
        "entity_ids": ["api.py:value"],
        "expected_action": "unchanged",
        "expected_detection": True,
        "review_status": "pending independent review",
        "rationale": "Current document already reflects the default.",
        "required_patterns": ["2"],
        "forbidden_patterns": ["Defaults to 1"],
        "preserve": ["## Value"],
    }
    return root, case


def test_pair_rejects_unchanged_docs_and_duplicate_seeds(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(tmp_path / "same.toml", [{**case, "head": case["base"]}])
    with pytest.raises(ProposalError, match="changed documentation section"):
        prepare_packet(
            [(manifest, repo)],
            tmp_path / "packet.json",
            [case["id"]],
            paired_upstream=True,
        )
    manifest = write_manifest(
        tmp_path / "duplicates.toml",
        [case, {**case, "id": "duplicate", "variant": "base_docs"}],
    )
    with pytest.raises(ProposalError, match="one seed"):
        prepare_packet(
            [(manifest, repo)],
            tmp_path / "packet.json",
            [case["id"], "duplicate"],
            paired_upstream=True,
        )


def test_projection_preserves_sources_and_tracks_doc_selection(upstream, tmp_path):
    repository, case = upstream
    original = local_git(repository, "status", "--porcelain")
    target = tmp_path / "projection"
    provenance = materialize_case(repository, case, target)
    assert (target / "api.py").read_bytes() == local_git(
        repository, "show", case["head"] + ":api.py"
    )
    assert (target / "README.md").read_text() == "## Value\nDefaults to 2.\n\n"
    assert provenance["document_selections"]["head"]["start_line"] == 3
    assert provenance["document_selections"]["head"]["end_line"] == 5
    assert provenance["upstream_head"] == case["head"]
    assert provenance["projection_commits"]["head"] != case["head"]
    assert (
        target / "UPSTREAM-LICENSE.txt"
    ).read_text() == "Test fixture license notice."
    assert local_git(repository, "status", "--porcelain") == original


@pytest.mark.parametrize(
    "variant,prefix,expected",
    [
        ("base_docs", "", "Defaults to 1."),
        ("authored_stale_claim", "Authored stale claim.\n", "Authored stale claim."),
        ("dependency_ablation", "Unknown behavior.\n", "Unknown behavior."),
    ],
)
def test_variants_are_explicit_and_reproducible(
    upstream, tmp_path, variant, prefix, expected
):
    repo, case = upstream
    changed = {**case, "variant": variant, "prefix": prefix}
    provenance = materialize_case(repo, changed, tmp_path / "projection")
    assert expected in (tmp_path / "projection" / "README.md").read_text()
    assert provenance["variant"] == variant
    assert provenance["document_selections"]["head"]["authored_prefix"] == prefix


def test_preparation_only_never_scores_a_model_or_calls_network(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(tmp_path / "case.toml", [case])
    with patch("docguard.ai.upstream.generate") as api:
        report = evaluate_pr(CONFIG, repo, manifest, tmp_path / "report.json")
    api.assert_not_called()
    assert report["mode"] == "preparation-only"
    assert report["api_requests"] == 0
    assert report["metrics"]["action_accuracy"]["value"] is None
    context = json.loads(report["results"][0]["requests"][0]["messages"][1]["content"])
    assert (
        not {"rationale", "expected_action", "review_status", "required_patterns"}
        & context.keys()
    )
    assert "fake-key" not in json.dumps(report)


def test_live_mock_collects_usage_and_reports_decision_without_leaking_key(
    upstream, tmp_path
):
    repo, case = upstream

    def response(model, context, **kwargs):
        kwargs["usage_sink"](
            {"input_tokens": 100, "output_tokens": 20, "total_tokens": 120}
        )
        return {
            "action": "unchanged",
            "summary": "Already correct",
            "content": None,
            "warnings": [],
            "evidence_ids": [context["evidence"][-1]["id"]],
        }

    with patch("docguard.ai.upstream.generate", side_effect=response):
        report = evaluate_pr(
            CONFIG,
            repo,
            write_manifest(tmp_path / "case.toml", [case]),
            tmp_path / "report.json",
            live=True,
        )
    assert report["api_requests"] == 1
    assert report["metrics"]["action_accuracy"]["value"] == 1.0
    assert report["metrics"]["edit_recall_completed_cases"]["value"] is None
    assert report["metrics"]["semantic_correctness"] is None
    assert report["results"][0]["token_usage"][0]["total_tokens"] == 120
    assert report["results"][0]["human_review"]["status"] == "pending"
    assert "fake-key" not in json.dumps(report)


def test_revision_checked_without_mutating_upstream(upstream, tmp_path):
    repo, case = upstream
    changed = {**case, "variant": "base_docs", "expected_action": "revise"}

    def response(model, context):
        return {
            "action": "revise",
            "summary": "Default changed",
            "content": context["document_text"].replace("1.", "2."),
            "warnings": [],
            "evidence_ids": [context["evidence"][-1]["id"]],
        }

    before = local_git(repo, "status", "--porcelain")
    report = evaluate_pr(
        CONFIG,
        repo,
        write_manifest(tmp_path / "case.toml", [changed]),
        tmp_path / "report.json",
        generator=response,
    )
    assert report["results"][0]["automatic_pass"]
    assert report["results"][0]["checks"]["preview_preserves_document"]
    assert local_git(repo, "status", "--porcelain") == before


def test_invalid_citations_and_rate_limits_are_not_quality_successes(
    upstream, tmp_path
):
    repo, case = upstream
    cases = [case, {**case, "id": "second"}]
    manifest = write_manifest(tmp_path / "cases.toml", cases)
    bad = Mock(
        return_value={
            "action": "unchanged",
            "summary": "claim",
            "content": None,
            "warnings": [],
            "evidence_ids": ["invented"],
        }
    )
    invalid = evaluate_pr(
        CONFIG, repo, manifest, tmp_path / "invalid.json", generator=bad
    )
    assert invalid["errors"] == 2
    assert invalid["metrics"]["citation_validity"]["value"] == 0
    assert invalid["metrics"]["completion_coverage"]["value"] == 0
    limited = evaluate_pr(
        CONFIG,
        repo,
        manifest,
        tmp_path / "limited.json",
        generator=Mock(side_effect=ProviderError("Groq", 429)),
    )
    assert limited["not_run"] == 1
    assert limited["metrics"]["action_accuracy"]["value"] is None


def test_invalid_pin_preflight_makes_zero_calls(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(
        tmp_path / "cases.toml", [case, {**case, "id": "missing", "head": "0" * 40}]
    )
    api = Mock()
    with pytest.raises(ProposalError):
        evaluate_pr(CONFIG, repo, manifest, tmp_path / "report.json", generator=api)
    api.assert_not_called()
    assert not (tmp_path / "report.json").exists()


@pytest.mark.parametrize(
    "change",
    [
        {"head": "main"},
        {"prefix": "not authentic"},
        {"source_paths": ["../secret.py"]},
        {"source_paths": ["api.py", "api.py"]},
        {"document_path": "bad.txt"},
        {"expected_detection": 1},
    ],
)
def test_bad_manifest_rejected(upstream, tmp_path, change):
    case = {**upstream[1], **change}
    with pytest.raises(ProposalError):
        load_manifest(write_manifest(tmp_path / "case.toml", [case]))


def test_section_boundaries_and_ambiguous_headings():
    raw = b"# Top\n## Target\n```md\n## example\n```\n### Child\nText\n## Next\nOther\n"
    selected, start, end = extract_section(raw, "## Target")
    assert start == 2 and end == 7
    assert b"## example" in selected and b"## Next" not in selected
    with pytest.raises(ProposalError):
        extract_section(b"## Same\n## Same\n", "## Same")
    with pytest.raises(ProposalError):
        extract_section(raw, "## Missing")


def test_metrics_denominators_do_not_hide_errors():
    rows = []
    for expected, actual in [
        ("revise", "revise"),
        ("revise", "unchanged"),
        ("unchanged", "revise"),
        ("needs_review", "needs_review"),
    ]:
        rows.append(
            {
                "status": "completed",
                "expected_action": expected,
                "action": actual,
                "automatic_pass": expected == actual,
                "detected": True,
                "expected_detection": True,
                "citations_valid": True,
            }
        )
    rows.append({"status": "api_error", "detected": True, "expected_detection": True})
    result = summarize(rows, 6)
    assert result["completion_coverage"] == {
        "numerator": 4,
        "denominator": 6,
        "value": 4 / 6,
    }
    assert result["edit_precision"]["value"] == 0.5
    assert result["edit_recall_completed_cases"]["value"] == 0.5
    assert result["unnecessary_edit_rate"]["value"] == 1
    assert result["required_abstention_recall"]["value"] == 1
    assert result["action_accuracy"]["value"] == 0.5


def test_budget_and_existing_output_preflight(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(tmp_path / "case.toml", [case])
    with patch("docguard.ai.upstream.materialize_case") as materialize:
        with pytest.raises(ProposalError):
            evaluate_pr(CONFIG, repo, manifest, tmp_path / "out.json", max_requests=0)
        output = tmp_path / "exists.json"
        output.write_text("keep")
        with pytest.raises(ProposalError):
            evaluate_pr(CONFIG, repo, manifest, output)
        materialize.assert_not_called()


def unchanged_response(model, context, **kwargs):
    if "usage_sink" in kwargs:
        kwargs["usage_sink"]({"total_tokens": 12})
    return {
        "action": "unchanged",
        "summary": "Already correct",
        "content": None,
        "warnings": [],
        "evidence_ids": [context["evidence"][-1]["id"]],
    }


def test_checkpoint_survives_interrupt_and_resume_skips_completed(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(tmp_path / "cases.toml", [case, {**case, "id": "second"}])
    output = tmp_path / "report.json"
    count = 0

    def interrupted(model, context, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            saved = json.loads(output.read_text())
            assert saved["results"][0]["status"] == "completed"
            assert saved["attempts"][-1]["status"] == "in_flight"
            raise KeyboardInterrupt()
        return unchanged_response(model, context, **kwargs)

    with patch("docguard.ai.upstream.generate", side_effect=interrupted):
        with pytest.raises(KeyboardInterrupt):
            evaluate_pr(CONFIG, repo, manifest, output, live=True)
    assert not output.with_name(output.name + ".lock").exists()
    first = json.loads(output.read_text())["results"][0]
    with patch("docguard.ai.upstream.generate", side_effect=unchanged_response) as api:
        report = evaluate_pr(
            CONFIG, repo, manifest, output, live=True, resume=True, max_requests=1
        )
    assert api.call_count == 1
    assert report["results"][0] == first
    assert report["api_requests"] == 3
    assert report["session_requests"] == 1
    assert report["token_usage"]["total_tokens"] == 24
    assert report["metrics"]["completion_coverage"]["value"] == 1
    with patch("docguard.ai.upstream.generate") as api:
        evaluate_pr(CONFIG, repo, manifest, output, live=True, resume=True)
    api.assert_not_called()


@pytest.mark.parametrize(
    "status,delay,retries,budget,expected_calls,waits",
    [
        (429, 2, 2, 3, 3, [2, 2]),
        (429, 120, 2, 3, 1, []),
        (429, None, 2, 3, 3, [1, 2]),
        (429, 0, 5, 1, 1, []),
        (429, 0, 0, 3, 1, []),
        (401, 0, 2, 3, 1, []),
        (403, 0, 2, 3, 1, []),
        (500, 0, 2, 3, 1, []),
    ],
)
def test_retry_bounds_and_budget(
    upstream, tmp_path, status, delay, retries, budget, expected_calls, waits
):
    repo, case = upstream
    manifest = write_manifest(tmp_path / "case.toml", [case])
    api = Mock(side_effect=ProviderError("Groq", status, delay))
    with patch("docguard.ai.upstream.sleep") as sleep:
        report = evaluate_pr(
            CONFIG,
            repo,
            manifest,
            tmp_path / "report.json",
            generator=api,
            max_retries=retries,
            max_requests=budget,
        )
    assert api.call_count == expected_calls
    assert [call.args[0] for call in sleep.call_args_list] == waits
    assert report["results"][0]["status"] == "api_error"
    assert report["metrics"]["action_accuracy"]["value"] is None
    assert len(report["attempts"]) == expected_calls


def test_retry_then_success_and_resume_preserves_quality_failure(upstream, tmp_path):
    repo, case = upstream
    # Deliberately wrong gold label: a completed failed evaluation must not be re-rolled.
    manifest = write_manifest(
        tmp_path / "case.toml", [{**case, "expected_action": "revise"}]
    )
    output = tmp_path / "report.json"
    calls = 0

    def response(model, context):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ProviderError("Groq", 429, 0)
        return unchanged_response(model, context)

    with patch("docguard.ai.upstream.sleep"):
        report = evaluate_pr(CONFIG, repo, manifest, output, generator=response)
    assert calls == 2
    assert report["results"][0]["status"] == "completed"
    assert not report["results"][0]["automatic_pass"]
    api = Mock()
    resumed = evaluate_pr(CONFIG, repo, manifest, output, generator=api, resume=True)
    api.assert_not_called()
    assert resumed["results"] == report["results"]


def test_resume_rejects_changed_identity_before_git_or_api(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(tmp_path / "case.toml", [case])
    output = tmp_path / "report.json"
    evaluate_pr(CONFIG, repo, manifest, output)
    original = output.read_bytes()
    for config, kwargs in [
        (AIConfig("groq", "different", "key"), {}),
        (CONFIG, {"live": True}),
        (CONFIG, {"selected": ["example"]}),
    ]:
        # Selecting the same set is equivalent, so alter the prompt hash for that case.
        patcher = patch(
            "docguard.ai.upstream.GIT_PROMPT_VERSION",
            99 if kwargs.get("selected") else 1,
        )
        with patcher, patch("docguard.ai.upstream.materialize_case") as materialize:
            with pytest.raises(ProposalError, match="mismatch"):
                evaluate_pr(config, repo, manifest, output, resume=True, **kwargs)
            materialize.assert_not_called()
        assert output.read_bytes() == original
    manifest.write_text(manifest.read_text() + "\n# changed labels or dataset\n")
    with pytest.raises(ProposalError, match="mismatch"):
        evaluate_pr(CONFIG, repo, manifest, output, resume=True)


def test_atomic_checkpoint_failure_and_lock_preserve_report(upstream, tmp_path):
    from docguard.ai.upstream import _checkpoint

    output = tmp_path / "report.json"
    output.write_text('{"keep": true}')
    with patch("docguard.ai.upstream.os.replace", side_effect=OSError("disk failure")):
        with pytest.raises(OSError):
            _checkpoint(output, {"replacement": True})
    assert json.loads(output.read_text()) == {"keep": True}
    assert list(tmp_path.iterdir()) == [output]
    lock = output.with_name(output.name + ".lock")
    lock.write_text("another process")
    with pytest.raises(ProposalError, match="locked"):
        evaluate_pr(CONFIG, upstream[0], tmp_path / "unused.toml", output, resume=True)
    assert lock.read_text() == "another process"


def test_related_prs_cannot_cross_splits(upstream, tmp_path):
    case = upstream[1]
    manifest = write_manifest(
        tmp_path / "cases.toml",
        [
            {**case, "split": "development"},
            {**case, "id": "second", "split": "held_out"},
        ],
    )
    with pytest.raises(ProposalError, match="cross"):
        load_manifest(manifest)


def test_checked_in_benchmark_groups_and_labels():
    from pathlib import Path

    groups = {}
    repositories = set()
    for path in Path("evaluations/upstream").glob("*.toml"):
        for case in load_manifest(path):
            repositories.add(case["repository_url"])
            for group in (case["pr_url"], case["repository_url"] + case["group"]):
                assert groups.setdefault(group, case["split"]) == case["split"]
            assert "pending" in case["review_status"]
    assert len(repositories) >= 2


def test_cli_routes_resume_and_retry_options(tmp_path):
    from docguard.cli import main

    output = tmp_path / "report.json"
    with (
        patch("docguard.cli.load_config", return_value=CONFIG),
        patch(
            "docguard.cli.evaluate_pr",
            return_value={
                "mode": "live",
                "api_requests": 1,
                "errors": 0,
                "not_run": 0,
                "results": [],
            },
        ) as evaluate,
    ):
        assert (
            main(
                [
                    "evaluate-pr",
                    "--repository",
                    str(tmp_path),
                    "--output",
                    str(output),
                    "--live",
                    "--resume",
                    "--max-retries",
                    "1",
                    "--max-retry-wait",
                    "7",
                    "--max-requests",
                    "2",
                ]
            )
            == 0
        )
    assert evaluate.call_args.kwargs["resume"] is True
    assert evaluate.call_args.kwargs["max_retries"] == 1
    assert evaluate.call_args.kwargs["max_retry_wait"] == 7
    assert evaluate.call_args.kwargs["max_requests"] == 2


@pytest.mark.parametrize(
    "options",
    [
        {"max_retries": -1},
        {"max_retries": 6},
        {"max_retry_wait": -1},
        {"max_retry_wait": 61},
        {"max_retry_wait": float("nan")},
    ],
)
def test_invalid_retry_options_fail_before_preflight(tmp_path, options):
    with patch("docguard.ai.upstream.materialize_case") as materialize:
        with pytest.raises(ProposalError, match="Retry bounds"):
            evaluate_pr(
                CONFIG,
                tmp_path,
                tmp_path / "unused.toml",
                tmp_path / "out.json",
                **options,
            )
    materialize.assert_not_called()


def test_corrupt_resume_is_rejected_before_preflight(upstream, tmp_path):
    repo, case = upstream
    manifest = write_manifest(tmp_path / "case.toml", [case])
    output = tmp_path / "out.json"
    evaluate_pr(CONFIG, repo, manifest, output)
    report = json.loads(output.read_text())
    report["results"][0]["status"] = "invented"
    output.write_text(json.dumps(report))
    original = output.read_bytes()
    with patch("docguard.ai.upstream.materialize_case") as materialize:
        with pytest.raises(ProposalError, match="Invalid checkpoint"):
            evaluate_pr(CONFIG, repo, manifest, output, resume=True)
    materialize.assert_not_called()
    assert output.read_bytes() == original


def test_preservation_findings_do_not_masquerade_as_semantic_failures(
    upstream, tmp_path
):
    repo, case = upstream
    changed = {**case, "variant": "base_docs", "expected_action": "revise"}

    def response(model, context):
        return {
            "action": "revise",
            "summary": "Update default",
            "content": context["document_text"].replace("1.", "2.").rstrip() + "\n",
            "warnings": [],
            "evidence_ids": [context["evidence"][-1]["id"]],
        }

    report = evaluate_pr(
        CONFIG,
        repo,
        write_manifest(tmp_path / "case.toml", [changed]),
        tmp_path / "out.json",
        generator=response,
    )
    row = report["results"][0]
    assert row["automatic_pass"] is True
    assert row["preservation"]["issues"] == ["trailing_newlines_changed"]
    assert row["human_review"]["accepted"] is None


def test_explicit_requirements_route_without_credentials_or_api_and_resume(
    upstream, tmp_path
):
    repo, case = upstream
    case = {
        **case,
        "expected_action": "needs_review",
        "claims": [
            {
                "id": "default",
                "quote": "Defaults to 2.",
                "required_evidence": ["after:missing.py:helper"],
            }
        ],
    }
    manifest = write_manifest(tmp_path / "claims.toml", [case])
    output = tmp_path / "report.json"
    config = AIConfig("groq", "test", "")
    with patch("docguard.ai.upstream.generate") as api:
        report = evaluate_pr(config, repo, manifest, output, live=True)
        resumed = evaluate_pr(config, repo, manifest, output, live=True, resume=True)
    api.assert_not_called()
    row = report["results"][0]
    assert row["detected"] is True
    assert row["action"] == "needs_review"
    assert row["automatic_pass"] is True
    assert row["decision_source"] == "deterministic_gate"
    assert report["api_requests"] == resumed["api_requests"] == 0
    assert report["token_usage"]["total_tokens"] is None


def test_credentials_still_required_when_gate_is_ready(upstream, tmp_path):
    repo, case = upstream
    case = {
        **case,
        "claims": [
            {
                "id": "default",
                "quote": "Defaults to 2.",
                "required_evidence": ["after:api.py:value"],
            }
        ],
    }
    with patch("docguard.ai.upstream.generate") as api:
        with pytest.raises(ProposalError, match="credentials"):
            evaluate_pr(
                AIConfig("groq", "test", ""),
                repo,
                write_manifest(tmp_path / "claims.toml", [case]),
                tmp_path / "report.json",
                live=True,
            )
    api.assert_not_called()
