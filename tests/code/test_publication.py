import json
from pathlib import Path
from unittest.mock import Mock

import pytest

from docguard.ai.config import AIConfig
from docguard.ai.dataset import create_case_repository, load_cases
from docguard.ai.files import ProposalError
from docguard.ai.git_proposals import suggest_git
from docguard.publication import GitHubError, github_api, publish_proposal


@pytest.fixture(scope="module")
def proposal(tmp_path_factory):
    directory = tmp_path_factory.mktemp("publication")
    root, artifact = directory / "repo", directory / "proposal.json"
    case = load_cases(Path("evaluations/git_cases.toml"))[0]
    base, head = create_case_repository(case, root)

    def generate(model, context):
        return {
            "action": "revise",
            "summary": "Document timeout",
            "content": case["replacement"],
            "warnings": [],
            "evidence_ids": [context["evidence"][-1]["id"]],
        }

    suggest_git(
        root,
        base,
        head,
        "docguard-map.json",
        artifact,
        AIConfig("groq", "test", ""),
        generator=generate,
    )
    return root, artifact, head


class Server:
    def __init__(self, head):
        self.head = head
        self.repo = "owner/project"
        self.state = "open"
        self.branch = None
        self.pr = None
        self.commits = {}
        self.calls = []
        self.stale_at = None
        self.reads = 0
        self.fail_create_pr = False
        self.fail_ref = False
        self.collision = False

    def __call__(self, method, endpoint, payload):
        self.calls.append((method, endpoint, payload))
        if endpoint == "pulls/7":
            self.reads += 1
            return {
                "state": self.state,
                "merged": False,
                "head": {
                    "repo": {"full_name": self.repo},
                    "sha": "changed"
                    if self.stale_at and self.reads >= self.stale_at
                    else self.head,
                    "ref": "feature",
                },
            }
        if endpoint == f"git/commits/{self.head}":
            return {"tree": {"sha": "base-tree"}}
        if endpoint == "git/trees":
            assert payload["base_tree"] == "base-tree"
            assert len(payload["tree"]) == 1
            assert payload["tree"][0]["path"] == "README.md"
            return {"sha": "new-tree"}
        if endpoint == "git/commits":
            self.commits["repair"] = {
                "tree": {"sha": payload["tree"]},
                "parents": [{"sha": p} for p in payload["parents"]],
            }
            return {"sha": "repair"}
        if endpoint.startswith("git/commits/"):
            return self.commits[endpoint.split("/")[-1]]
        if endpoint.startswith("git/ref/heads/"):
            if self.branch is None:
                raise GitHubError(404)
            return {"object": {"sha": self.branch}}
        if endpoint == "git/refs":
            self.branch = payload["sha"]
            if self.fail_ref:
                self.fail_ref = False
                raise GitHubError(422)
            return {}
        if endpoint.startswith("pulls?"):
            return [self.pr] if self.pr else []
        if endpoint == "pulls":
            assert payload["draft"] is True and payload["base"] == "feature"
            if self.fail_create_pr:
                self.fail_create_pr = False
                raise GitHubError(429)
            self.pr = {
                "state": "open",
                "draft": True,
                "base": {"ref": "feature"},
                "head": {"sha": "repair"},
                "html_url": "https://github.com/owner/project/pull/8",
            }
            if self.collision:
                raise GitHubError(422)
            return self.pr
        raise AssertionError((method, endpoint))


def run(proposal, server, publish=True):
    root, artifact, _ = proposal
    return publish_proposal(
        artifact, root, "README.md", "owner/project", 7, publish=publish, api=server
    )


def test_preview_is_offline_and_does_not_change_document(proposal):
    api = Mock(side_effect=AssertionError("network"))
    before = (proposal[0] / "README.md").read_bytes()
    result = run(proposal, api, publish=False)
    assert result["mode"] == "preview" and "timeout" in result["diff"]
    assert (proposal[0] / "README.md").read_bytes() == before
    api.assert_not_called()


