# AI-assisted documentation proposals

DocGuard now has a local workflow from code change to a reviewed documentation
edit. The deterministic parser and review engine decide which documents to inspect;
Groq or OpenAI proposes an edit; you inspect a diff and explicitly apply one document.
No AI call runs automatically in the pull-request workflow.

For Groq, `.env` configuration, live evaluation, and deliberate failure tests,
start with [the Groq evaluation guide](groq-evaluation.md).

## Run the offline demo first

From the DocGuard repository root in PowerShell, with the existing editable
installation in `.venv`:

```powershell
.\.venv\Scripts\python.exe examples/ai_demo.py
.\.venv\Scripts\python.exe -m docguard review .docguard-demo/baseline.json --root .docguard-demo --mapping .docguard-demo/docguard-map.json
```

The script refuses to overwrite an existing demo. Use `--output .docguard-demo-2`
for another experiment and substitute that directory in later commands. The
default `.docguard-demo` directory is ignored by Git.

The demo contains a snapshot of `total(price)` returning `price`, current source
returning `price * 1.2`, and a document that still describes the old behavior.
Review should report `modified: body` and return exit code `1`.

Inspect the actual API request without sending anything:

```powershell
.\.venv\Scripts\python.exe -m docguard suggest .docguard-demo/baseline.json --root .docguard-demo --mapping .docguard-demo/docguard-map.json --dry-run --output .docguard-demo/requests.json
Get-Content .docguard-demo/requests.json
```

This needs no API key. The file contains the exact request payloads: instructions,
model, document text, before/after metadata, review reasons, current source
snippets for mapped entities, and output schema. API credentials are never included.

The demo also creates `offline-proposal.json`, a **hand-written fixture**, clearly
labeled `offline-demo-not-an-ai-model`. It verifies preview and apply without
pretending to test model quality:

```powershell
.\.venv\Scripts\python.exe -m docguard apply-proposal .docguard-demo/offline-proposal.json --root .docguard-demo --document docs/prices.md --check
Get-Content .docguard-demo/docs/prices.md
```

The diff should change "returns the price unchanged" to "returns the price
multiplied by 1.2", retaining the support sentence. `--check` writes nothing.
If you want to test application of the fixture, omit `--check`:

```powershell
.\.venv\Scripts\python.exe -m docguard apply-proposal .docguard-demo/offline-proposal.json --root .docguard-demo --document docs/prices.md
Get-Content .docguard-demo/docs/prices.md
```

For the live experiment below, use a fresh demo directory if you already applied
the fixture. Otherwise the model may correctly conclude that the document needs
no change.

## Generate a real OpenAI proposal

For this OpenAI example, use an OpenAI API key with model access and billing.
If your `.env` selects Groq, use the Groq guide above instead.
No additional Python dependency is required; the client uses the Responses HTTPS
API through the standard library. Do not put the key in source files or Git.
This PowerShell command prompts without showing the key or storing it in the
command itself:

```powershell
$env:OPENAI_API_KEY = [System.Net.NetworkCredential]::new("", (Read-Host "OpenAI API key" -AsSecureString)).Password
.\.venv\Scripts\python.exe -m docguard suggest .docguard-demo/baseline.json --root .docguard-demo --mapping .docguard-demo/docguard-map.json --provider openai --model gpt-4.1-mini --output .docguard-demo/ai-proposals.json
Get-Content .docguard-demo/ai-proposals.json
```

This explicit OpenAI command sends the prepared context to OpenAI and incurs API
usage charges. Its default model is `gpt-4.1-mini`; Groq defaults to
`openai/gpt-oss-120b`. Configuration can override these defaults. Availability depends on your account. Nothing is sent in dry-run
mode, and zero flagged documents produce zero API calls even without a key.

The model returns one of:

| Action | Meaning | Can apply? |
| --- | --- | --- |
| `revise` | A complete proposed replacement, summary, and warnings | Yes, after preview |
| `unchanged` | Existing documentation already fits | No |
| `needs_review` | Evidence is insufficient for a supported edit | No |

Read the summary and warnings. If the action is `revise`, preview and apply:

```powershell
.\.venv\Scripts\python.exe -m docguard apply-proposal .docguard-demo/ai-proposals.json --root .docguard-demo --document docs/prices.md --check
# Inspect the diff before running the next command.
.\.venv\Scripts\python.exe -m docguard apply-proposal .docguard-demo/ai-proposals.json --root .docguard-demo --document docs/prices.md
```

Applying affects exactly the selected document. Commit it normally after review.
The baseline is not refreshed automatically. When finished using the API:

```powershell
Remove-Item Env:OPENAI_API_KEY
```

