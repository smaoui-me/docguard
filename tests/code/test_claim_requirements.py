import copy
import json
from unittest.mock import Mock

import pytest

from docguard.ai.claims import assess_claims
from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository
from docguard.ai.files import ProposalError
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.proposals import suggest
from docguard.docs.mapping import ClaimRequirement, MappingError, load_mapping
from docguard.git_review import _git

QUOTE = "total(price) returns the price unchanged."
CONFIG = AIConfig("groq", "test", "")
CLAIM = {
    "id": "price-result",
    "quote": QUOTE,
    "required_evidence": ["after:api.py:transform"],
}


def mapping(claim=None):
    return {
        "schema_version": 2,
        "documents": {
            "README.md": {
                "entity_ids": ["api.py:total"],
                "claims": [copy.deepcopy(CLAIM if claim is None else claim)],
            }
        },
    }


def write_mapping(root, value):
    path = root / "docguard-map.json"
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def repository(tmp_path, *, helper=False, quote=QUOTE, helper_only=False, claim=None):
    root = tmp_path / "repo"
    before = "def total(price): return price\n"
    after = "def total(price): return transform(price)\n"
    if helper_only:
        before = after + "def transform(price): return price\n"
    if helper:
        after += "def transform(price): return price * 1.2\n"
    base, _ = create_case_repository(
        {
            "before": before,
            "after": after,
            "before_document": quote + "\n",
            "document": quote + "\n",
            "entity_ids": ["api.py:total"],
        },
        root,
    )
    write_mapping(root, mapping(claim))
    _git(root, "add", "docguard-map.json")
    _git(root, "commit", "-m", "declare claim evidence requirements")
    return root, base, _git(root, "rev-parse", "HEAD").decode().strip()


@pytest.mark.parametrize(
    "mutation",
    [
        {"id": ""},
        {"id": "space name"},
        {"quote": " "},
        {"quote": "x" * 4001},
        {"required_evidence": []},
        {"required_evidence": [True]},
        {"required_evidence": ["api.py:transform"]},
        {"required_evidence": ["after:../api.py:f"]},
        {"required_evidence": ["after:api.py:f", "after:api.py:f"]},
        {"required_evidence": ["after:C:/api.py:f"]},
        {"extra": "ignored?"},
    ],
)
def test_invalid_claims_fail_explicitly(tmp_path, mutation):
    (tmp_path / "README.md").write_text(QUOTE)
    path = write_mapping(tmp_path, mapping({**CLAIM, **mutation}))
    with pytest.raises(MappingError):
        load_mapping(path, tmp_path)


def test_duplicate_claims_and_missing_v2_fields_rejected(tmp_path):
    (tmp_path / "README.md").write_text(QUOTE)
    value = mapping()
    value["documents"]["README.md"]["claims"] *= 2
    with pytest.raises(MappingError):
        load_mapping(write_mapping(tmp_path, value), tmp_path)
    with pytest.raises(MappingError):
        load_mapping(
            write_mapping(
                tmp_path,
                {"schema_version": 2, "documents": {"README.md": ["api.py:total"]}},
            ),
            tmp_path,
        )


def test_required_side_and_unique_quote_are_enforced():
    overlapping = (ClaimRequirement("overlap", "aa", ("after:api.py:transform",)),)
    assert (
        assess_claims(
            overlapping, "aaa", [{"id": "after:api.py:transform", "text": "code"}]
        )["status"]
        == "needs_review"
    )
    claims = (ClaimRequirement("price", QUOTE, ("after:api.py:transform",)),)
    before = [{"id": "before:api.py:transform", "text": "implementation"}]
    assert assess_claims(claims, QUOTE, before)["status"] == "needs_review"
    after = [{"id": "after:api.py:transform", "text": "implementation"}]
    assert assess_claims(claims, QUOTE, after)["status"] == "ready"
    assert assess_claims(claims, QUOTE * 2, after)["status"] == "needs_review"
    assert (
        assess_claims(claims, "updated documentation", after)["status"]
        == "needs_review"
    )


def test_missing_dependency_skips_provider_and_cannot_be_forged_into_revision(tmp_path):
    root, base, head = repository(tmp_path)
    output = tmp_path / "proposal.json"
    api = Mock(side_effect=AssertionError("No paid request should occur"))
    assert (
        suggest_git(
            root, base, head, "docguard-map.json", output, CONFIG, generator=api
        )
        == 1
    )
    api.assert_not_called()
    data = json.loads(output.read_text(encoding="utf-8"))
    row = data["proposals"][0]
    assert row["proposal"]["action"] == "needs_review"
    assert "after:api.py:transform" in row["proposal"]["warnings"][0]
    assert data["review"]["claim_requirements"]["README.md"]["status"] == "needs_review"
    row["proposal"].update(action="revise", content="invented correction\n")
    row["evidence_ids"] = [row["evidence"][0]["id"]]
    output.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ProposalError, match="requirements are unmet"):
        apply_git_proposal(output, root, "README.md", check=True)
    assert (root / "README.md").read_text().strip() == QUOTE


