"""Read versioned documentation-to-entity mappings without parsing document text."""

import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


class MappingError(ValueError):
    """Invalid mapping configuration or an unresolved reference."""


@dataclass(frozen=True)
class ClaimRequirement:
    id: str
    quote: str
    required_evidence: tuple[str, ...]


@dataclass(frozen=True)
class DocumentMapping:
    document: str
    entity_ids: tuple[str, ...]
    claims: tuple[ClaimRequirement, ...] = ()
    section: tuple[str, ...] = ()

    @property
    def dependency_ids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    ref.split(":", 1)[1]
                    for claim in self.claims
                    for ref in claim.required_evidence
                }
            )
        )


def parse_claims(value: object) -> tuple[ClaimRequirement, ...]:
    if not isinstance(value, list) or not value or len(value) > 50:
        raise MappingError("claims must contain between 1 and 50 requirements")
    result = []
    seen: set[str] = set()
    for claim in value:
        if not isinstance(claim, dict) or set(claim) != {
            "id",
            "quote",
            "required_evidence",
        }:
            raise MappingError("Each claim requires id, quote and required_evidence")
        name, quote, refs = claim["id"], claim["quote"], claim["required_evidence"]
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", name)
            or name in seen
        ):
            raise MappingError("Claim IDs must be unique simple identifiers")
        if not isinstance(quote, str) or not quote.strip() or len(quote) > 4000:
            raise MappingError(
                "Claim quote must be non-empty and at most 4000 characters"
            )
        if not isinstance(refs, list) or not refs or len(refs) > 50:
            raise MappingError(
                "required_evidence must contain between 1 and 50 evidence IDs"
            )
        for ref in refs:
            if not isinstance(ref, str) or not re.fullmatch(
                r"(?:before|after):[^:]+:.+", ref
            ):
                raise MappingError(
                    "Required evidence IDs must use before:path.py:entity or after:path.py:entity"
                )
            _, path, entity = ref.split(":", 2)
            relative = PurePosixPath(path)
            if (
                "\\" in path
                or relative.is_absolute()
                or ".." in relative.parts
                or relative.as_posix() != path
                or not path.endswith(".py")
                or not entity.strip()
                or any(ord(c) < 32 for c in ref)
            ):
                raise MappingError("Invalid required evidence ID")
        if len(set(refs)) != len(refs):
            raise MappingError("Duplicate required evidence ID")
        seen.add(name)
        result.append(ClaimRequirement(name, quote, tuple(sorted(refs))))
    return tuple(result)


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MappingError(f"Duplicate mapping key: {key}")
        result[key] = value
    return result


def load_mapping(path: Path, root: Path) -> tuple[DocumentMapping, ...]:
    """Load v1 links or v2 links with explicit claim evidence requirements.

    All documents must exist inside root, including after symlink resolution.
    Entity existence is checked during review against both snapshots.
    """
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise NotADirectoryError(root)
    try:
        data = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MappingError(f"Invalid mapping {path}: {error}") from error
    if not isinstance(data, dict) or set(data) != {"schema_version", "documents"}:
        raise MappingError("Mapping requires exactly schema_version and documents")
    if type(data["schema_version"]) is not int or data["schema_version"] not in {1, 2}:
        raise MappingError("Unsupported mapping schema version; expected 1 or 2")
    documents = data["documents"]
    if not isinstance(documents, dict):
        raise MappingError(
            "documents must be an object mapping paths to entity ID arrays"
        )
    result: list[DocumentMapping] = []
    resolved_documents: set[Path] = set()
    for document, ids in sorted(documents.items()):
        claims: tuple[ClaimRequirement, ...] = ()
        section: tuple[str, ...] = ()
        if data["schema_version"] == 2:
            if not isinstance(ids, dict) or set(ids) not in (
                {"entity_ids", "claims"},
                {"entity_ids", "claims", "section"},
            ):
                raise MappingError("Version 2 documents require entity_ids and claims")
            if "section" in ids:
                value = ids["section"]
                if (
                    not isinstance(value, list)
                    or not value
                    or any(
                        not isinstance(v, str)
                        or not re.fullmatch(r"#{1,6} [^\r\n]+", v)
                        for v in value
                    )
                ):
                    raise MappingError("section must be a non-empty ATX heading path")
                section = tuple(value)
                if not document.endswith(".md"):
                    raise MappingError("Section edits support Markdown (.md) only")
            if ids["claims"] != [] or not section:
                claims = parse_claims(ids["claims"])
            ids = ids["entity_ids"]
        relative = PurePosixPath(document)
        if (
            not document
            or "\\" in document
            or PureWindowsPath(document).drive
            or relative.is_absolute()
            or ".." in relative.parts
            or relative.as_posix() != document
            or document == "."
        ):
            raise MappingError(
                f"Document path must be normalized and repository-relative: {document!r}"
            )
        resolved = (root / document).resolve()
        if not resolved.is_relative_to(root):
            raise MappingError(f"Document resolves outside repository: {document}")
        if not resolved.is_file():
            raise MappingError(f"Document does not exist or is not a file: {document}")
        if resolved in resolved_documents:
            raise MappingError(
                f"Multiple document paths resolve to the same file: {document}"
            )
        resolved_documents.add(resolved)
        if not isinstance(ids, list) or not ids:
            raise MappingError(
                f"Document {document} requires a non-empty array of entity IDs"
            )
        if any(
            not isinstance(entity_id, str) or not entity_id.strip() for entity_id in ids
        ):
            raise MappingError(f"Entity IDs for {document} must be non-empty strings")
        if len(set(ids)) != len(ids):
            raise MappingError(f"Duplicate entity reference in {document}")
        result.append(DocumentMapping(document, tuple(sorted(ids)), claims, section))
    return tuple(result)
