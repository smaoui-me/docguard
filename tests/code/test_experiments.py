import json
import os
from unittest.mock import Mock

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.experiment_packet import load_labels, load_packet, reference_labels
from docguard.ai.experiments import run_experiment, score_experiment
from docguard.ai.files import ProposalError, digest
from docguard.ai.provider import ProviderError
from docguard.ai.reference_benchmark import evaluate_reference, judge_result
from docguard.ai.references import load_discussions
from docguard.ai.review_ui import render_review_ui

CONFIG = AIConfig("groq", "test-model", "test-key")


def reference_judgment(context):
    return {
        "same_direction": True,
        "covers_reference_change": True,
        "contradicts_reference": False,
        "unsupported_additions": False,
        "preserves_unrelated": True,
        "explanation": "The candidate and upstream correction express the same multiplier.",
        "reference_quote": "factor is 1.2",
        "candidate_quote": "multiplied by 1.2",
        "missing_or_conflicting_claims": [],
    }


def test_automatic_reference_comparison_requires_no_human_labels_and_resumes(
    review_files, tmp_path
):
    packet, labels = review_files
    attach_reference(packet, labels)
    folder = tmp_path / "automatic"
    generated, judged = Mock(side_effect=response), Mock(side_effect=reference_judgment)
    first = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=generated,
        judge=judged,
        max_requests=1,
        delay_seconds=0,
    )
    assert first["stop_reason"] == "request_budget"
    assert generated.call_count == 1 and judged.call_count == 0
    second = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=generated,
        judge=judged,
        resume=True,
        delay_seconds=0,
    )
    assert generated.call_count == 1 and judged.call_count == 1
    assert second["metrics"]["overall"]["aligned"] == 1
    assert second["phase"] == "complete"
    assert "HIDDEN_REFERENCE_FIX" in judged.call_args.args[0]["reference_document"]
    assert "HIDDEN_REFERENCE_FIX" not in json.dumps(generated.call_args.args[2])
    assert (folder / "comparison.html").exists()
    third = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=generated,
        judge=judged,
        resume=True,
        delay_seconds=0,
    )
    assert third["session_requests"] == 0


@pytest.mark.parametrize(
    "field,value",
    [
        ("covers_reference_change", False),
        ("contradicts_reference", True),
        ("unsupported_additions", True),
        ("preserves_unrelated", False),
        ("missing_or_conflicting_claims", ["Missing exception"]),
    ],
)
def test_same_direction_alone_does_not_pass_reference_judge(field, value):
    result = reference_judgment({})
    result[field] = value
    assert (
        judge_result(result, "factor is 1.2", "multiplied by 1.2")["outcome"]
        == "needs_revision"
    )


def test_reference_judge_requires_real_quotes_and_boolean_types():
    result = reference_judgment({})
    with pytest.raises(ProposalError, match="quotes"):
        judge_result(result, "invented", "multiplied by 1.2")
    result["same_direction"] = "true"
    with pytest.raises(ProposalError, match="Invalid"):
        judge_result(result, "factor is 1.2", "multiplied by 1.2")


def test_reference_judge_rate_limits_are_bounded_and_resumable(review_files, tmp_path):
    packet, labels = review_files
    attach_reference(packet, labels)
    folder = tmp_path / "automatic"
    judge = Mock(side_effect=ProviderError("Groq", 429, 2))
    sleep = Mock()
    report = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=response,
        judge=judge,
        delay_seconds=0,
        sleep=sleep,
    )
    assert judge.call_count == 2
    assert report["stop_reason"] == "judge_api_error"
    assert report["metrics"]["overall"]["coverage"] == 0
    sleep.assert_called_once_with(2)
    report = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=Mock(side_effect=AssertionError),
        judge=reference_judgment,
        resume=True,
        delay_seconds=0,
    )
    assert report["metrics"]["overall"]["aligned"] == 1


def test_exact_upstream_match_skips_judge(review_files, tmp_path):
    packet, labels = review_files
    data = attach_reference(packet, labels)
    target = data["cases"][0]["upstream_reference"]["documents"]["head"]["text"]

    def exact(arm, stage, context):
        return {**response(arm, stage, context), "content": target}

    report = evaluate_reference(
        packet,
        tmp_path / "automatic",
        CONFIG,
        generator=exact,
        judge=Mock(side_effect=AssertionError),
        delay_seconds=0,
    )
    assert report["results"][0]["decision_source"] == "exact_match"
    assert report["session_requests"] == 1