@pytest.mark.parametrize("helper_only", [False, True])
@pytest.mark.parametrize("policy", ["mapped", "direct"])
def test_required_helper_is_selected_and_helper_only_changes_trigger_review(
    tmp_path, helper_only, policy
):
    root, base, head = repository(tmp_path, helper=True, helper_only=helper_only)
    output = tmp_path / "proposal.json"

    def response(model, context):
        assert context["claim_requirements"]["status"] == "ready"
        ids = [e["id"] for e in context["evidence"]]
        assert ids.count("after:api.py:transform") == 1
        if helper_only:
            assert any(r["entity_id"] == "api.py:transform" for r in context["reasons"])
        return {
            "action": "revise",
            "content": "total(price) returns price multiplied by 1.2.\n",
            "summary": "Supported multiplier change",
            "warnings": [],
            "evidence_ids": ["after:api.py:transform"],
        }

    api = Mock(side_effect=response)
    suggest_git(
        root,
        base,
        head,
        "docguard-map.json",
        output,
        CONFIG,
        generator=api,
        evidence_policy=policy,
    )
    api.assert_called_once()
    assert "1.2" in apply_git_proposal(output, root, "README.md", check=True)


@pytest.mark.parametrize("quote", ["Changed text", QUOTE + "\n" + QUOTE])
def test_stale_or_ambiguous_quote_blocks_even_with_complete_evidence(tmp_path, quote):
    root, base, head = repository(tmp_path, helper=True, quote=quote)
    api = Mock()
    output = tmp_path / "requests.json"
    suggest_git(
        root,
        base,
        head,
        "docguard-map.json",
        output,
        CONFIG,
        dry_run=True,
        generator=api,
    )
    api.assert_not_called()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["requests"] == []
    assert data["review"]["claim_requirements"]["README.md"]["status"] == "needs_review"


def test_snapshot_mode_refuses_to_ignore_contracts(tmp_path):
    root, _, _ = repository(tmp_path)
    api = Mock()
    with pytest.raises(ProposalError, match="suggest-git"):
        suggest(
            root,
            tmp_path / "unused.json",
            root / "docguard-map.json",
            tmp_path / "out.json",
            generator=api,
        )
    api.assert_not_called()


def test_historical_evidence_can_support_a_removal_claim(tmp_path):
    claim = {**CLAIM, "required_evidence": ["before:api.py:total"]}
    root, base, head = repository(tmp_path, claim=claim)
    output = tmp_path / "requests.json"
    suggest_git(root, base, head, "docguard-map.json", output, CONFIG, dry_run=True)
    data = json.loads(output.read_text(encoding="utf-8"))
    assert len(data["requests"]) == 1
    assert data["review"]["claim_requirements"]["README.md"]["status"] == "ready"


def test_deleted_required_helper_triggers_gate_without_primary_change(tmp_path):
    root, base, head = repository(tmp_path, helper_only=True, helper=False)
    api = Mock()
    output = tmp_path / "proposal.json"
    suggest_git(root, base, head, "docguard-map.json", output, CONFIG, generator=api)
    api.assert_not_called()
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["proposals"][0]["proposal"]["action"] == "needs_review"
    assert data["review"]["documents"][0]["reasons"][0]["change"] == "removed"


def test_added_required_helper_triggers_review_and_removed_requirement_is_reported():
    from docguard.code.python_parser import _parse_source
    from docguard.docs.mapping import DocumentMapping
    from docguard.docs.review import removed_mapping_links, review_documents

    before = {
        e.id: e for e in _parse_source("def total(p): return transform(p)\n", "api.py")
    }
    after = {
        e.id: e
        for e in _parse_source(
            "def total(p): return transform(p)\ndef transform(p): return p * 1.2\n",
            "api.py",
        )
    }
    plain = DocumentMapping("README.md", ("api.py:total",))
    contract = DocumentMapping(
        "README.md",
        plain.entity_ids,
        (ClaimRequirement("price", QUOTE, ("after:api.py:transform",)),),
    )
    report = review_documents([contract], before, after)
    assert report.documents[0].reasons[0].change == "added"
    assert report.unmapped_added == ()
    assert removed_mapping_links([contract], [plain])[0].entity_id == "api.py:transform"
