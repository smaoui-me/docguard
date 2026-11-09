"""Committed Git evidence and proposals; working-tree edits require explicit apply."""

import difflib
import json
from collections.abc import Callable, Sequence
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.ai.claims import assess_claims, blocked_decision
from docguard.ai.config import AIConfig
from docguard.ai.evidence import EVIDENCE_VERSION, DependencyEvidence
from docguard.ai.files import (
    ProposalError,
    array,
    digest,
    object_fields,
    parse_json,
    read_bytes,
    relative_path,
    string,
    write_new_json,
)
from docguard.ai.proposals import (
    MAX_CONTEXT_CHARS,
    PreparedDocument,
    Proposal,
    _decision,
    apply_proposal,
    prepare_documents,
    source_digest,
)
from docguard.ai.provider import GIT_PROMPT_VERSION, generate, request_payload
from docguard.code.index import index_repository
from docguard.code.models import CodeEntity
from docguard.code.scanner import discover_python_files
from docguard.code.snapshots import save_snapshot
from docguard.docs.mapping import load_mapping
from docguard.docs.reporting import report_document
from docguard.docs.review import removed_mapping_links, review_documents
from docguard.docs.sections import (
    replace_section,
    select_section,
    validate_section_edit,
)
from docguard.git_review import GitTrees, _git, git_trees


def _normalized_source_digest(root: Path) -> str:
    root = root.resolve(strict=True)
    entries = [
        (
            path.relative_to(root).as_posix(),
            digest(read_bytes(path).replace(b"\r\n", b"\n")),
        )
        for path in discover_python_files(root)
    ]
    return digest(json.dumps(entries).encode("utf-8"))


def _evidence(
    root: Path, revision: str, entity: CodeEntity, side: str
) -> dict[str, object]:
    source = read_bytes(root / relative_path(entity.file_path)).decode("utf-8")
    snippet = "".join(
        source.splitlines(keepends=True)[entity.start_line - 1 : entity.end_line]
    )
    return {
        "id": f"{side}:{entity.id}",
        "revision": revision,
        "path": entity.file_path,
        "start_line": entity.start_line,
        "end_line": entity.end_line,
        "text": snippet,
        "sha256": digest(snippet.encode("utf-8")),
    }


