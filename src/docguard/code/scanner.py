"""Discover Python files without mixing filesystem traversal with AST parsing."""

import os
from pathlib import Path

EXCLUDED_DIRECTORIES = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)


def discover_python_files(root: Path) -> list[Path]:
    """Return sorted Python paths, including tests, without following symlinks.

    Known environment/cache directories are pruned. This is not a .gitignore
    interpreter. Missing roots and filesystem access errors propagate.
    """
    if not root.exists():
        raise FileNotFoundError(root)
    if not root.is_dir():
        raise NotADirectoryError(root)

    def raise_walk_error(error: OSError) -> None:
        raise error

    paths: list[Path] = []
    for directory, subdirectories, filenames in os.walk(root, onerror=raise_walk_error):
        subdirectories[:] = [
            name
            for name in subdirectories
            if name not in EXCLUDED_DIRECTORIES
            and not (Path(directory) / name).is_symlink()
        ]
        for name in filenames:
            path = Path(directory) / name
            if path.suffix == ".py" and not path.is_symlink():
                paths.append(path)
    return sorted(paths, key=lambda path: path.as_posix())
