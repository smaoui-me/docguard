"""Upstream-authored documentation references, kept outside model contexts."""

import difflib
from pathlib import Path
from typing import Any

from docguard.ai.files import ProposalError, digest, parse_json, read_bytes
from docguard.ai.upstream import _blob, extract_section

REVIEW_LEVELS = ("upstream_reference", "project_reviewed", "independently_audited")


def review_level(label: dict[str, Any]) -> str:
    value = label.get(
        "review_level",
        "independently_audited" if label.get("independent") else "project_reviewed",
    )
    if not isinstance(value, str) or value not in REVIEW_LEVELS:
        raise ProposalError("Unknown label review level")
    if (value == "independently_audited") != label.get("independent", False):
        raise ProposalError("Review level and independence attestation disagree")
    return value


def upstream_reference(repository: Path, case: dict[str, Any]) -> dict[str, Any]:
    documents = {}
    for side in ("base", "head"):
        blob = _blob(repository, case[side], case["document_path"])
        selected, start, end = extract_section(
            blob,
            case.get("base_section", case["section"])
            if side == "base"
            else case["section"],
        )
        documents[side] = {
            "text": selected.decode("utf-8"),
            "sha256": digest(selected),
            "blob_sha256": digest(blob),
            "revision": case[side],
            "path": case["document_path"],
            "start_line": start,
            "end_line": end,
        }
    before, after = documents["base"]["text"], documents["head"]["text"]
    return {
        "kind": "upstream_documentation",
        "documents": documents,
        "changed": before != after,
        "diff": "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile="upstream/base",
                tofile="upstream/head",
            )
        ),
        "role": "withheld_reference_only",
        "caveat": "An upstream-authored patch is reference evidence, not a guarantee of semantic correctness or relevant scope.",
    }


def validate_reference(reference: object) -> None:
    if (
        not isinstance(reference, dict)
        or reference.get("kind") != "upstream_documentation"
        or reference.get("role") != "withheld_reference_only"
    ):
        raise ProposalError("Invalid upstream reference")
    documents = reference.get("documents")
    if not isinstance(documents, dict):
        raise ProposalError("Missing reference documents")
    for side in ("base", "head"):
        doc = documents.get(side)
        if (
            not isinstance(doc, dict)
            or not isinstance(doc.get("text"), str)
            or doc.get("sha256") != digest(doc["text"].encode("utf-8"))
        ):
            raise ProposalError("Reference document hash mismatch")
    if reference.get("changed") != (
        documents["base"]["text"] != documents["head"]["text"]
    ):
        raise ProposalError("Reference change flag mismatch")


def provisional_action(case: dict[str, Any]) -> str:
    reference = case.get("upstream_reference")
    validate_reference(reference)
    assert isinstance(reference, dict)
    if not reference["changed"] or case["provenance"]["variant"] not in (
        "base_docs",
        "authentic_head",
    ):
        raise ProposalError(
            "Automatic reference labels require a changed upstream section and authentic/base-doc variants; review other cases manually"
        )
    if case["provenance"]["document_selections"]["head"].get("authored_prefix"):
        raise ProposalError(
            "Authored prefixes cannot receive upstream reference labels"
        )
    side = "base" if case["provenance"]["variant"] == "base_docs" else "head"
    expected = reference["documents"][side]["text"].replace("\r\n", "\n")
    if any(
        context["document_text"].replace("\r\n", "\n") != expected
        for context in case["contexts"].values()
    ):
        raise ProposalError(
            "Reference labels require the exact upstream document variant as model input"
        )
    return "revise" if case["provenance"]["variant"] == "base_docs" else "unchanged"


def load_discussions(
    path: Path | None, pr_urls: set[str]
) -> dict[str, list[dict[str, Any]]]:
    """Accept explicit snapshots of GitHub issue/review comments, never fetch implicitly."""
    if path is None:
        return {}
    raw = parse_json(read_bytes(path).decode("utf-8-sig"))
    if not isinstance(raw, list):
        raise ProposalError(
            "Discussion snapshot must be a JSON array of GitHub comments"
        )
    result: dict[str, list[dict[str, Any]]] = {}
    for comment in raw:
        if not isinstance(comment, dict):
            raise ProposalError("Invalid discussion comment")
        url, body = comment.get("html_url"), comment.get("body")
        author = (
            comment.get("user", {}).get("login")
            if isinstance(comment.get("user"), dict)
            else None
        )
        updated = comment.get("updated_at")
        pr = next(
            (pr for pr in pr_urls if isinstance(url, str) and url.startswith(pr + "#")),
            None,
        )
        if pr is None or not all(
            isinstance(v, str) and v.strip() for v in (body, author, updated)
        ):
            raise ProposalError(
                "Discussion comments need a selected PR URL, body, author and updated_at"
            )
        assert isinstance(body, str)
        result.setdefault(pr, []).append(
            {
                "url": url,
                "text": body,
                "author": author,
                "updated_at": updated,
                "sha256": digest(body.encode("utf-8")),
            }
        )
    return result
