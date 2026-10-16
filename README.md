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

## Documentation review

DocGuard can track explicit links from documentation files to code entities. It
suggests documents to review when linked metadata changes or an entity is removed.
It does not read the document text, prove that documentation is stale, or edit it.

Create documentation inside your target repository (for example,
`../demo/docs/client.md`) and a mapping file named `docguard-map.json`:

```json
{
  "schema_version": 1,
  "documents": {
    "docs/client.md": ["client.py:connect", "client.py:close"]
  }
}
```

Use exact IDs from your baseline JSON. Document paths are relative to `--root`,
not the mapping file's directory. Use normalized forward-slash paths; absolute
paths, backslashes, `.`/`..` components, missing files, and symlinks resolving
outside the repository are rejected. The mapping file itself may be outside the
repository. Each document needs a non-empty array of unique IDs; an empty
`documents` object is allowed. Several documents may reference the same entity.

Create the baseline before changing source, then review after making changes:

```powershell
.\.venv\Scripts\python.exe -m docguard snapshot ../demo --output baseline.json
# Edit a mapped function in ../demo/client.py.
.\.venv\Scripts\python.exe -m docguard review baseline.json --root ../demo --mapping docguard-map.json
$LASTEXITCODE
```

Example output:

```text
REVIEW docs/client.md
  client.py:connect modified: parameters
UNMAPPED ADDED client.py:new_function
1 documents to review, 1 unmapped additions
```

Review rules:

| Situation | Result |
| --- | --- |
| Linked entity metadata changed | Review document, listing changed fields |
| Linked entity removed | Review document, with removal reason |
| Only source line bounds changed | No documentation finding |
| Newly added entity has no document link | Separate `UNMAPPED ADDED` finding |
| Newly added entity already has a link | No review finding solely for its addition |
| Mapped ID absent from both snapshots | Configuration error |

An ID present only in the baseline is a legitimate removal, not a misspelled
reference. Modified or removed entities without mappings do not trigger document
review. Unchanged unmapped entities are not reported: this is change impact,
not a complete documentation coverage audit. A document gets one review entry
with all relevant reasons, sorted by ID; documents are sorted by path.

For `review`, exit `0` means no review findings, `1` means documents need review
or new entities are unmapped, and `2` means invalid input or execution failure.
Unlike `compare`, line-only movement does not cause exit `1`. Errors go to stderr;
no partial report is printed when validation fails. Source, documentation,
mapping, and baseline files are never modified by this command.

The library API is also available:

```python
from docguard.docs.mapping import load_mapping
from docguard.docs.review import review_documents

mappings = load_mapping(Path("docguard-map.json"), root)
report = review_documents(mappings, before, after)
# report.documents: DocumentReview(document, reasons)
# report.unmapped_added: tuple of entity IDs
```

Use `load_mapping` to validate document paths and structure, then
`review_documents` to validate entity references and calculate impact. The latter
performs no filesystem reads. Mapping validation raises `MappingError`, a
`ValueError` subclass; filesystem errors propagate normally. The current mapping
describes both snapshots, so keep references to removed entities until their
documentation has been reviewed. Once the baseline is refreshed, remove obsolete
links or they will correctly become unknown references.

Limitations: manual links require maintenance; renames appear as removal/addition;
duplicate occurrence suffixes can shift; body-only changes are not detected.
Documentation changes themselves are not compared, so a document already updated
by a human may still be suggested for review. No Markdown parsing, embeddings,
LLM, database, or new runtime dependency is used.

## Git revisions and pull-request automation

Git review creates its baseline automatically from the merge base (the common
ancestor of the target branch and proposed commit). No saved baseline is needed:

```powershell
.\.venv\Scripts\python.exe -m docguard review-git --root ../demo --base main --head HEAD --mapping docguard-map.json
```

Run this while `HEAD` names a committed feature branch, or pass an explicit commit
SHA. `main` is an example target branch name; substitute the branch in your repo.
Both revisions and their common history must exist locally.
`--root` must be the actual Git worktree root (linked worktrees are supported),
not an ordinary subdirectory that Git associates with a parent repository.
Fetch history if necessary; DocGuard itself never performs a network fetch. Unrelated histories
or ambiguous merge bases fail. Submodules are not supported and fail explicitly.

