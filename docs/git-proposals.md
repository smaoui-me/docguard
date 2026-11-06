# Git proposals with evidence

This milestone connects committed Git review to AI proposals. It also adds 30
authored regression fixtures. These are **synthetic**, with author-checked labels
pending independent human review; they are not 30 imported or independently
reviewed public PRs. Do not advertise their offline pass rate as model accuracy.

## Try the real workflow

From the DocGuard project root, configure `.env` as described in
[the Groq guide](groq-evaluation.md), then create a disposable repository:

```powershell
.\.venv\Scripts\python.exe examples/git_ai_demo.py
.\.venv\Scripts\python.exe -m docguard suggest-git --root .docguard-demo-git --base HEAD~1 --mapping docguard-map.json --dry-run --output git-requests.json
Get-Content git-requests.json
```

The demo creates two commits: `connect(host, port=443)` gains a `timeout=30`
parameter. Documentation still describes the original signature. The request
contains before/after source, a unified diff, previous/current documentation,
entity metadata and evidence IDs. There are no API calls yet. If the demo or output
exists, choose another name rather than overwriting it.

Generate a real proposal (one provider request for this example):

```powershell
.\.venv\Scripts\python.exe -m docguard suggest-git --root .docguard-demo-git --base HEAD~1 --mapping docguard-map.json --output git-proposals.json
Get-Content git-proposals.json
.\.venv\Scripts\python.exe -m docguard apply-git-proposal git-proposals.json --root .docguard-demo-git --document README.md --check
```

Review the proposed text and `evidence_ids`. If the decision is `revise`, run the
last command without `--check` to apply. Other actions cannot be applied. A second
application should fail as stale. Your `.env` is read from the current terminal
directory, not from the target repository or either exported commit.

For your own repository replace the demo root, use locally available target/head
revisions, and commit a `docguard-map.json` mapping in the head revision. `--head`
defaults to HEAD. This feature does not fetch history, commit changes, or publish PRs.

## Evidence and application contract

1. Resolve base/head to commits and find their unique merge base.
2. Export regular tracked blobs into temporary directories. Never check out another
   branch or execute/import code from the target project.
3. Run the existing deterministic parser/mapping review. Untracked and uncommitted
   changes are ignored during generation. Head documentation may already be correct.
4. For affected documents, add mapped entity snippets from both revisions, their
   paths, line ranges, SHA-256 text hashes and stable `before:`/`after:` evidence IDs.
   Changes to unmapped entities and removed mapping links remain visible in `review`.
5. Ask the model for a decision and citations. Reject fabricated/duplicate citations,
   and reject revisions or unchanged decisions with no citations. Every context is
   checked against the 40,000-character bound before the first provider call.
6. Save a separate versioned `docguard.ai.git-proposals` artifact. No document changes
   during generation; no partial proposal bundle if any response fails.
7. Preview/apply requires the matching checkout HEAD. Reconstruct evidence from Git,
   validate original document/source/mapping state, then reuse atomic application.
   CRLF versus LF checkout differences are accepted, while target newline convention
   is preserved. Other local source/document changes are refused.

References prove that cited snippets exist, **not that the generated claim follows
from them**. This initial implementation cites a document-level decision, not each
sentence or individual edit. Artifacts are unsigned and human review is still needed.
Imported dependencies, globals and callers are not automatically expanded; complex
claims can still require review. Renames are removal/addition pairs, not inferred
identity links. Line-only changes and module-level-only changes are outside the
existing entity-change detector. Automatic mapping and multilingual parsing are
not introduced here.

Git export retains the existing review implementation's behavior: it exports the
whole tracked tree, skips symlinks and rejects submodules. Per-context limits do
not make full-tree export memory bounded. Application is not a repository-wide lock.

## The 30-case evaluation corpus

Open `evaluations/git_cases.toml`. Each case contains:

- Category, difficulty, provenance, review status and rationale.
- Before/after Python source and before/current documentation.
- Explicit entity mappings and expected request/decision behavior.
- An offline replacement fixture, required/forbidden patterns and prose to preserve.
- A development or reserved split (20 and 10 cases). Fixture API families stay in
  the same split; reserved means reserved for future live assessment, not a blind
  independently curated holdout.

Cases cover parameter addition/removal, keyword-only and async parameters, defaults,
return types/shapes, behavior changes, renames/deletion, already-correct documentation,
refactors, line/comment changes, missing dependencies and misleading source content.
They include multiple mapped functions, methods, conditions and async code, but
remain smaller and more controlled than typical production PRs.

Run all cases offline (creates and removes temporary Git repositories):

```powershell
.\.venv\Scripts\python.exe -m docguard evaluate-git --split all --output git-evaluation-offline.json
```

