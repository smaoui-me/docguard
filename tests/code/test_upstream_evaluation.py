import json
from unittest.mock import Mock, patch

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository
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


def write_manifest(path, cases):
    lines = ["schema_version = 1"]
    for case in cases:
        lines.append("[[cases]]")
        lines.extend(key + " = " + json.dumps(value) for key, value in case.items())
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


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
