"""Bounded local reads and proposal-file validation."""

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import cast

MAX_FILE_BYTES = 1_000_000
DOCUMENT_SUFFIXES = {".md", ".rst", ".txt"}


class ProposalError(ValueError):
    """AI context, response, or proposal is invalid or stale."""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def relative_path(name: str) -> Path:
    path = PurePosixPath(name)
    if (
        not name
        or name == "."
        or "\\" in name
        or ":" in name
        or path.is_absolute()
        or PureWindowsPath(name).drive
        or ".." in path.parts
        or path.as_posix() != name
        or any(part.lower() == ".git" for part in path.parts)
    ):
        raise ProposalError(f"Expected a normalized repository-relative path: {name!r}")
    return Path(*path.parts)


def document_path(root: Path, name: str) -> Path:
    relative = relative_path(name)
    if relative.suffix.lower() not in DOCUMENT_SUFFIXES:
        raise ProposalError("AI proposals support only .md, .rst, and .txt documents")
    root = root.resolve(strict=True)
    path = root
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ProposalError(
                f"Symlink documents or parent directories are not supported: {name}"
            )
    if not path.resolve(strict=True).is_relative_to(root) or not path.is_file():
        raise ProposalError(
            f"Document must be an existing file inside the repository: {name}"
        )
    return path


def read_bytes(path: Path, limit: int = MAX_FILE_BYTES) -> bytes:
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ProposalError(f"File exceeds {limit} bytes: {path.name}")
    return data


def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    data: dict[str, object] = {}
    for key, value in pairs:
        if key in data:
            raise ProposalError(f"Duplicate JSON key: {key}")
        data[key] = value
    return data


def parse_json(text: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=unique_object)
    except json.JSONDecodeError as error:
        raise ProposalError("Invalid JSON in proposal or model response") from error


def object_fields(value: object, keys: set[str]) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ProposalError(f"Expected exactly these fields: {sorted(keys)}")
    return cast(dict[str, object], value)


def string(value: object) -> str:
    if not isinstance(value, str) or "\x00" in value:
        raise ProposalError("Expected a string without NUL characters")
    return value


def array(value: object) -> list[object]:
    if not isinstance(value, list):
        raise ProposalError("Expected a JSON array")
    return cast(list[object], value)


def write_new_json(path: Path, value: object) -> None:
    """Never overwrite an existing source, baseline, or proposal file."""
    if path.suffix.lower() != ".json":
        raise ProposalError("Proposal/context output must have a .json extension")
    encoded = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with path.open("xb") as stream:
        try:
            stream.write(encoded)
        except BaseException:
            stream.close()
            path.unlink(missing_ok=True)
            raise
