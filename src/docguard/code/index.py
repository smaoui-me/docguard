"""Compose discovery and parsing into a repository-relative entity index."""

from pathlib import Path

from docguard.code.models import CodeEntity
from docguard.code.python_parser import parse_python_file
from docguard.code.scanner import discover_python_files


def index_repository(root: Path) -> dict[str, CodeEntity]:
    """Index all discovered files; propagate errors rather than return partial data."""
    root = root.resolve(strict=True)
    index: dict[str, CodeEntity] = {}
    for path in discover_python_files(root):
        for entity in parse_python_file(path, repository_root=root):
            if entity.id in index:
                raise ValueError(f"Duplicate entity ID: {entity.id}")
            index[entity.id] = entity
    return index
