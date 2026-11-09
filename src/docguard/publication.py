"""Explicit, bounded GitHub draft publication of one locally validated proposal.

Never executes target code, updates an existing branch, merges, or publishes by
default. GitHub writes happen only through publish=True after local validation.
"""

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from docguard.ai.files import ProposalError, digest, parse_json, read_bytes
from docguard.ai.git_proposals import apply_git_proposal
from docguard.ai.proposals import _decision
from docguard.docs.mapping import load_mapping
from docguard.git_review import _git

API = Callable[[str, str, dict[str, Any] | None], Any]


class GitHubError(ProposalError):
    def __init__(self, status: int):
        self.status = status
        super().__init__(
            f"GitHub request failed (HTTP {status}); verify permissions/rate limits and retry the same artifact"
        )


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def github_api(repository: str, token: str) -> API:
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository
    ):
        raise ProposalError("GitHub repository must be owner/name")
    if not token.strip():
        raise ProposalError("Set GITHUB_TOKEN to publish; preview needs no token")
    if any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise ProposalError("GITHUB_TOKEN contains invalid characters")
    opener = urllib.request.build_opener(_NoRedirect())

    def request(
        method: str, endpoint: str, payload: dict[str, Any] | None = None
    ) -> Any:
        req = urllib.request.Request(
            f"https://api.github.com/repos/{repository}/{endpoint}",
            data=json.dumps(payload).encode() if payload is not None else None,
            method=method,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "Content-Type": "application/json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "docguard",
            },
        )
        try:
            with opener.open(req, timeout=30) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise ProposalError("GitHub response exceeds size limit")
                return json.loads(raw)
        except urllib.error.HTTPError as error:
            raise GitHubError(error.code) from None
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            raise ProposalError(
                "GitHub transport/response failure; retry the same artifact"
            ) from None

    return request


def publish_proposal(
    artifact: Path,
    root: Path,
    document: str,
    repository: str,
    source_pr: int,
    *,
    publish: bool = False,
    api: API | None = None,
) -> dict[str, Any]:
    if (
        not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9_.-]*/[A-Za-z0-9][A-Za-z0-9_.-]*", repository
        )
        or source_pr < 1
    ):
        raise ProposalError("Specify owner/repository and a positive source PR number")
    # Full commit, evidence, mapping, scope, source and stale-document validation.
    artifact_bytes = read_bytes(artifact, 10_000_000)
    diff = apply_git_proposal(artifact, root, document, check=True)
    if read_bytes(artifact, 10_000_000) != artifact_bytes:
        raise ProposalError("Proposal artifact changed during validation")
    data = parse_json(artifact_bytes.decode("utf-8"))
    assert isinstance(data, dict)
    head = data["git"]["head"]
    row = next(
        row["proposal"]
        for row in data["proposals"]
        if row["proposal"]["document"] == document
    )
    scoped = any(
        m.document == document and m.section
        for m in load_mapping(root / data["git"]["mapping"], root)
    )
    decision = {key: row[key] for key in ("action", "summary", "content", "warnings")}
    _, _, content, _ = _decision(
        decision, row["original"], normalize_newlines=not scoped
    )
    if content is None:
        raise ProposalError("Only revise proposals can be published")
    mode = (
        _git(root, "--literal-pathspecs", "ls-tree", head, "--", document)
        .decode()
        .split()[0]
    )
    if mode not in {"100644", "100755"}:
        raise ProposalError("Publication requires a tracked regular document")
    branch = f"docguard/pr-{source_pr}-{head[:12]}-{digest(document.encode())[:12]}"
    plan: dict[str, Any] = {
        "mode": "publish" if publish else "preview",
        "repository": repository,
        "source_pr": source_pr,
        "head": head,
        "branch": branch,
        "document": document,
        "diff": diff,
        "content_sha256": digest(content.encode()),
        "draft": True,
    }
    if not publish:
        return plan
    request = api or github_api(repository, os.environ.get("GITHUB_TOKEN", ""))

    def target() -> str:
        pr = request("GET", f"pulls/{source_pr}", None)
        if pr.get("state") != "open" or pr.get("merged"):
            raise ProposalError("Source PR is closed or merged")
        if (pr["head"].get("repo") or {}).get(
            "full_name", ""
        ).lower() != repository.lower():
            raise ProposalError(
                "Fork PR publication is unsupported; export and review the proposal manually"
            )
        if pr["head"]["sha"] != head:
            raise ProposalError("Source PR head changed; regenerate before publication")
        return str(pr["head"]["ref"])

    base_branch = target()
    base_tree = request("GET", f"git/commits/{head}", None)["tree"]["sha"]
    tree = request(
        "POST",
        "git/trees",
        {
            "base_tree": base_tree,
            "tree": [
                {"path": document, "mode": mode, "type": "blob", "content": content}
            ],
        },
    )["sha"]
    ref_endpoint = "git/ref/heads/" + urllib.parse.quote(branch, safe="/")
    try:
        commit = request("GET", ref_endpoint, None)["object"]["sha"]
    except GitHubError as error:
        if error.status != 404:
            raise
        commit = request(
            "POST",
            "git/commits",
            {
                "message": f"docs: repair documentation for PR #{source_pr}",
                "tree": tree,
                "parents": [head],
            },
        )["sha"]
        if target() != base_branch:
            raise ProposalError("Source branch changed; regenerate")
        try:
            request("POST", "git/refs", {"ref": f"refs/heads/{branch}", "sha": commit})
        except GitHubError as collision:
            if collision.status != 422:
                raise
            # Another identical run may have created it; verify before reuse.
            commit = request("GET", ref_endpoint, None)["object"]["sha"]
    existing = request("GET", f"git/commits/{commit}", None)
    if existing["tree"]["sha"] != tree or [p["sha"] for p in existing["parents"]] != [
        head
    ]:
        raise ProposalError("Existing repair branch differs; refusing to overwrite it")
    query = urllib.parse.urlencode(
        {
            "state": "all",
            "head": f"{repository.split('/')[0]}:{branch}",
            "per_page": 100,
        }
    )

    def find_pr() -> Any:
        found = request("GET", f"pulls?{query}", None)
        if len(found) > 1:
            raise ProposalError("Multiple repair PRs found; review manually")
        if found:
            pr = found[0]
            if (
                pr["state"] != "open"
                or not pr.get("draft")
                or pr["base"]["ref"] != base_branch
                or pr["head"]["sha"] != commit
            ):
                raise ProposalError(
                    "Existing repair PR was closed or changed; review manually"
                )
            return pr
        return None

    if target() != base_branch:
        raise ProposalError("Source branch changed; regenerate")
    pr = find_pr()
    reused = pr is not None
    if pr is None:
        try:
            pr = request(
                "POST",
                "pulls",
                {
                    "title": f"docs: proposed repair for #{source_pr}",
                    "body": f"DocGuard proposal for source PR #{source_pr} at `{head}`.\n\nReview the documentation patch and evidence artifact before merging. This draft targets the source PR branch. No automatic merge is performed.",
                    "head": branch,
                    "base": base_branch,
                    "draft": True,
                    "maintainer_can_modify": False,
                },
            )
        except GitHubError as collision:
            if collision.status != 422:
                raise
            pr = find_pr()
            if pr is None:
                raise
            reused = True
    # GitHub cannot atomically lock the source branch while creating a PR.
    # A concurrent change leaves a draft, and is explicitly reported as stale.
    if target() != base_branch:
        raise ProposalError(
            "Source branch changed during publication; inspect the draft"
        )
    plan.update(url=pr["html_url"], reused=reused)
    return plan
