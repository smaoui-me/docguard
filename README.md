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

for path in discover_python_files(Path("src")):
    for entity in parse_python_file(path):
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
- Entity IDs are `<supplied file path>:<qualified name>`. Identical paths and
  source produce identical results; absolute and relative paths are not yet
  canonicalized. Repeated definitions of the same qualified name share an ID.
- This milestone does not implement documentation parsing, change detection,
  rename tracking, or AI-driven updates.
