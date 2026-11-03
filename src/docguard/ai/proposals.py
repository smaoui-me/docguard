"""Prepare evidence, generate proposals, and explicitly preview/apply one edit."""

import difflib
import json
import os
import re
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from tempfile import NamedTemporaryFile

from docguard.ai.files import (
    ProposalError,
    array,
    digest,
    document_path,
    object_fields,
    parse_json,
    read_bytes,
    relative_path,
    string,
    write_new_json,
)
from docguard.ai.provider import generate, request_payload
from docguard.code.index import index_repository
from docguard.code.python_parser import _parse_source
from docguard.code.scanner import discover_python_files
from docguard.code.snapshots import load_snapshot
from docguard.docs.mapping import load_mapping
from docguard.docs.review import review_documents

MAX_CONTEXT_CHARS = 40000


@dataclass(frozen=True)
class PreparedDocument:
    document: str
    original: str
    original_sha256: str
    context: dict[str, object]


@dataclass(frozen=True)
class Proposal:
    document: str
    original: str
    original_sha256: str
    action: str
    summary: str
    content: str | None
    warnings: tuple[str, ...]


def source_digest(root: Path) -> str:
    """Include whole discovered files, so even global/constant edits invalidate proposals."""
    root = root.resolve(strict=True)
    files = [
        (path.relative_to(root).as_posix(), digest(read_bytes(path)))
        for path in discover_python_files(root)
    ]
    return digest(json.dumps(files, sort_keys=True).encode("utf-8"))


def prepare_documents(
    root: Path,
    baseline: Path,
    mapping: Path,
    selected: Sequence[str] = (),
    max_documents: int = 3,
) -> tuple[str, tuple[PreparedDocument, ...]]:
    """Preflight every context before making any API requests. No silent truncation."""
    if not 1 <= max_documents <= 20:
        raise ProposalError("max-documents must be between 1 and 20")
    root = root.resolve(strict=True)
    source_hash = source_digest(root)
    before, after = load_snapshot(baseline), index_repository(root)
    mappings = load_mapping(mapping, root)
    report = review_documents(mappings, before, after)
    affected = {item.document: item for item in report.documents}
    if set(selected) - affected.keys():
        raise ProposalError("Selected document is not flagged for review")
    names = sorted(set(selected) if selected else affected)
    if len(names) > max_documents:
        raise ProposalError(
            f"{len(names)} documents exceed max-documents={max_documents}; select --document or raise the limit"
        )
    links = {item.document: item.entity_ids for item in mappings}
    prepared: list[PreparedDocument] = []
    for name in names:
        raw = read_bytes(document_path(root, name))
        original = raw.decode("utf-8")
        entities: list[dict[str, object]] = []
        for entity_id in links[name]:
            old, current = before.get(entity_id), after.get(entity_id)
            snippet: str | None = None
            if current is not None:
                source_path = root / relative_path(current.file_path)
                if not source_path.resolve(strict=True).is_relative_to(root):
                    raise ProposalError("Source path resolves outside repository")
                source = read_bytes(source_path).decode("utf-8")
                # Check that snippets and indexed metadata came from the same source.
                parsed = {
                    item.id: item for item in _parse_source(source, current.file_path)
                }
                if parsed.get(entity_id) != current:
                    raise ProposalError(
                        "Source changed during context preparation; retry"
                    )
                snippet = "".join(
                    source.splitlines(keepends=True)[
                        current.start_line - 1 : current.end_line
                    ]
                )
            entities.append(
                {
                    "entity_id": entity_id,
                    "before": asdict(old) if old else None,
                    "after": asdict(current) if current else None,
                    "current_source": snippet,
                }
            )
        context: dict[str, object] = {
            "document": name,
            "document_text": original,
            "reasons": [asdict(reason) for reason in affected[name].reasons],
            "entities": entities,
            "limitations": "Old function bodies and external dependencies are unavailable. Assess documentation against current evidence; missing history alone does not require review. If missing dependencies prevent verifying a behavioral claim, request review instead of inferring their effects.",
        }
        if len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT_CHARS:
            raise ProposalError(
                f"Context for {name} exceeds {MAX_CONTEXT_CHARS} characters; split the document/mapping"
            )
        prepared.append(PreparedDocument(name, original, digest(raw), context))
    if source_digest(root) != source_hash:
        raise ProposalError("Source changed during context preparation; retry")
    return source_hash, tuple(prepared)


def _decision(
    value: object, original: str
) -> tuple[str, str, str | None, tuple[str, ...]]:
    data = object_fields(value, {"action", "summary", "content", "warnings"})
    action, summary = string(data["action"]), string(data["summary"])
    if action not in {"revise", "unchanged", "needs_review"} or not summary.strip():
        raise ProposalError("Invalid proposal action or empty summary")
    warnings = tuple(string(item) for item in array(data["warnings"]))
    content = None if data["content"] is None else string(data["content"])
    if action == "revise":
        if content is None or not content.strip():
            raise ProposalError("A revision must contain a non-empty complete document")
        if len(content) > 60000:
            raise ProposalError("Proposed document exceeds 60000 characters")
        # Preserve the original newline convention for ordinary UTF-8 documents.
        content = content.replace("\r\n", "\n")
        if "\r\n" in original and "\n" not in original.replace("\r\n", ""):
            content = content.replace("\n", "\r\n")
        if content == original:
            action, content = "unchanged", None
    elif content is not None:
        raise ProposalError("Non-revision decisions must have null content")
    return action, summary, content, warnings


