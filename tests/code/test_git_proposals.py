import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository, load_cases
from docguard.ai.files import ProposalError
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.provider import request_payload
from docguard.git_review import _git

DATASET = Path(__file__).resolve().parents[2] / "evaluations/git_cases.toml"
CONFIG = AIConfig("groq", "openai/gpt-oss-120b", "fake-key")


@pytest.fixture
def repo(tmp_path):
    case = load_cases(DATASET)[0]
    root = tmp_path / "repo with spaces"
    base, head = create_case_repository(case, root)
    return root, base, head, case


def generate_fixture(case):
    def generate(model, context):
        return {
            "action": case["action"],
            "summary": "Document verified change",
            "content": case["replacement"] if case["action"] == "revise" else None,
            "warnings": [],
            "evidence_ids": [e["id"] for e in context["evidence"]],
        }

    return generate


def suggest(repo, output, **kwargs):
    root, base, head, case = repo
    return suggest_git(
        root,
        base,
        head,
        "docguard-map.json",
        output,
        CONFIG,
        generator=kwargs.pop("generator", generate_fixture(case)),
        **kwargs,
    )


def test_evidence_proposal_preview_apply_and_stale_reapply(repo, tmp_path):
    root, base, head, case = repo
    output = tmp_path / "proposal.json"
    status = _git(root, "status", "--porcelain")
    assert suggest(repo, output) == 1
    data = json.loads(output.read_text())
    assert data["git"] == {
        "base": base,
        "head": head,
        "merge_base": base,
        "mapping": "docguard-map.json",
    }
    before, after = data["proposals"][0]["evidence"]
    assert before["revision"] == base
    assert after["revision"] == head
    assert "timeout" not in before["text"]
    assert "timeout=30" in after["text"]
    assert after["path"] == "api.py"
    assert after["start_line"] == 1 and after["end_line"] == 2
    assert _git(root, "status", "--porcelain") == status
    diff = apply_git_proposal(output, root, "README.md", True)
    assert "timeout" in diff
    assert _git(root, "status", "--porcelain") == status
    apply_git_proposal(output, root, "README.md")
    assert (root / "README.md").read_text() == case["replacement"]
    with pytest.raises(ProposalError, match="Document changed"):
        apply_git_proposal(output, root, "README.md")


def test_dry_run_has_both_sources_diff_and_evidence_schema_ignores_dirty_worktree(
    repo, tmp_path
):
    root, _, _, _ = repo
    (root / "api.py").write_text("invalid python !")
    (root / "README.md").write_text("uncommitted secret-not-in-context")
    api = Mock()
    output = tmp_path / "requests.json"
    suggest(repo, output, dry_run=True, generator=api)
    api.assert_not_called()
    data = json.loads(output.read_text())
    payload = data["requests"][0]
    context = json.loads(payload["messages"][1]["content"])
    assert len(context["evidence"]) == 2
    assert "+def connect" in context["changes"][0]["diff"]
    assert "previous_document_text" in context or context["previous_document_same_as_current"]
    assert (
        "evidence_ids"
        in payload["response_format"]["json_schema"]["schema"]["required"]
    )
    assert "secret-not-in-context" not in output.read_text()
    assert "fake-key" not in output.read_text()


@pytest.mark.parametrize(
    "mutation",
    ["unknown_citation", "empty_citations", "duplicate_citations", "missing_citations"],
)
def test_bad_provider_citations_fail_before_artifact(repo, tmp_path, mutation):
    def bad(model, context):
        result = generate_fixture(repo[3])(model, context)
        if mutation == "unknown_citation":
            result["evidence_ids"] = ["after:fake.py:invented"]
        elif mutation == "empty_citations":
            result["evidence_ids"] = []
        elif mutation == "duplicate_citations":
            result["evidence_ids"] *= 2
        else:
            del result["evidence_ids"]
        return result

    output = tmp_path / "bad.json"
    with pytest.raises(ProposalError):
        suggest(repo, output, generator=bad)
    assert not output.exists()


@pytest.mark.parametrize(
    "mutation",
    ["evidence", "line", "original", "citation", "head", "source", "document"],
)
def test_tampering_and_dirty_files_rejected(repo, tmp_path, mutation):
    root, base, _, _ = repo
    output = tmp_path / "proposal.json"
    suggest(repo, output)
    data = json.loads(output.read_text())
    item = data["proposals"][0]
    if mutation == "evidence":
        item["evidence"][0]["text"] = "forged source"
    elif mutation == "line":
        item["evidence"][0]["start_line"] = 900
    elif mutation == "original":
        item["proposal"]["original"] = "forged doc"
    elif mutation == "citation":
        item["evidence_ids"] = ["unknown"]
    elif mutation == "head":
        data["git"]["head"] = base
    elif mutation == "source":
        (root / "api.py").write_text("def connect(): return 8")
    else:
        (root / "README.md").write_text("human edit")
    output.write_text(json.dumps(data))
    original = (root / "README.md").read_bytes()
    with pytest.raises(ProposalError):
        apply_git_proposal(output, root, "README.md")
    assert (root / "README.md").read_bytes() == original