def test_reference_judge_interrupt_reuses_checkpointed_response(
    review_files, tmp_path, monkeypatch
):
    packet, labels = review_files
    attach_reference(packet, labels)
    folder = tmp_path / "automatic"

    def interrupt(*args):
        raise KeyboardInterrupt

    with monkeypatch.context() as patcher:
        patcher.setattr("docguard.ai.reference_benchmark.judge_result", interrupt)
        with pytest.raises(KeyboardInterrupt):
            evaluate_reference(
                packet,
                folder,
                CONFIG,
                generator=response,
                judge=reference_judgment,
                delay_seconds=0,
            )
    assert not (folder / "reference-benchmark.lock").exists()
    report = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=Mock(side_effect=AssertionError),
        judge=Mock(side_effect=AssertionError),
        resume=True,
        delay_seconds=0,
    )
    assert report["session_requests"] == 0
    assert report["metrics"]["overall"]["aligned"] == 1


def test_reference_judge_bad_output_is_an_error_not_a_quality_failure(
    review_files, tmp_path
):
    packet, labels = review_files
    attach_reference(packet, labels)
    report = evaluate_reference(
        packet,
        tmp_path / "automatic",
        CONFIG,
        generator=response,
        judge=lambda context: {
            **reference_judgment(context),
            "reference_quote": "invented quote",
        },
        delay_seconds=0,
    )
    metrics = report["metrics"]["overall"]
    assert metrics["errors"] == 1 and metrics["needs_revision"] == 0
    assert metrics["reference_agreement"] is None and metrics["coverage"] == 0


def test_reference_resume_refuses_changed_generation_report(review_files, tmp_path):
    packet, labels = review_files
    attach_reference(packet, labels)
    folder = tmp_path / "automatic"
    evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=response,
        judge=reference_judgment,
        max_requests=1,
        delay_seconds=0,
    )
    path = folder / "generation.json"
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ProposalError, match="Generation report changed"):
        evaluate_reference(
            packet,
            folder,
            CONFIG,
            generator=response,
            judge=reference_judgment,
            resume=True,
            delay_seconds=0,
        )


def test_invalid_judge_retry_is_explicit_bounded_and_preserves_rejected_response(
    review_files, tmp_path
):
    packet, labels = review_files
    attach_reference(packet, labels)
    folder = tmp_path / "automatic"
    bad = Mock(
        return_value={**reference_judgment({}), "reference_quote": "invented quote"}
    )
    evaluate_reference(
        packet, folder, CONFIG, generator=response, judge=bad, delay_seconds=0
    )
    report = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=response,
        judge=bad,
        delay_seconds=0,
        resume=True,
        retry_judge_errors=True,
    )
    assert bad.call_count == 2
    assert len(report["results"][0]["rejected_judge_responses"]) == 1
    assert report["attempts"][-1]["validation_retry"] is True
    assert "format_feedback" in bad.call_args.args[0]
    report = evaluate_reference(
        packet,
        folder,
        CONFIG,
        generator=response,
        judge=bad,
        delay_seconds=0,
        resume=True,
        retry_judge_errors=True,
    )
    assert bad.call_count == 2
    assert report["metrics"]["overall"]["errors"] == 1


def attach_reference(packet, labels):
    data = json.loads(packet.read_text())
    case = data["cases"][0]
    before = case["contexts"]["mapped"]["document_text"]
    after = "# Price\nHIDDEN_REFERENCE_FIX: factor is 1.2.\n"
    case["upstream_reference"] = {
        "kind": "upstream_documentation",
        "role": "withheld_reference_only",
        "changed": True,
        "diff": "-Returns price unchanged.\n+HIDDEN_REFERENCE_FIX\n",
        "documents": {
            side: {"text": text, "sha256": digest(text.encode())}
            for side, text in (("base", before), ("head", after))
        },
    }
    case["discussion"] = [
        {
            "text": "DISCUSSION_SENTINEL",
            "url": case["provenance"]["pr_url"] + "#issuecomment-1",
            "author": "maintainer",
            "updated_at": "2026-11-10T00:00:00Z",
            "sha256": digest(b"DISCUSSION_SENTINEL"),
        }
    ]
    packet.write_text(json.dumps(data))
    gold = json.loads(labels.read_text())
    gold["packet_sha256"] = digest(packet.read_bytes())
    labels.write_text(json.dumps(gold))
    return data