def test_publication_rerun_reuses_one_draft(proposal):
    server = Server(proposal[2])
    assert run(proposal, server)["reused"] is False
    assert run(proposal, server)["reused"] is True
    assert (
        sum(method == "POST" and path == "pulls" for method, path, _ in server.calls)
        == 1
    )
    assert all(method != "PATCH" for method, _, _ in server.calls)


@pytest.mark.parametrize("mutation", ["fork", "closed", "stale"])
def test_ineligible_source_rejected_before_writes(proposal, mutation):
    server = Server(proposal[2])
    if mutation == "fork":
        server.repo = "other/fork"
    elif mutation == "closed":
        server.state = "closed"
    else:
        server.stale_at = 1
    with pytest.raises(ProposalError):
        run(proposal, server)
    assert not any(method == "POST" for method, _, _ in server.calls)


@pytest.mark.parametrize(
    "mutation", ["closed", "not_draft", "base", "head", "tree", "parent"]
)
def test_changed_repair_refused_without_overwrite(proposal, mutation):
    server = Server(proposal[2])
    run(proposal, server)
    if mutation == "closed":
        server.pr["state"] = "closed"
    elif mutation == "not_draft":
        server.pr["draft"] = False
    elif mutation in {"base", "head"}:
        server.pr[mutation]["ref" if mutation == "base" else "sha"] = "other"
    elif mutation == "tree":
        server.commits["repair"]["tree"]["sha"] = "other"
    else:
        server.commits["repair"]["parents"] = []
    with pytest.raises(ProposalError, match="Existing"):
        run(proposal, server)
    assert all(method != "PATCH" for method, _, _ in server.calls)


def test_rate_limit_after_branch_creation_recovers_without_duplicate_commit(proposal):
    server = Server(proposal[2])
    server.fail_create_pr = True
    with pytest.raises(GitHubError):
        run(proposal, server)
    assert server.branch == "repair"
    run(proposal, server)
    assert (
        sum(
            method == "POST" and path == "git/commits"
            for method, path, _ in server.calls
        )
        == 1
    )


@pytest.mark.parametrize("collision", ["ref", "pr"])
def test_concurrent_identical_publication_recovers(proposal, collision):
    server = Server(proposal[2])
    server.fail_ref = collision == "ref"
    server.collision = collision == "pr"
    assert run(proposal, server)["url"].endswith("/8")


@pytest.mark.parametrize("stale_at", [2, 3, 4])
def test_head_movement_during_publication_is_reported(proposal, stale_at):
    server = Server(proposal[2])
    server.stale_at = stale_at
    with pytest.raises(ProposalError, match="head changed"):
        run(proposal, server)
    if stale_at < 4:
        assert server.pr is None
    else:
        assert server.pr["draft"] is True


def test_tampered_artifact_never_reaches_network(proposal, tmp_path):
    root, artifact, head = proposal
    data = json.loads(artifact.read_text())
    data["git"]["head"] = "0" * 40
    invalid = tmp_path / "invalid.json"
    invalid.write_text(json.dumps(data))
    api = Mock()
    with pytest.raises(ProposalError):
        run((root, invalid, head), api)
    api.assert_not_called()


def test_credentials_and_repository_validation():
    with pytest.raises(ProposalError, match="GITHUB_TOKEN"):
        github_api("owner/repo", "")
    with pytest.raises(ProposalError, match="owner/name"):
        github_api("https://evil.invalid", "secret")


def test_workflow_separates_trusted_analysis_from_publication():
    text = Path(".github/workflows/docguard-repair.yml").read_text()
    assert "workflow_dispatch:" in text and "pull_request_target:" not in text
    assert "environment: docguard-publish" in text
    assert "needs: analyze" in text and "EXPECTED_DIGEST" in text
    assert "python -P -m docguard publish-proposal" in text
    assert "ref: ${{ github.sha }}" in text
    assert "persist-credentials: false" in text
    action = Path("action.yml").read_text()
    assert "--max-documents 1" in action and "--dry-run" in action
    assert "pip install" not in action