def prepare_git_documents(
    trees: GitTrees,
    mapping: str,
    selected: Sequence[str] = (),
    max_documents: int = 3,
    evidence_policy: str = "mapped",
) -> tuple[str, tuple[PreparedDocument, ...], dict[str, object]]:
    """Preflight bounded before/after evidence for every selected document."""
    if evidence_policy not in {"mapped", "direct"}:
        raise ProposalError("Unknown evidence policy")
    mapping_path = relative_path(mapping)
    before, after = index_repository(trees.old), index_repository(trees.new)
    mappings = load_mapping(trees.new / mapping_path, trees.new)
    report = review_documents(mappings, before, after)
    old_map = trees.old / mapping_path
    old_mappings = load_mapping(old_map, trees.old) if old_map.exists() else ()
    from dataclasses import replace

    report = replace(
        report, removed_links=removed_mapping_links(old_mappings, mappings)
    )
    # Keep the generated baseline outside exported trees, even if a repo uses this name.
    with TemporaryDirectory(prefix="docguard-baseline-") as directory:
        baseline = Path(directory) / "baseline.json"
        save_snapshot(before, baseline)
        source_hash, documents = prepare_documents(
            trees.new, baseline, trees.new / mapping_path, selected, max_documents
        )
    links = {item.document: item.entity_ids for item in mappings}
    requirements = {item.document: item.claims for item in mappings}
    scopes = {item.document: item.section for item in mappings}
    collectors = (
        {
            "before": DependencyEvidence(trees.old, before),
            "after": DependencyEvidence(trees.new, after),
        }
        if evidence_policy == "direct"
        else {}
    )
    enriched: list[PreparedDocument] = []
    for document in documents:
        evidence: list[dict[str, object]] = []
        for entity_id in links[document.document]:
            for side, index, root, revision in (
                ("before", before, trees.old, trees.merge_base),
                ("after", after, trees.new, trees.head),
            ):
                if entity_id in index:
                    evidence.append(_evidence(root, revision, index[entity_id], side))
        context = dict(document.context)
        context["evidence"] = evidence
        # Explicit requirements bypass heuristic retrieval, not the context budget.
        for ref in sorted(
            {
                ref
                for claim in requirements[document.document]
                for ref in claim.required_evidence
            }
        ):
            if any(entry["id"] == ref for entry in evidence):
                continue
            side, entity_id = ref.split(":", 1)
            index, root, revision = (
                (before, trees.old, trees.merge_base)
                if side == "before"
                else (after, trees.new, trees.head)
            )
            if entity_id in index:
                evidence.append(_evidence(root, revision, index[entity_id], side))
        old_doc = trees.old / relative_path(document.document)
        context["previous_document_text"] = (
            read_bytes(old_doc).decode("utf-8") if old_doc.is_file() else None
        )
        if scopes[document.document] and old_doc.is_file():
            try:
                old_raw = read_bytes(old_doc)
                context["previous_document_text"] = select_section(
                    old_raw, scopes[document.document]
                ).text(old_raw)
            except ProposalError:
                context["previous_document_text"] = None
        context["git"] = {
            "base": trees.base,
            "head": trees.head,
            "merge_base": trees.merge_base,
        }
        context["changes"] = [
            {
                "entity_id": key,
                "diff": "".join(
                    difflib.unified_diff(
                        next(
                            (
                                str(e["text"])
                                for e in evidence
                                if e["id"] == f"before:{key}"
                            ),
                            "",
                        ).splitlines(keepends=True),
                        next(
                            (
                                str(e["text"])
                                for e in evidence
                                if e["id"] == f"after:{key}"
                            ),
                            "",
                        ).splitlines(keepends=True),
                        fromfile=f"before/{key}",
                        tofile=f"after/{key}",
                    )
                ),
            }
            for key in links[document.document]
        ]
        context["limitations"] = (
            "Before and after snippets are provided for mapped entities only. Imports, globals and dependencies may be missing. Judge the HEAD document against HEAD source; request review for claims whose effects cannot be verified. Renames are not inferred."
        )
        if evidence_policy == "direct":
            context["evidence_selection"] = {
                "policy": "direct",
                "version": EVIDENCE_VERSION,
                "max_depth": 2,
                "max_items_per_side": 12,
            }
            context["limitations"] = (
                "Mapped entities plus bounded static references are supplied. Literal assignments describe initialization, not guaranteed runtime values. Dynamic dispatch, external dependencies and omitted references remain uncertain; use needs_review when missing evidence prevents verifying a claim. No runtime behavior or rename is inferred."
            )
            issues: list[dict[str, str]] = []
            for side, revision in (("before", trees.merge_base), ("after", trees.head)):
                available = max(
                    0,
                    MAX_CONTEXT_CHARS
                    - len(json.dumps(context, ensure_ascii=False))
                    - 7000,
                )
                additions, missing = collectors[side].expand(
                    list(links[document.document]),
                    side,
                    revision,
                    max_chars=min(8000, available),
                )
                known_ids = {entry["id"] for entry in evidence}
                evidence.extend(
                    entry for entry in additions if entry["id"] not in known_ids
                )
                issues.extend(missing)
            context["evidence_gaps"] = issues
        if requirements[document.document]:
            context["claim_requirements"] = assess_claims(
                requirements[document.document], str(context["document_text"]), evidence
            )
        if len(json.dumps(context, ensure_ascii=False)) > MAX_CONTEXT_CHARS:
            raise ProposalError(
                "Git evidence exceeds context limit; narrow the document mapping"
            )
        enriched.append(
            PreparedDocument(
                document.document, document.original, document.original_sha256, context
            )
        )
    return source_hash, tuple(enriched), report_document(report)


def validate_citations(value: object, evidence: object, action: str) -> list[str]:
    ids = [string(item) for item in array(value)]
    entries = array(evidence)
    known = {string(item["id"]) for item in entries if isinstance(item, dict)}
    if len(ids) != len(set(ids)) or set(ids) - known:
        raise ProposalError("Proposal cites duplicate or unknown evidence IDs")
    if action in {"revise", "unchanged"} and not ids:
        raise ProposalError("Revision/unchanged decisions must cite supplied evidence")
    return ids