@pytest.mark.parametrize("discussion_mode", ["withheld", "input"])
def test_reference_never_sent_and_discussion_requires_explicit_input_mode(
    review_files, tmp_path, discussion_mode
):
    packet, labels = review_files
    attach_reference(packet, labels)
    calls = []

    def inspect(arm, stage, context):
        serialized = json.dumps(context)
        assert "HIDDEN_REFERENCE_FIX" not in serialized
        assert ("DISCUSSION_SENTINEL" in serialized) == (discussion_mode == "input")
        calls.append((arm, stage))
        return response(arm, stage, context)

    report = run_experiment(
        packet,
        labels,
        tmp_path / "run.json",
        CONFIG,
        caller=inspect,
        delay_seconds=0,
        discussion_mode=discussion_mode,
    )
    assert len(calls) == 4
    assert report["identity"]["discussion_mode"] == discussion_mode
    assert (
        report["metrics"]["arms"]["simple_llm"]["by_label_review_level"][
            "project_reviewed"
        ]["coverage"]["value"]
        == 1
    )
    with pytest.raises(ProposalError, match="configuration mismatch"):
        run_experiment(
            packet,
            labels,
            tmp_path / "run.json",
            CONFIG,
            caller=inspect,
            delay_seconds=0,
            resume=True,
            discussion_mode="input" if discussion_mode == "withheld" else "withheld",
        )


def test_provisional_labels_are_separate_and_can_be_partially_audited(
    review_files, tmp_path
):
    packet, labels = review_files
    attach_reference(packet, labels)
    provisional = tmp_path / "provisional.json"
    reference_labels(packet, provisional)
    report = run_experiment(
        packet,
        provisional,
        tmp_path / "run.json",
        CONFIG,
        caller=response,
        delay_seconds=0,
    )
    metrics = report["metrics"]["arms"]["docguard_direct"]["by_label_review_level"]
    assert metrics["upstream_reference"]["coverage"]["denominator"] == 1
    assert (
        metrics["independently_audited"]["decision_metrics"]["action_agreement"][
            "value"
        ]
        is None
    )
    data = json.loads(provisional.read_text())
    row = data["labels"][0]
    row.update(
        review_level="independently_audited",
        independent=True,
        reviewer="Upstream maintainer",
        mapped="needs_review",
        direct="revise",
    )
    provisional.write_text(json.dumps(data))
    _, reviewed = load_labels(provisional, *load_packet(packet))
    assert reviewed["example"]["mapped"] == "needs_review"
    row["independent"] = False
    provisional.write_text(json.dumps(data))
    with pytest.raises(ProposalError, match="attestation"):
        load_labels(provisional, *load_packet(packet))


def test_reference_hash_and_provisional_override_are_checked(review_files, tmp_path):
    packet, labels = review_files
    data = attach_reference(packet, labels)
    provisional = tmp_path / "provisional.json"
    reference_labels(packet, provisional)
    gold = json.loads(provisional.read_text())
    gold["labels"][0]["mapped"] = "unchanged"
    provisional.write_text(json.dumps(gold))
    with pytest.raises(ProposalError, match="match the documented variant"):
        load_labels(provisional, *load_packet(packet))
    data["cases"][0]["upstream_reference"]["documents"]["head"]["text"] = "altered"
    packet.write_text(json.dumps(data))
    with pytest.raises(ProposalError, match="hash mismatch"):
        load_packet(packet)


def test_discussion_snapshot_rejects_unrelated_pr_and_keeps_provenance(tmp_path):
    pr = "https://github.com/example/repo/pull/12"
    path = tmp_path / "comments.json"
    path.write_text(
        json.dumps(
            [
                {
                    "html_url": pr + "#issuecomment-1",
                    "body": "Intent explanation",
                    "user": {"login": "contributor"},
                    "updated_at": "2026-11-10T00:00:00Z",
                }
            ]
        )
    )
    snapshot = load_discussions(path, {pr})[pr][0]
    assert snapshot["author"] == "contributor"
    assert snapshot["sha256"] == digest(b"Intent explanation")
    with pytest.raises(ProposalError, match="selected PR"):
        load_discussions(path, {"https://github.com/example/repo/pull/1"})