def suggest(
    root: Path,
    baseline: Path,
    mapping: Path,
    output: Path,
    model: str = "gpt-4.1-mini",
    dry_run: bool = False,
    selected: Sequence[str] = (),
    max_documents: int = 3,
    generator: Callable[[str, dict[str, object]], object] | None = None,
    provider: str = "openai",
) -> int:
    """Write a new context/proposal artifact; never modify documentation here."""
    if output.exists() or output.is_symlink():
        raise ProposalError("Output already exists; choose a new JSON filename")
    if output.suffix.lower() != ".json" or not output.parent.is_dir():
        raise ProposalError("Output must be a .json file in an existing directory")
    if not model.strip():
        raise ProposalError("Model name cannot be empty")
    root = root.resolve(strict=True)
    source_hash, prepared = prepare_documents(
        root, baseline, mapping, selected, max_documents
    )
    if dry_run:
        write_new_json(
            output,
            {
                "schema_version": 1,
                "kind": "docguard.ai.requests",
                "model": model,
                "requests": [
                    request_payload(model, item.context, provider) for item in prepared
                ],
            },
        )
        return len(prepared)
    proposals: list[Proposal] = []
    for item in prepared:
        action, summary, content, warnings = _decision(
            (
                generator(model, item.context)
                if generator
                else generate(model, item.context, provider=provider)
            ),
            item.original,
        )
        proposals.append(
            Proposal(
                item.document,
                item.original,
                item.original_sha256,
                action,
                summary,
                content,
                warnings,
            )
        )
    if source_digest(root) != source_hash:
        raise ProposalError("Source changed while generating proposals; regenerate")
    for item in prepared:
        if (
            digest(read_bytes(document_path(root, item.document)))
            != item.original_sha256
        ):
            raise ProposalError(
                f"Document changed while generating proposals: {item.document}"
            )
    write_new_json(
        output,
        {
            "schema_version": 1,
            "kind": "docguard.ai.proposals",
            "model": model,
            "source_tree_sha256": source_hash,
            "proposals": [asdict(item) for item in proposals],
        },
    )
    return len(proposals)


def _sha(value: object) -> str:
    text = string(value)
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise ProposalError("Expected a SHA-256 digest")
    return text


def load_proposals(path: Path) -> tuple[str, tuple[Proposal, ...]]:
    data = object_fields(
        parse_json(read_bytes(path, 10_000_000).decode("utf-8")),
        {
            "schema_version",
            "kind",
            "model",
            "source_tree_sha256",
            "proposals",
        },
    )
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] != 1
        or data["kind"] != "docguard.ai.proposals"
    ):
        raise ProposalError(
            "Expected a version 1 AI proposal artifact, not a dry-run request"
        )
    string(data["model"])
    source_hash = _sha(data["source_tree_sha256"])
    proposals: list[Proposal] = []
    names: set[str] = set()
    for value in array(data["proposals"]):
        item = object_fields(
            value,
            {
                "document",
                "original",
                "original_sha256",
                "action",
                "summary",
                "content",
                "warnings",
            },
        )
        name, original = string(item["document"]), string(item["original"])
        relative_path(name)
        if name in names:
            raise ProposalError(f"Duplicate proposal for {name}")
        names.add(name)
        original_hash = _sha(item["original_sha256"])
        if digest(original.encode("utf-8")) != original_hash:
            raise ProposalError("Proposal original text does not match its hash")
        decision = {
            key: item[key] for key in ("action", "summary", "content", "warnings")
        }
        action, summary, content, warnings = _decision(decision, original)
        proposals.append(
            Proposal(name, original, original_hash, action, summary, content, warnings)
        )
    return source_hash, tuple(proposals)


def apply_proposal(path: Path, root: Path, document: str, check: bool = False) -> str:
    """Preview or apply exactly one selected edit, refusing stale source/documents."""
    source_hash, proposals = load_proposals(path)
    selected = next((item for item in proposals if item.document == document), None)
    if selected is None:
        raise ProposalError(f"No proposal for {document}")
    if selected.action != "revise" or selected.content is None:
        raise ProposalError(
            f"Proposal is {selected.action}, not an applicable revision"
        )
    root = root.resolve(strict=True)
    destination = document_path(root, document)
    if source_digest(root) != source_hash:
        raise ProposalError(
            "Source files changed since generation; regenerate the proposal"
        )
    if digest(read_bytes(destination)) != selected.original_sha256:
        raise ProposalError(
            "Document changed since generation; regenerate the proposal"
        )
    diff = "".join(
        difflib.unified_diff(
            selected.original.splitlines(keepends=True),
            selected.content.splitlines(keepends=True),
            fromfile=f"a/{document}",
            tofile=f"b/{document}",
        )
    )
    if check:
        return diff
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            dir=destination.parent, prefix=".docguard-", suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(selected.content.encode("utf-8"))
        os.chmod(temporary, destination.stat().st_mode)
        # Recheck the document immediately before replacement.
        if (
            digest(read_bytes(document_path(root, document)))
            != selected.original_sha256
        ):
            raise ProposalError(
                "Document changed before apply; regenerate the proposal"
            )
        os.replace(temporary, destination)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return diff