def suggest_git(
    root: Path,
    base: str,
    head: str,
    mapping: str,
    output: Path,
    config: AIConfig,
    *,
    dry_run: bool = False,
    selected: Sequence[str] = (),
    max_documents: int = 3,
    evidence_policy: str = "mapped",
    generator: Callable[[str, dict[str, object]], object] | None = None,
) -> int:
    if (
        output.exists()
        or output.is_symlink()
        or output.suffix.lower() != ".json"
        or not output.parent.is_dir()
    ):
        raise ProposalError("Output must be a new .json file in an existing directory")
    with git_trees(root, base, head) as trees:
        source_hash, prepared, review = prepare_git_documents(
            trees, mapping, selected, max_documents, evidence_policy
        )
        provenance = {
            "base": trees.base,
            "head": trees.head,
            "merge_base": trees.merge_base,
            "mapping": mapping,
        }
        routes = {
            item.document: item.context["claim_requirements"]
            for item in prepared
            if "claim_requirements" in item.context
        }
        if routes:
            review["claim_requirements"] = routes
        if dry_run:
            write_new_json(
                output,
                {
                    "schema_version": 2,
                    "evidence_policy": evidence_policy,
                    "evidence_version": EVIDENCE_VERSION,
                    "kind": "docguard.ai.git-requests",
                    "git_prompt_version": GIT_PROMPT_VERSION,
                    "git": provenance,
                    "review": review,
                    "requests": [
                        request_payload(config.model, item.context, config.provider)
                        for item in prepared
                        if blocked_decision(item.context) is None
                    ],
                },
            )
            return len(prepared)
        proposals: list[dict[str, object]] = []
        for item in prepared:
            response = blocked_decision(item.context) or (
                generator(config.model, item.context)
                if generator
                else generate(
                    config.model,
                    item.context,
                    provider=config.provider,
                    api_key=config.api_key,
                )
            )
            data = object_fields(
                response, {"action", "summary", "content", "warnings", "evidence_ids"}
            )
            decision = {
                key: data[key] for key in ("action", "summary", "content", "warnings")
            }
            action, summary, content, warnings = _decision(
                decision, str(item.context["document_text"])
            )
            if content is not None and "section" in item.context:
                scope = tuple(string(v) for v in array(item.context["section"]))
                content = replace_section(
                    item.original.encode("utf-8"), scope, content
                ).decode("utf-8")
            citations = validate_citations(
                data["evidence_ids"], item.context["evidence"], action
            )
            proposal = Proposal(
                item.document,
                item.original,
                item.original_sha256,
                action,
                summary,
                content,
                warnings,
            )
            proposals.append(
                {
                    "proposal": asdict(proposal),
                    "evidence_ids": citations,
                    "evidence": item.context["evidence"],
                }
            )
        write_new_json(
            output,
            {
                "schema_version": 2,
                "evidence_policy": evidence_policy,
                "evidence_version": EVIDENCE_VERSION,
                "kind": "docguard.ai.git-proposals",
                "git_prompt_version": GIT_PROMPT_VERSION,
                "git": provenance,
                "provider": config.provider,
                "model": config.model,
                "source_tree_sha256": source_hash,
                "review": review,
                "proposals": proposals,
            },
        )
        return len(proposals)