@pytest.fixture
def review_files(tmp_path):
    context = {
        "document_text": "# Price\nReturns price unchanged.\n",
        "evidence": [
            {
                "id": "after:api.py:total",
                "text": "def total(price): return price * 1.2",
                "path": "api.py",
                "start_line": 1,
                "end_line": 1,
            }
        ],
        "changes": [],
    }
    provenance = {
        "pr_url": "https://github.com/example/repo/pull/1",
        "repository_url": "https://github.com/example/repo",
        "upstream_base": "a" * 40,
        "upstream_head": "b" * 40,
        "variant": "base_docs",
        "scope": "Test fixture",
        "license_text": "Fixture only",
        "document_selections": {
            "head": {
                "authored_prefix": "",
                "upstream_revision": "b" * 40,
                "path": "README.md",
                "start_line": 1,
            }
        },
    }
    packet = tmp_path / "packet.json"
    packet.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "docguard.review-packet",
                "cases": [
                    {
                        "case": "example",
                        "contexts": {"mapped": context, "direct": context},
                        "context_sha256": {
                            k: digest(json.dumps(context, sort_keys=True).encode())
                            for k in ("mapped", "direct")
                        },
                        "provenance": provenance,
                        "exposure": "test-fixture",
                    }
                ],
            }
        )
    )
    labels = tmp_path / "labels.json"
    labels.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "docguard.experiment-labels",
                "packet_sha256": digest(packet.read_bytes()),
                "labels": [
                    {
                        "case": "example",
                        "mapped": "revise",
                        "direct": "revise",
                        "reviewer": "Test reviewer",
                        "notes": "The supplied implementation multiplies by 1.2.",
                        "independent": False,
                    }
                ],
            }
        )
    )
    return packet, labels


def response(arm, stage, context):
    if stage == "validator":
        return {
            "supported": True,
            "complete": True,
            "preserves_unrelated": True,
            "style_consistent": True,
            "summary": "The factor matches the code.",
            "evidence_ids": ["after:api.py:total"],
        }
    decision = {
        "action": "revise",
        "summary": "Factor changed",
        "content": "# Price\nReturns price multiplied by 1.2.\n",
        "warnings": [],
    }
    if arm != "simple_llm":
        decision["evidence_ids"] = ["after:api.py:total"]
    return decision


def test_all_methods_share_candidate_and_keep_common_denominators(
    review_files, tmp_path
):
    packet, labels = review_files
    caller = Mock(side_effect=response)
    report = run_experiment(
        packet, labels, tmp_path / "run.json", CONFIG, caller=caller, delay_seconds=0
    )
    assert (
        caller.call_count == 4
    )  # three generations + one validator, not four generations
    assert report["metrics"]["common_completed_cases"] == ["example"]
    assert (
        report["metrics"]["arms"]["leave_unchanged"]["completed_case_metrics"][
            "missed_edits"
        ]["value"]
        == 1
    )
    direct, validated = report["results"][3:5]
    assert direct["candidate"] == validated["candidate"]
    assert validated["generation_shared_from"] == "docguard_direct"
    assert (
        report["metrics"]["arms"]["docguard_validated"][
            "effective_attempts_including_shared_generation"
        ]
        == 2
    )
    assert report["metrics"]["human_acceptance"] is None
    assert not (tmp_path / "run.json.lock").exists()


def test_budget_resume_only_runs_missing_validation(review_files, tmp_path):
    packet, labels = review_files
    path = tmp_path / "run.json"
    first = run_experiment(
        packet, labels, path, CONFIG, caller=response, max_requests=3, delay_seconds=0
    )
    assert first["stop_reason"] == "request_budget"
    assert first["metrics"]["common_completed_cases"] == []
    second_caller = Mock(side_effect=response)
    second = run_experiment(
        packet, labels, path, CONFIG, caller=second_caller, resume=True, delay_seconds=0
    )
    assert second_caller.call_count == 1
    assert second_caller.call_args.args[:2] == ("docguard_validated", "validator")
    assert second["session_requests"] == 1
    complete = run_experiment(
        packet,
        labels,
        path,
        CONFIG,
        caller=Mock(side_effect=AssertionError),
        resume=True,
        delay_seconds=0,
    )
    assert complete["session_requests"] == 0


def test_repeated_rate_limits_are_bounded_and_preserve_errors(review_files, tmp_path):
    packet, labels = review_files
    caller = Mock(side_effect=ProviderError("Groq", 429, 2))
    sleep = Mock()
    report = run_experiment(
        packet,
        labels,
        tmp_path / "run.json",
        CONFIG,
        caller=caller,
        delay_seconds=0,
        sleep=sleep,
    )
    assert caller.call_count == 2
    sleep.assert_called_once_with(2)
    assert report["stop_reason"] == "provider_http_429"
    assert report["results"][1]["status"] == "api_error"
    assert len(report["attempts"]) == 2


