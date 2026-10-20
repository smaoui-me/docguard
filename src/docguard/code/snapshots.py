"""Versioned, validated JSON persistence for entity indexes."""

import json
import os
import re
from collections.abc import Mapping
from dataclasses import asdict, fields
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast

from docguard.code.models import CodeEntity, EntityKind, Parameter, ParameterKind

SCHEMA_VERSION = 2


class SnapshotError(ValueError):
    """A snapshot has invalid contents or an unsupported schema version."""


def _object(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise SnapshotError(f"Expected object with fields: {sorted(keys)}")
    return cast(dict[str, object], value)


def _string(value: object) -> str:
    if not isinstance(value, str):
        raise SnapshotError("Expected a string")
    return value


def _optional_string(value: object) -> str | None:
    return None if value is None else _string(value)


def _list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise SnapshotError("Expected an array")
    return cast(list[object], value)


def _line(value: object) -> int:
    if type(value) is not int or value < 1:
        raise SnapshotError("Source lines must be positive integers")
    return value


def _parameter(value: object) -> Parameter:
    data = _object(value, {field.name for field in fields(Parameter)})
    return Parameter(
        name=_string(data["name"]),
        annotation=_optional_string(data["annotation"]),
        default=_optional_string(data["default"]),
        kind=ParameterKind(_string(data["kind"])),
    )


def _entity(value: object) -> CodeEntity:
    data = _object(value, {field.name for field in fields(CodeEntity)})
    start, end = _line(data["start_line"]), _line(data["end_line"])
    if end < start:
        raise SnapshotError("end_line cannot precede start_line")
    fingerprint = _optional_string(data["body_fingerprint"])
    if fingerprint is not None and re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None:
        raise SnapshotError(
            "body_fingerprint must be a lowercase SHA-256 hex digest or null"
        )
    return CodeEntity(
        id=_string(data["id"]),
        name=_string(data["name"]),
        qualified_name=_string(data["qualified_name"]),
        kind=EntityKind(_string(data["kind"])),
        file_path=_string(data["file_path"]),
        start_line=start,
        end_line=end,
        parameters=tuple(_parameter(item) for item in _list(data["parameters"])),
        docstring=_optional_string(data["docstring"]),
        decorators=tuple(_string(item) for item in _list(data["decorators"])),
        return_annotation=_optional_string(data["return_annotation"]),
        body_fingerprint=fingerprint,
    )


def _decode(value: object) -> dict[str, CodeEntity]:
    data = _object(value, {"schema_version", "entities"})
    version = data["schema_version"]
    if type(version) is not int or version != SCHEMA_VERSION:
        raise SnapshotError(
            f"Unsupported snapshot schema version: {version!r}; expected 2. "
            "Regenerate the baseline from its original source revision with the current parser."
        )
    index: dict[str, CodeEntity] = {}
    try:
        for item in _list(data["entities"]):
            entity = _entity(item)
            if entity.id in index:
                raise SnapshotError(f"Duplicate entity ID: {entity.id}")
            index[entity.id] = entity
    except ValueError as error:
        raise SnapshotError(str(error)) from error
    return dict(sorted(index.items()))


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise SnapshotError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def save_snapshot(index: Mapping[str, CodeEntity], path: Path) -> None:
    """Save deterministic UTF-8 JSON, replacing the destination only after writing.

    The parent directory must exist. Invalid indexes raise SnapshotError; file
    access failures propagate as OSError. Existing snapshots survive failed writes.
    """
    for key, entity in index.items():
        if key != entity.id:
            raise SnapshotError(
                f"Index key {key!r} does not match entity ID {entity.id!r}"
            )
    document = {
        "schema_version": SCHEMA_VERSION,
        "entities": [asdict(index[key]) for key in sorted(index)],
    }
    # Validate before touching the destination, even for manually built indexes.
    _decode(json.loads(json.dumps(document)))
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    temporary: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load_snapshot(path: Path) -> dict[str, CodeEntity]:
    """Load a v2 snapshot, restoring enums and tuples; reject malformed data."""
    try:
        document = json.loads(
            path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object
        )
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise SnapshotError(f"Invalid snapshot {path}: {error}") from error
    return _decode(document)