def apply_git_proposal(
    path: Path, root: Path, document: str, check: bool = False
) -> str:
    raw = parse_json(read_bytes(path, 10_000_000).decode("utf-8"))
    extra = (
        {"evidence_policy", "evidence_version"}
        if isinstance(raw, dict) and raw.get("schema_version") == 2
        else set()
    )
    data = object_fields(
        raw,
        {
            "schema_version",
            "kind",
            "git_prompt_version",
            "git",
            "provider",
            "model",
            "source_tree_sha256",
            "review",
            "proposals",
        }
        | extra,
    )
    if (
        type(data["schema_version"]) is not int
        or data["schema_version"] not in {1, 2}
        or data["kind"] != "docguard.ai.git-proposals"
    ):
        raise ProposalError("Expected a version 1 Git proposal artifact")
    evidence_policy = string(data.get("evidence_policy", "mapped"))
    if extra and (
        type(data["evidence_version"]) is not int
        or data["evidence_version"] != EVIDENCE_VERSION
    ):
        raise ProposalError("Evidence selector version changed; regenerate proposal")
    provenance = object_fields(data["git"], {"base", "head", "merge_base", "mapping"})
    head = string(provenance["head"])
    if _git(root, "rev-parse", "HEAD").decode().strip() != head:
        raise ProposalError(
            "Checkout HEAD differs from proposal HEAD; use the matching checkout"
        )
    rows = [
        object_fields(item, {"proposal", "evidence", "evidence_ids"})
        for item in array(data["proposals"])
    ]
    proposals: list[object] = []
    # Reconstruct evidence from the exact commits; artifact text alone is not trusted.
    with git_trees(root, string(provenance["base"]), head) as trees:
        if trees.merge_base != provenance["merge_base"]:
            raise ProposalError("Proposal merge base does not match Git history")
        mapping_path = relative_path(string(provenance["mapping"]))
        if read_bytes(root / mapping_path).replace(b"\r\n", b"\n") != read_bytes(
            trees.new / mapping_path
        ).replace(b"\r\n", b"\n"):
            raise ProposalError("Working mapping differs from committed proposal HEAD")
        names = []
        for row in rows:
            proposal = row["proposal"]
            if not isinstance(proposal, dict):
                raise ProposalError("Invalid Git proposal")
            names.append(string(proposal.get("document")))
        source_hash, prepared, _ = prepare_git_documents(
            trees, string(provenance["mapping"]), names, 20, evidence_policy
        )
        if data["source_tree_sha256"] != source_hash:
            raise ProposalError("Proposal source digest does not match committed HEAD")
        evidence = {item.document: item.context["evidence"] for item in prepared}
        originals = {item.document: item for item in prepared}
        working_source_hash = source_digest(root)
        if _normalized_source_digest(root) != _normalized_source_digest(trees.new):
            raise ProposalError("Working source differs from committed proposal HEAD")
        for row, name in zip(rows, names):
            if name not in evidence or row["evidence"] != evidence[name]:
                raise ProposalError("Evidence does not match committed source")
            proposal = row["proposal"]
            assert isinstance(proposal, dict)
            if (
                blocked_decision(originals[name].context) is not None
                and proposal.get("action") != "needs_review"
            ):
                raise ProposalError(
                    "Claim evidence requirements are unmet; regenerate for human review"
                )
            if (
                proposal.get("original") != originals[name].original
                or proposal.get("original_sha256") != originals[name].original_sha256
            ):
                raise ProposalError(
                    "Proposal original document differs from committed HEAD"
                )
            validate_citations(
                row["evidence_ids"], row["evidence"], string(proposal.get("action"))
            )
            proposal = dict(proposal)
            scope = tuple(
                string(v) for v in array(originals[name].context.get("section", []))
            )
            if scope and proposal.get("action") == "revise":
                validate_section_edit(
                    originals[name].original, string(proposal.get("content")), scope
                )
            if name == document:
                from docguard.ai.files import document_path

                actual = read_bytes(document_path(root, name))
                if scope and actual != originals[name].original.encode("utf-8"):
                    raise ProposalError(
                        "Document changed since proposal HEAD (section edits require exact bytes)"
                    )
                if actual.replace(b"\r\n", b"\n") != originals[name].original.encode(
                    "utf-8"
                ).replace(b"\r\n", b"\n"):
                    raise ProposalError("Document changed since proposal HEAD")
                proposal["original"] = actual.decode("utf-8")
                proposal["original_sha256"] = digest(actual)
            proposals.append(proposal)
    # Existing application checks handle source/document staleness and atomic writes.
    with TemporaryDirectory(prefix="docguard-apply-") as directory:
        bundle = Path(directory) / "proposal.json"
        write_new_json(
            bundle,
            {
                "schema_version": 1,
                "kind": "docguard.ai.proposals",
                "model": data["model"],
                "source_tree_sha256": working_source_hash,
                "proposals": proposals,
            },
        )
        scoped = (
            "section" in originals[document].context if document in originals else False
        )
        return apply_proposal(
            bundle, root, document, check, normalize_newlines=not scoped
        )