def test_validator_rejection_is_not_automatic_human_disapproval(review_files, tmp_path):
    packet, labels = review_files

    def reject(arm, stage, context):
        value = response(arm, stage, context)
        if stage == "validator":
            value["supported"] = False
        return value

    path = tmp_path / "run.json"
    report = run_experiment(
        packet, labels, path, CONFIG, caller=reject, delay_seconds=0
    )
    row = report["results"][-1]
    assert row["initial_action"] == "revise" and row["action"] == "needs_review"
    reviews = tmp_path / "reviews.json"
    reviews.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "kind": "docguard.experiment-reviews",
                "report_sha256": digest(path.read_bytes()),
                "reviews": [
                    {
                        "case": "example",
                        "arm": "docguard_validated",
                        "reviewer": "Reviewer",
                        "independent": True,
                        "notes": "The candidate is correct; rejection is unnecessary.",
                        "supported": True,
                        "complete": True,
                        "preserves_unrelated": True,
                        "style_consistent": True,
                        "accepted": False,
                        "candidate_acceptable": True,
                    }
                ],
            }
        )
    )
    scores = score_experiment(path, reviews, tmp_path / "scores.json")
    assert scores["validator"]["good_candidates_rejected"]["value"] == 1
    assert scores["validator"]["bad_candidates_caught"]["value"] is None
    assert (
        scores["independent_metrics"]["docguard_validated"]["acceptance"]["value"] == 0
    )
    path.write_text(path.read_text() + "\n")
    with pytest.raises(ProposalError, match="exact experiment"):
        score_experiment(path, reviews, tmp_path / "bad.json")


def test_invalid_citations_do_not_count_as_completed(review_files, tmp_path):
    packet, labels = review_files

    def bad(arm, stage, context):
        value = response(arm, stage, context)
        if arm != "simple_llm":
            value["evidence_ids"] = ["invented"]
        return value

    report = run_experiment(
        packet, labels, tmp_path / "run.json", CONFIG, caller=bad, delay_seconds=0
    )
    assert report["results"][2]["status"] == "validation_error"
    assert report["metrics"]["common_completed_cases"] == []


def test_resume_requires_exact_model_and_label_file(review_files, tmp_path):
    packet, labels = review_files
    path = tmp_path / "run.json"
    run_experiment(packet, labels, path, CONFIG, caller=response, delay_seconds=0)
    with pytest.raises(ProposalError, match="configuration mismatch"):
        run_experiment(
            packet,
            labels,
            path,
            AIConfig("groq", "other", "key"),
            caller=response,
            resume=True,
            delay_seconds=0,
        )
    labels.write_text(labels.read_text() + "\n")
    with pytest.raises(ProposalError, match="configuration mismatch"):
        run_experiment(
            packet, labels, path, CONFIG, caller=response, resume=True, delay_seconds=0
        )


def test_labels_need_all_cases_and_nonempty_rationale(review_files):
    packet, labels = review_files
    packet_hash, data = load_packet(packet)
    value = json.loads(labels.read_text())
    value["labels"][0]["notes"] = ""
    labels.write_text(json.dumps(value))
    with pytest.raises(ProposalError, match="rationale"):
        load_labels(labels, packet_hash, data)


def test_html_embeds_untrusted_text_as_data_and_refuses_overwrite(
    review_files, tmp_path
):
    packet, _ = review_files
    value = json.loads(packet.read_text())
    attack = "</script><script>window.stolen=true</script>"
    value["cases"][0]["contexts"]["mapped"]["document_text"] = attack
    value["cases"][0]["context_sha256"]["mapped"] = digest(
        json.dumps(value["cases"][0]["contexts"]["mapped"], sort_keys=True).encode()
    )
    packet.write_text(json.dumps(value))
    output = tmp_path / "review.html"
    render_review_ui(packet, output)
    html = output.read_text(encoding="utf-8")
    assert attack not in html
    assert "connect-src 'none'" in html and "textContent" in html
    assert "innerHTML" not in html
    with pytest.raises(FileExistsError):
        render_review_ui(packet, output)


