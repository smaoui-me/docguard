"""Read versioned documentation-to-entity mappings without parsing document text."""

import json
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath


class MappingError(ValueError):
    """Invalid mapping configuration or an unresolved reference."""


@dataclass(frozen=True)
class DocumentMapping:
    document: str
    entity_ids: tuple[str, ...]


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise MappingError(f"Duplicate mapping key: {key}")
        result[key] = value
    return result


def load_mapping(path: Path, root: Path) -> tuple[DocumentMapping, ...]:
    """Load v1 mappings; document paths are canonical forward-slash root-relative paths.

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
    if type(data["schema_version"]) is not int or data["schema_version"] != 1:
        raise MappingError("Unsupported mapping schema version; expected 1")
    documents = data["documents"]
    if not isinstance(documents, dict):
        raise MappingError(
            "documents must be an object mapping paths to entity ID arrays"
        )
    result: list[DocumentMapping] = []
    resolved_documents: set[Path] = set()
    for document, ids in sorted(documents.items()):
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
        result.append(DocumentMapping(document, tuple(sorted(ids))))
    return tuple(result)