Only committed regular files are analyzed. Untracked files, staged changes, and
unstaged changes are ignored. Symlinks are skipped (a mapped symlink document will
therefore be missing and fail validation). The command reads Git tree/blob data
into temporary directories, without changing branches, modifying the index, or
running target code, Git hooks, or checkout filters. `.gitattributes` export-ignore
rules do not hide files. Regular files are exported in memory before writing, so
very large repositories/blobs can require substantial memory. Non-portable paths
and filesystem collisions fail rather than silently overwrite extracted files.

The mapping is read from the **head commit**; `--mapping` is a path inside that
commit, not a file from your working directory. Removing a link in the PR can
suppress a suggestion. This initial version does not audit mapping changes.

### Machine-readable output

Both review commands accept `--format json`:

```powershell
.\.venv\Scripts\python.exe -m docguard review baseline.json --root ../demo --mapping docguard-map.json --format json
.\.venv\Scripts\python.exe -m docguard review-git --root ../demo --base main --mapping docguard-map.json --format json
```

The report has its own `schema_version: 1`, `documents`, `unmapped_added`, and
`counts` fields. Reasons retain `entity_id`, `change`, and `changed_fields`.
Git reports additionally contain `git.base`, `git.head`, and `git.merge_base`
with resolved commit SHAs. JSON goes to stdout without mixed-in progress messages;
errors go to stderr and return `2`, with no JSON report on failure.

For automation, Git review supports:

```powershell
.\.venv\Scripts\python.exe -m docguard review-git --root ../demo --base main --mapping docguard-map.json --format json --advisory --summary review-summary.md
```

`--advisory` returns `0` even when findings exist; errors still return `2`.
Without it, findings return `1`. `--summary` writes an escaped Markdown/HTML
summary suitable for a CI job summary. These output options do not change the
actual findings. Findings are suggestions, not proof of stale documentation.

### GitHub Actions workflow

`.github/workflows/docguard-review.yml` runs on pull requests with read-only
repository permissions. It checks out the target commit as the trusted tool,
checks out full proposed history separately, then runs the tool from outside the
target checkout with Python's safe-path flag. It does not install or execute PR
source, post comments, or require secrets. It uses Python 3.11 and the standard
library. The workflow produces a job summary and a `docguard-review` artifact
containing JSON and Markdown. Errors fail the job; review findings are advisory.

**Bootstrap:** the target branch must already contain this Git-review command.
The PR introducing it cannot successfully run it from an older target branch.
Run the local tests for that initial merge; subsequent PRs use the merged tool.
Actions must be enabled, and GitHub may require approval for fork workflows.
The workflow is for GitHub.com; hosted execution must be verified in an actual PR.

`docguard-map.json` links the README to selected public DocGuard APIs as an initial
mapping. It is not a complete coverage map. Python `.py` files are the only code
language analyzed; documentation can be any existing regular file type, but its
contents are not interpreted. Body-only changes remain outside the comparison.

### Test Git automation without creating a dummy repository yourself

```powershell
.\.venv\Scripts\python.exe -m pytest tests/code/test_git_review.py -vv
.\.venv\Scripts\python.exe -m pytest tests/code/test_reporting.py tests/code/test_review_cli.py -vv
```

The Git tests create temporary repositories, configure a local test author, make
real commits/branches, and clean up afterward. They do not commit into this repo
or contact a Git hosting service. Git must be installed (otherwise the Git tests
are skipped). Cases include diverging branches, changed signatures, removals,
unmapped additions, line-only changes, invalid mappings/source/revisions,
unrelated histories, shallow clones, submodules, dirty worktrees, and advisory
exit codes. The summary tests check that document names cannot inject markup.

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
- This milestone does not implement document-content parsing, function-body change
  detection, Git integration, rename tracking, or AI-driven updates.