def test_changed_packet_context_is_rejected(review_files):
    packet, _ = review_files
    value = json.loads(packet.read_text())
    value["cases"][0]["contexts"]["mapped"]["document_text"] = "Changed"
    packet.write_text(json.dumps(value))
    with pytest.raises(ProposalError, match="hash mismatch"):
        load_packet(packet)


def test_resume_rejects_edited_expected_decisions(review_files, tmp_path):
    packet, labels = review_files
    output = tmp_path / "run.json"
    run_experiment(packet, labels, output, CONFIG, caller=response, delay_seconds=0)
    value = json.loads(output.read_text())
    value["results"][0]["expected_action"] = "unchanged"
    output.write_text(json.dumps(value))
    with pytest.raises(ProposalError, match="frozen labels"):
        run_experiment(
            packet,
            labels,
            output,
            CONFIG,
            caller=response,
            delay_seconds=0,
            resume=True,
        )


def test_interrupt_preserves_completed_calls(review_files, tmp_path):
    packet, labels = review_files
    path = tmp_path / "run.json"
    calls = []

    def interrupt(arm, stage, context):
        calls.append(arm)
        if len(calls) == 2:
            raise KeyboardInterrupt
        return response(arm, stage, context)

    with pytest.raises(KeyboardInterrupt):
        run_experiment(packet, labels, path, CONFIG, caller=interrupt, delay_seconds=0)
    assert not path.with_suffix(".json.lock").exists()
    saved = json.loads(path.read_text())
    assert saved["attempts"][1]["status"] == "in_flight"
    resume = Mock(side_effect=response)
    run_experiment(
        packet, labels, path, CONFIG, caller=resume, delay_seconds=0, resume=True
    )
    assert resume.call_count == 3
    assert all(call.args[0] != "simple_llm" for call in resume.call_args_list)


def test_claim_gate_skips_paid_docguard_calls(review_files, tmp_path):
    packet, labels = review_files
    value = json.loads(packet.read_text())
    case = value["cases"][0]
    for policy, context in case["contexts"].items():
        context["claim_requirements"] = {"status": "needs_review", "claims": []}
        case["context_sha256"][policy] = digest(
            json.dumps(context, sort_keys=True).encode()
        )
    packet.write_text(json.dumps(value))
    gold = json.loads(labels.read_text())
    gold["packet_sha256"] = digest(packet.read_bytes())
    labels.write_text(json.dumps(gold))
    caller = Mock(side_effect=response)
    report = run_experiment(
        packet, labels, tmp_path / "run.json", CONFIG, caller=caller, delay_seconds=0
    )
    assert caller.call_count == 1
    assert all(
        r["decision_source"] == "deterministic_gate" for r in report["results"][2:]
    )


def test_invalid_validator_boolean_fails_closed(review_files, tmp_path):
    packet, labels = review_files

    def invalid(arm, stage, context):
        value = response(arm, stage, context)
        if stage == "validator":
            value["supported"] = "true"
        return value

    report = run_experiment(
        packet, labels, tmp_path / "run.json", CONFIG, caller=invalid, delay_seconds=0
    )
    assert report["results"][-1]["status"] == "validation_error"
    assert "action" not in report["results"][-1]
    assert report["metrics"]["arms"]["docguard_validated"]["coverage"]["value"] == 0


