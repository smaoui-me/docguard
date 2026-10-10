# DocGuard

A self-healing technical documentation tool.

Requires Python 3.11 or newer.

## Current milestone: Python parser and file discovery

DocGuard extracts immutable entities for classes, functions, methods, and their
async variants. Metadata includes qualified names, source lines, annotations,
defaults, all five parameter kinds, docstrings, and decorators. Nested definitions
are included, and `self` and `cls` are preserved as written in the source.

The repository scanner discovers Python files independently of parsing. It sorts
paths, includes test files, and skips common environment/cache directories and
symlinks. It does not interpret `.gitignore`.

## Setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Editable installation makes `docguard` importable without setting `PYTHONPATH`.
Development dependencies are optional; the parser itself uses only the standard library.

## Parse a repository

Run Python from the repository root after installation:

```python
from pathlib import Path

from docguard.code.python_parser import parse_python_file
from docguard.code.scanner import discover_python_files

root = Path(".").resolve()
for path in discover_python_files(root / "src"):
    for entity in parse_python_file(path, repository_root=root):
        print(entity.kind.value, entity.qualified_name, entity.start_line)
```

## Checks

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check src tests
.\.venv\Scripts\python.exe -m mypy src
```

The tests also support the standard-library runner:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests/code -v
```

## Boundaries and limitations

- Source is parsed, never executed. Decorators and defaults are stored as syntax
  strings produced by `ast.unparse()`, not evaluated values.
- Invalid syntax raises `SyntaxError`; missing files and filesystem errors also
  propagate. Valid files without definitions return an empty list.
- Entity IDs are `<normalized file path>:<qualified name>`. Pass `repository_root`
  to use portable repository-relative paths (for example,
  `src/client.py:Client.connect`); otherwise paths are resolved absolute paths.
  Both forms use forward slashes. Relative input paths are interpreted from the
  working directory, not from `repository_root`. Files resolving outside the
  supplied root are rejected. IDs survive comment/line shifts, but do not track
  renames.
- Every definition is retained. Repeated qualified names within a file receive
  occurrence suffixes: `module.py:connect`, `module.py:connect#2`,
  `module.py:connect#3`. Counts follow traversal order, span entity kinds, and
  reset for each parse. Names and qualified names remain unchanged. Nested
  definitions are counted by their own full qualified name; parent suffixes
  are not inherited. Inserting, deleting, or reordering duplicate definitions
  can change which definition an occurrence ID identifies.
- This milestone does not implement documentation parsing, change detection,
  rename tracking, or AI-driven updates.