Expected: 30/30. This proves the fixtures pass through deterministic detection,
Git context preparation, citation validation and preview/application. Generation
uses gold fixtures; it does not measure model quality. Fixtures are never executed.

Start live evaluation with a small development subset:

```powershell
.\.venv\Scripts\python.exe -m docguard evaluate-git --live --case timeout_parameter --case retry_default --case missing_transform --output git-evaluation-live.json
```

Default maximum is three selected live cases. Use `--max-requests` explicitly for
larger runs (up to 100); the selected case count is conservatively used as a bound
even when some cases need no model call. Reports include actual API request counts,
dataset hash, prompt versions, per-case checks, outputs and errors. HTTP 401/403/429
stops the run and records remaining cases as `not_run`; there are no automatic
retries. Exit 0 requires all selected cases pass, 1 means failure/incomplete, and
2 means invalid setup. No paid evaluation is added to CI.

Use `--split reserved` only after freezing prompts and development choices. Once
you inspect its outputs to tune the system, it is no longer a held-out assessment.
The expected labels, fixture replacement and grading patterns are never sent to
the model. Grading uses limited text assertions; manually assess semantic accuracy
and unrelated changes before claiming a quality improvement.

## Where to find real PRs

A first pinned HTTPX pilot and the `evaluate-pr` command are now available in
[upstream PR evaluation](upstream-evaluation.md). Its authentic and controlled
cases remain separate from this synthetic corpus.

Start with merged PRs in well-documented Python libraries. HTTPX's
[release notes](https://github.com/encode/httpx/releases) connect user-visible API
changes to issues and PRs. Two concrete candidates to inspect are:

- [HTTPX #3378: Request parameter cleanup](https://github.com/encode/httpx/pull/3378)
  for signature/annotation changes and whether documentation needs an edit.
- [HTTPX #3364: URL instantiation](https://github.com/encode/httpx/pull/3364)
  for behavior involving URL/query parameters.

These are candidates, not imported or validated benchmark cases. Inspect Files
changed, related tests, discussion and docs before assigning a label. Changelog
numbers may link to issues rather than PRs; verify the page type.

In GitHub's PR search, try:

```text
repo:encode/httpx is:pr is:merged "default"
repo:encode/httpx is:pr is:merged "parameter"
repo:pallets/flask is:pr is:merged "documentation"
repo:pallets/click is:pr is:merged "deprecated"
```

Prefer a mix of small and moderately complex PRs with understandable public behavior.
Complexity should come from multiple related symbols, boundaries and missing context,
not merely hundreds of changed lines. Include real no-edit cases to measure false
positives. Deliberate prompt injections usually need authored adversarial variants,
clearly separated from the original upstream change.

## How to curate an upstream case correctly

1. Record repository URL, PR URL, exact base/head commit SHAs, relevant code and doc
   paths, project license and any attribution obligations for redistributed excerpts.
2. Read the code diff and tests. Write the expected user-facing behavior in your own
   words; have another person review it. A merged PR is not automatically a gold label.
3. Build the explicit mapping for relevant entities. Keep upstream reference metadata
   in a sidecar manifest; never send the PR's desired final prose as an answer hint.
4. Choose the task deliberately. With head docs already fixed, expect `unchanged`.
   To assess repair, create a clearly labeled controlled variant combining head code
   with base documentation; do not describe that variant as the original PR tree.
5. Keep a source PR and all its variants in one split. Keep frozen held-out cases
   separate from prompt development. Record whether examples were publicly available
   to the model; public history does not eliminate training-data contamination.
6. Add representative long-context or dependency-heavy cases after the small cases
   work. Label insufficient evidence explicitly rather than forcing an edit.

There is no automatic upstream-PR importer in this milestone. This manual process
is intentional: finding a PR is easy; producing a defensible label requires review.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/code/test_git_proposals.py tests/code/test_git_dataset.py -vv
.\.venv\Scripts\python.exe -m pytest
```

The first command covers all 30 fixtures, merge-base selection, dirty working trees,
citation forgery, original-text tampering, stale files, no-op/no-network runs,
Windows line endings, split/budget validation, and rate-limit stopping. Existing
Git tests continue to cover invalid revisions, ancestry, submodules and parse failures.


## Optional dependency evidence

`suggest-git --evidence-policy direct` expands mapped function/method snippets with
bounded local dependencies. `mapped` remains the default and preserves the
original evaluation scope. See [evidence selection and human review](evidence-and-review.md).
Git request/proposal artifacts now use schema version 2 with an evidence policy
and selector version. Apply still accepts legacy schema-1 mapped artifacts. New
artifacts reconstruct evidence using their recorded policy; a changed selector
version requires regenerating the proposal.