@pytest.mark.skipif(
    os.environ.get("DOCGUARD_BROWSER_TESTS") != "1", reason="Opt-in real browser test"
)
def test_browser_labels_exports_ratings_and_treats_source_as_text(
    review_files, tmp_path
):
    sync = pytest.importorskip("playwright.sync_api")
    packet, labels = review_files
    attach_reference(packet, labels)
    attack = "</script><script>window.stolen=true</script>"
    data = json.loads(packet.read_text())
    case = data["cases"][0]
    for policy, context in case["contexts"].items():
        context["evidence"][0]["text"] += "\n# " + attack
        case["context_sha256"][policy] = digest(
            json.dumps(context, sort_keys=True).encode()
        )
    packet.write_text(json.dumps(data))
    ui = tmp_path / "review.html"
    render_review_ui(packet, ui)
    with sync.sync_playwright() as playwright:
        options = {"headless": True}
        if os.environ.get("DOCGUARD_BROWSER_CHANNEL"):
            options["channel"] = os.environ["DOCGUARD_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        page = browser.new_page(accept_downloads=True)
        errors = []
        requests = []
        page.on("pageerror", lambda error: errors.append(error))
        page.on("request", lambda request: requests.append(request.url))
        page.goto(ui.as_uri())
        assert page.locator("#reference-card").is_visible()
        assert "HIDDEN_REFERENCE_FIX" in page.locator("#reference-head").inner_text()
        assert attack in page.locator("#evidence").inner_text()
        assert page.evaluate("window.stolen === undefined")
        assert page.locator("#progress").inner_text() == "0 / 1 saved"
        page.locator("#save").click()
        assert "explicitly" in page.locator("#error").inner_text()
        page.locator("#reviewer").fill("Test reviewer")
        page.locator("#notes").fill("after:api.py:total supplies the multiplier.")
        page.locator("#field-mapped").select_option("revise")
        page.locator("#field-direct").select_option("revise")
        page.locator("#save").click()
        with page.expect_download() as download:
            page.locator("#export").click()
        exported = tmp_path / "browser-labels.json"
        download.value.save_as(exported)
        load_labels(exported, *load_packet(packet))
        page.locator("#import").set_input_files(exported)
        assert page.locator("#progress").inner_text() == "1 / 1 saved"
        report = tmp_path / "report.json"
        run_experiment(
            packet, exported, report, CONFIG, caller=response, delay_seconds=0
        )
        review = tmp_path / "repairs.html"
        render_review_ui(packet, review, report)
        page.goto(review.as_uri())
        assert "Candidate A" in page.locator("#select").inner_text()
        page.locator("#select").select_option("4")
        page.locator("#reference-comparison").select_option("valid_alternative")
        page.locator("#reviewer").fill("Test reviewer")
        page.locator("#notes").fill(
            "Candidate matches supplied multiplier; final routing appropriate."
        )
        for criterion in (
            "supported",
            "complete",
            "preserves_unrelated",
            "style_consistent",
            "candidate_acceptable",
            "accepted",
        ):
            page.locator("#field-" + criterion).select_option("true")
        page.locator("#save").click()
        with page.expect_download() as download:
            page.locator("#export").click()
        reviews = tmp_path / "browser-reviews.json"
        download.value.save_as(reviews)
        scores = score_experiment(report, reviews, tmp_path / "scores.json")
        assert (
            scores["metrics"]["docguard_validated"]["upstream_reference_comparison"][
                "valid_alternative"
            ]
            == 1
        )
        assert (
            scores["metrics"]["docguard_validated"]["repair_candidate_acceptance"][
                "value"
            ]
            == 1
        )
        assert scores["metrics"]["simple_llm"]["acceptance"]["value"] is None
        assert not errors
        assert all(url.startswith("file:") for url in requests)
        browser.close()


@pytest.mark.skipif(
    os.environ.get("DOCGUARD_BROWSER_TESTS") != "1", reason="Opt-in real browser test"
)
def test_browser_promotes_only_explicitly_verified_reference_labels(
    review_files, tmp_path
):
    sync = pytest.importorskip("playwright.sync_api")
    packet, labels = review_files
    attach_reference(packet, labels)
    provisional = tmp_path / "provisional.json"
    reference_labels(packet, provisional)
    ui = tmp_path / "seeded.html"
    render_review_ui(packet, ui, labels_path=provisional)
    with sync.sync_playwright() as playwright:
        options = {"headless": True}
        if os.environ.get("DOCGUARD_BROWSER_CHANNEL"):
            options["channel"] = os.environ["DOCGUARD_BROWSER_CHANNEL"]
        browser = playwright.chromium.launch(**options)
        page = browser.new_page(accept_downloads=True)
        page.goto(ui.as_uri())
        assert "upstream_reference" in page.locator("#review-level").inner_text()
        assert page.locator("#reviewer").input_value() == ""
        assert not page.locator("#independent").is_checked()
        assert page.locator("#field-mapped").input_value() == "revise"
        page.locator("#reviewer").fill("Project owner")
        page.locator("#notes").fill(
            "Checked the code and upstream correction; sufficient evidence."
        )
        page.locator("#save").click()
        assert "project_reviewed" in page.locator("#review-level").inner_text()
        with page.expect_download() as download:
            page.locator("#export").click()
        exported = tmp_path / "reviewed.json"
        download.value.save_as(exported)
        _, rows = load_labels(exported, *load_packet(packet))
        assert rows["example"]["review_level"] == "project_reviewed"
        assert rows["example"]["independent"] is False
        browser.close()