def test_windows_checkout_newlines_preserved(repo, tmp_path):
    root, _, _, _ = repo
    output = tmp_path / "proposal.json"
    suggest(repo, output)
    for name in ("api.py", "README.md"):
        path = root / name
        path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    apply_git_proposal(output, root, "README.md")
    raw = (root / "README.md").read_bytes()
    assert b"\r\n" in raw
    assert b"\n" not in raw.replace(b"\r\n", b"")


def test_merge_base_and_no_checkout_mutation(repo, tmp_path):
    root, base, head, _ = repo
    _git(root, "checkout", "-b", "advanced-target", base)
    (root / "unrelated.txt").write_text("target-only change")
    _git(root, "add", ".")
    _git(root, "-c", "core.hooksPath=", "commit", "-m", "target advanced")
    target = _git(root, "rev-parse", "HEAD").decode().strip()
    output = tmp_path / "proposal.json"
    suggest_git(
        root,
        target,
        head,
        "docguard-map.json",
        output,
        CONFIG,
        generator=generate_fixture(repo[3]),
    )
    data = json.loads(output.read_text())
    assert data["git"]["merge_base"] == base
    assert data["git"]["base"] == target
    assert _git(root, "rev-parse", "HEAD").decode().strip() == target


def test_no_changes_no_network_existing_output_and_selection(repo, tmp_path):
    root, _, head, _ = repo
    api = Mock()
    output = tmp_path / "empty.json"
    assert (
        suggest_git(
            root, head, head, "docguard-map.json", output, CONFIG, generator=api
        )
        == 0
    )
    assert json.loads(output.read_text())["proposals"] == []
    api.assert_not_called()
    with pytest.raises(ProposalError):
        suggest(repo, output, generator=api)
    with pytest.raises(ProposalError):
        suggest(
            repo, tmp_path / "selected.json", generator=api, selected=["unknown.md"]
        )
    api.assert_not_called()


def test_snapshot_schema_unchanged_git_prompt_adds_citation_field():
    for provider in ("groq", "openai"):
        payload = request_payload("model", {"evidence": []}, provider)
        normal = request_payload("model", {}, provider)
        git_schema = (
            payload["response_format"]["json_schema"]["schema"]
            if provider == "groq"
            else payload["text"]["format"]["schema"]
        )
        normal_schema = (
            normal["response_format"]["json_schema"]["schema"]
            if provider == "groq"
            else normal["text"]["format"]["schema"]
        )
        assert "evidence_ids" in git_schema["required"]
        assert "evidence_ids" not in normal_schema["required"]


def test_context_limit_prevents_network(repo, tmp_path):
    root, base, _, case = repo
    (root / "api.py").write_text(
        'def connect(host, port=443):\n    return "' + ("x" * 41000) + '"\n'
    )
    _git(root, "add", ".")
    _git(root, "commit", "-m", "oversized context")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    api = Mock()
    output = tmp_path / "oversize.json"
    with pytest.raises(ProposalError, match="Context|context"):
        suggest((root, base, head, case), output, generator=api)
    api.assert_not_called()
    assert not output.exists()


def test_second_response_failure_never_writes_partial_bundle(repo, tmp_path):
    root, base, _, case = repo
    mapping = root / "docguard-map.json"
    data = json.loads(mapping.read_text())
    data["documents"]["other.md"] = data["documents"]["README.md"]
    mapping.write_text(json.dumps(data))
    (root / "other.md").write_text(case["document"])
    _git(root, "add", ".")
    _git(root, "commit", "-m", "second document")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    calls = []

    def fail_second(model, context):
        calls.append(context["document"])
        if len(calls) == 2:
            raise ProposalError("simulated failure")
        return generate_fixture(case)(model, context)

    output = tmp_path / "partial.json"
    with pytest.raises(ProposalError):
        suggest((root, base, head, case), output, generator=fail_second)
    assert len(calls) == 2
    assert not output.exists()
    assert (root / "README.md").read_text() == case["document"]


def test_changed_mapping_rejected_at_apply(repo, tmp_path):
    root = repo[0]
    output = tmp_path / "proposal.json"
    suggest(repo, output)
    (root / "docguard-map.json").write_text("{}")
    with pytest.raises(ProposalError, match="mapping"):
        apply_git_proposal(output, root, "README.md")


def test_legacy_mapped_artifact_still_previews(repo, tmp_path):
    output = tmp_path / "proposal.json"
    suggest(repo, output)
    data = json.loads(output.read_text())
    data["schema_version"] = 1
    del data["evidence_policy"]
    del data["evidence_version"]
    output.write_text(json.dumps(data))
    assert "timeout" in apply_git_proposal(output, repo[0], "README.md", check=True)