## Context, limits, and failure behavior

- `suggest` works with local snapshot-based review. Git review remains available
  separately; there is no automatic paid AI step on fork PRs or model-driven PR
  creation. Newly added/unmapped entities and removed-link findings require human
  mapping decisions; they do not invent documentation targets.
- AI editing supports UTF-8 `.md`, `.rst`, and `.txt` files. Other document formats
  can still participate in deterministic review. Code parsing is Python-only.
- Only flagged documents are sent. Each request contains that document and all of
  its explicitly mapped entities, with current snippets and old/new metadata.
  Old body source, imported modules, callers, and external dependencies are not
  supplied. Models must abstain where those gaps prevent a justified edit.
- At most 3 documents per run by default. Select individual documents with
  repeated `--document docs/example.md` options, or set `--max-documents` (1–20).
  All contexts are validated before the first request. Limits are 40,000 JSON
  context characters per document, 1 MB per source/document file read, 12,000
  output tokens per request, and 60,000 characters per proposed replacement.
  Oversized inputs fail rather than silently truncate. These are bounds, not
  an exact cost estimate.
- One request is made per selected document. There are no automatic retries.
  Missing credentials, API errors, timeouts, refusal, incomplete generation, or
  malformed output fail explicitly with exit `2`. If a later request fails,
  earlier calls may still have incurred charges, but no partial proposal bundle
  is saved and no document is changed.
- `suggest` returns `0` when it saves a valid artifact, including `needs_review`
  or an empty proposal list. Inspect actions instead of interpreting success as
  "the model fixed everything". Existing output files are never overwritten.
- Proposals retain original document bytes as UTF-8 text and their SHA-256 hash,
  plus a hash of all discovered Python source files. Preview/apply reject changed
  documents or source, including global-variable changes, added files, and comments.
  Regenerate stale proposals rather than bypassing the check. A second application
  of the same edit normally fails as stale. Baseline/mapping changes themselves
  are not hashed; regenerate if their intended meaning changes.
- Applying validates paths, rejects symlink documents/parents and unsupported file
  types, writes a temporary sibling, then atomically replaces one file. Failed
  replacement preserves the original. This is a local workflow, not a transaction
  lock against concurrent repository writers. Proposal artifacts are not signed;
  inspect them as you would any patch from another contributor.
- OpenAI requests set `store: false`; this is not a blanket guarantee about all provider
  retention policies. Document/source text is untrusted input in the prompt. The
  model gets no tools, execution, or filesystem access. Structured output and
  validation constrain format, not factual accuracy: human diff review remains
  necessary. No automatic claim that documentation is now correct is made.
- Request/proposal artifacts contain document and source context. Keep them local
  or share deliberately. The project's existing `*.json` ignore rule excludes
  generated artifacts; the committed mapping has a specific exception.

The integration follows OpenAI's [Structured Outputs documentation](https://developers.openai.com/api/docs/guides/structured-outputs?api-mode=responses).
The default model's features are documented on the [GPT-4.1 mini model page](https://developers.openai.com/api/docs/models/gpt-4.1-mini).

## Test and verify

Offline tests never need a key or network:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/code/test_ai_proposals.py tests/code/test_ai_provider.py tests/code/test_ai_demo.py -vv
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy src
```

They cover API payload shape, refusals/timeouts/rate limits, malicious or malformed
responses, partial failures, context limits, no-change runs, source/document edits
during generation, stale application, path restrictions, failed writes, CRLF and
Unicode, and the actual CLI demo workflow. Stubbed model responses verify software
behavior, not the quality of real generated documentation.

There is a separate, explicit **paid** live smoke test:

```powershell
# Set OPENAI_API_KEY first, as above.
$env:DOCGUARD_RUN_LIVE_AI = "1"
.\.venv\Scripts\python.exe -m pytest tests/code/test_ai_live.py -vv
Remove-Item Env:DOCGUARD_RUN_LIVE_AI
```

It sends one synthetic example, expects a supported multiplier edit, checks that
unrelated prose survives, and verifies that generation did not modify the document.
Optionally set `DOCGUARD_MODEL` to test another model. This is a smoke test, not a
comprehensive quality evaluation. The live test is skipped by default and is not
enabled in CI.

## How close is this to a working DocGuard?

This is a local AI-assisted MVP: detect → map → propose → preview → apply.
Deterministic PR review is implemented separately. Before calling it production
ready, validate a live model call with your account, verify the hosted workflow,
and evaluate proposal quality on representative documentation changes. Automatic
AI PRs, semantic correctness, broad language support, and automatic mapping remain
future work. They are not prerequisites for using the current local workflow.
