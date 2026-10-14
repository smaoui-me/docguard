# DocGuard

A self-healing technical documentation tool.

Requires Python 3.11 or newer.

## Current milestone: repository indexes, snapshots, and metadata comparison

DocGuard extracts immutable entities for classes, functions, methods, and their
async variants. Metadata includes qualified names, source lines, annotations,
defaults, all five parameter kinds, docstrings, and decorators. Nested definitions
are included, and `self` and `cls` are preserved as written in the source.

The repository scanner discovers Python files independently of parsing. It sorts
paths, includes test files, and skips common environment/cache directories and
symlinks. It does not interpret `.gitignore`.

Repository indexes combine discovery and parsing into an ID-to-entity dictionary.
Versioned JSON snapshots preserve those entities between runs. Comparisons report
added, removed, modified, and moved entities, with metadata and line changes kept
separate. All of these features use the standard library.

## Setup (PowerShell)

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

Editable installation makes `docguard` importable without setting `PYTHONPATH`.
Development dependencies are optional; the parser itself uses only the standard library.

## Command-line usage

From PowerShell in the DocGuard directory, create a baseline of a sibling demo
repository, edit its source, then compare:

```powershell
.\.venv\Scripts\python.exe -m docguard snapshot ../demo --output baseline.json
# Edit files in ../demo before running the comparison.
.\.venv\Scripts\python.exe -m docguard compare baseline.json --root ../demo
$LASTEXITCODE
```

Use `.` instead of `../demo` to index DocGuard itself. Paths are relative to the
terminal's working directory; quote paths containing spaces. No interactive
Python session is needed.

`snapshot` saves the baseline, replacing an existing output file. Its parent
directory must exist, and `.py` destinations are rejected to prevent overwriting
source. `compare` prints entity IDs grouped as `ADDED`, `REMOVED`, `MODIFIED`, and
`MOVED`; modifications include field names and movement includes old/new line
bounds. Comparison never updates the baseline. An entity can be both modified
and moved, so group counts are not a count of unique changed entities.

| Exit code | Meaning |
| --- | --- |
| `0` | Snapshot saved, or comparison found no changes |
| `1` | Comparison found changes, including line-only movement |
| `2` | Invalid arguments, paths, source, or snapshot; or a filesystem error |

Reports go to stdout; error messages go to stderr without a traceback for expected
failures. Use the same logical repository root as when creating the baseline.
Body-only changes remain outside metadata comparison's scope.

```powershell
.\.venv\Scripts\python.exe -m docguard --help
.\.venv\Scripts\python.exe -m docguard snapshot --help
.\.venv\Scripts\python.exe -m docguard compare --help
```

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

## Index, save, load, and compare

Create a baseline before editing your Python source:

```python
from pathlib import Path

from docguard.code.index import index_repository
from docguard.code.snapshots import save_snapshot

baseline = index_repository(Path("."))
save_snapshot(baseline, Path("baseline.json"))
```

After editing source, compare against that saved baseline:

```python
from pathlib import Path

from docguard.code.comparison import compare_snapshots
from docguard.code.index import index_repository
from docguard.code.snapshots import load_snapshot

before = load_snapshot(Path("baseline.json"))
after = index_repository(Path("."))
changes = compare_snapshots(before, after)

for entity in changes.added:
    print("added", entity.id)
for entity in changes.removed:
    print("removed", entity.id)
for change in changes.modified:
    print("modified", change.after.id, change.changed_fields)
for change in changes.moved:
    print("line bounds changed", change.after.id, change.changed_fields)
```

Use the same logical repository root for each index. A moved checkout is fine;
changing the root from the repository directory to its `src` directory changes IDs.
The index includes test files, preserves repeated definitions using occurrence
suffixes, and propagates parsing/read errors instead of returning a partial index.
An unexpected duplicate ID raises `ValueError` instead of overwriting an entity.

Snapshots have this envelope (an empty index is shown):

```json
{
  "schema_version": 1,
  "entities": []
}
```

Each entity contains every `CodeEntity` field, including all parameter fields.
Enums are stored as strings and tuples as JSON arrays; loading restores their
domain types. Entities are saved in sorted ID order with no timestamps or
checkout-specific root field, making repeated saves deterministic. Loading also
returns an index ordered by ID; callers should treat indexes as mappings rather
than rely on the original parser traversal order surviving serialization.

`SnapshotError` (a `ValueError` subclass) reports unsupported schema versions,
malformed JSON/schema, invalid enum values, invalid line bounds, duplicate JSON
keys, and duplicate entity IDs. Filesystem errors propagate normally. There are
no automatic schema migrations yet. Saving requires an existing parent directory;
it validates first, writes a temporary sibling, then replaces the destination.
Failed writes/replacements leave the previous snapshot intact. Loading and
comparison never update the baseline automatically.

Comparison results are immutable dataclasses containing tuples sorted by entity ID:

| Result | Contents | Meaning |
| --- | --- | --- |
| `added` | Current `CodeEntity` objects | IDs only in the new index |
| `removed` | Previous `CodeEntity` objects | IDs only in the old index |
| `modified` | `EntityChange` objects | Signature or metadata differs |
| `moved` | `EntityChange` objects | Start or end line differs |

Each `EntityChange` contains `before`, `after`, and `changed_fields`. Metadata
comparison includes name, qualified name, entity kind, file path, parameters,
return annotation, decorators, and docstring. Parameter changes include names,
annotations, defaults, kinds, and order; they are reported under `parameters`.
Line fields are compared independently. An entity can be both modified and moved;
a comment inserted above it produces movement alone. Changes to its end line
also count as movement, even if its start line stays fixed.

Matching is strictly by ID. Renames/file moves appear as removal plus addition.
Duplicate occurrence IDs retain the ordering limitations described below. Bodies
are not stored, so a body-only change with unchanged metadata and line bounds is
not reported. A body-only edit that changes the end line reports movement only.
This is metadata comparison, not behavioral or Git diff analysis.

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
- This milestone does not implement documentation parsing, function-body change
  detection, Git integration, rename tracking, or AI-driven updates.
