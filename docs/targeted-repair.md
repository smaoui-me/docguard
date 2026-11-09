# Targeted repairs and controlled publication

DocGuard can now constrain a Git proposal to one Markdown section. It still needs
an explicit code/document mapping; it does not discover every documentation claim.

## Map a section

Commit this mapping with the source and document:

```json
{
  "schema_version": 2,
  "documents": {
    "docs/prices.md": {
      "entity_ids": ["client.py:total"],
      "section": ["# Billing", "## Prices"],
      "claims": []
    }
  }
}
```

The heading path includes all enclosing headings and matches their text exactly.
Repeated identical paths are ambiguous and rejected. The section includes its
heading and children, ending before the next peer or ancestor heading. Claim
requirements can be added as described in [claim-requirements.md](claim-requirements.md);
their quotes must occur inside the selected section.

The model receives only the selected document section plus source evidence. It
returns a replacement section, including the unchanged heading. DocGuard splices
that replacement between the original byte sequences. The artifact contains the
whole resulting document so reviewers can inspect the complete diff. During apply,
DocGuard reconstructs the scope from the committed mapping and rejects any change
outside it, even if somebody tampered with the artifact.

Outside-section bytes, including UTF-8, trailing spaces and mixed CRLF/LF endings,
are preserved exactly. A section edit requires the working document to match the
committed document byte-for-byte; automatic checkout newline conversion can therefore
cause an intentional rejection. Use a consistent `.gitattributes` policy. Regenerate
after source, mapping or document changes. Scope does not prove semantic accuracy
or preserve all formatting **inside** the section.

This first selector supports ATX headings (`#`, `##`, etc.) and fenced code blocks.
It conservatively rejects HTML, Setext headings, horizontal underline rules,
empty/indented headings, indented code and unclosed fences. Whole-document mappings remain available for
unsupported documents. Snapshot-based `suggest` refuses section mappings; use
`suggest-git`, which has the immutable history needed to verify them.

## Reproduce the demo

From the project root in PowerShell:

```powershell
.venv\Scripts\python.exe examples/section_demo.py --output .docguard-demo-my-sections
.venv\Scripts\python.exe examples/claim_requirements_demo.py --output .docguard-demo-my-claims
```

Both commands use new disposable Git repositories and make zero API calls. The
section demo checks generation/preview preservation, surrounding bytes and stale
reapplication. Inspect `proposal.json`, `publication-preview.json`, `evaluation.json`
and `repo/README.md` in the output directory. The claims demo shows available evidence
and missing-evidence review routing. Use a new directory for each run.

To exercise your configured Groq model, using the key in the project `.env`:

```powershell
.venv\Scripts\python.exe examples/section_demo.py --live --output .docguard-demo-my-live-sections
```

This makes one model request with synthetic example code, and no GitHub requests.
It has no automatic retries: on a quota/network failure, inspect the error before
starting another run. The live demo's simple multiplier check is not a general
semantic evaluator. Review the actual generated wording yourself.

For your own repository:

```powershell
python -m docguard suggest-git --root ../demo --base BASE_SHA --head HEAD_SHA --mapping docguard-map.json --document docs/prices.md --output proposal.json
python -m docguard apply-git-proposal proposal.json --root ../demo --document docs/prices.md --check
```

## Draft PR publication

Preview is local and does not need a GitHub token:

```powershell
python -m docguard publish-proposal proposal.json --root ../demo --document docs/prices.md --repository OWNER/REPO --source-pr 123
```

After inspecting that plan, the same command with `--publish` authorizes GitHub
writes. It reads `GITHUB_TOKEN` from the process environment (not the AI `.env`
loader). The token needs repository contents and pull-request write permissions.
The local checkout must match the proposal's source PR head. The source PR must
be open and in the same repository; fork publication is explicitly unsupported.

The publisher validates the proposal before networking, verifies the current PR
head, creates a tree containing only the document change on the original base tree,
and creates a draft targeting the **source PR branch**. Merging that draft would add
the repair to the original feature PR. It does not automatically merge anything.
GitHub's [tree API](https://docs.github.com/en/rest/git/trees) and
[pull request API](https://docs.github.com/en/rest/pulls/pulls) provide these operations.

The branch identity uses the source PR, source commit and document. Reruns reuse a
matching draft. A different generated patch for that identity, a modified repair
branch, a closed draft or a retargeted PR requires manual resolution; DocGuard never
force-pushes over those changes. Partial failures can leave a repair branch without
a PR; retry the same artifact to recover. Requests are bounded and errors do not
include credential values or raw remote bodies.

GitHub cannot atomically lock a source branch while a PR is created. DocGuard checks
before and after publication. A detected final race leaves a draft and reports an
error; inspect it and regenerate against the new source commit. This is a known
limitation, not an atomic publication guarantee.

## Install the GitHub workflow

`action.yml` is a reusable **analysis-only** composite action. It accepts root, base,
head, document, mapping, output, provider, model and live. It runs trusted DocGuard
source with Python 3.11 and treats the target checkout as data. It makes at most one
AI request and does not install or import the target project. For cross-repository
use, reference this action at a reviewed full commit SHA; a release tag has not yet
been published.

`.github/workflows/docguard-repair.yml` demonstrates separate analysis and publication:

1. Add the Groq key as repository secret `GROQ_API_KEY`.
2. **Create environment `docguard-publish` and configure required reviewers** before
   enabling publication. Merely naming an environment in YAML does not configure
   approval protection; availability depends on your GitHub plan/repository settings.
3. Allow the workflow token to create pull requests in repository Actions settings.
4. Dispatch **DocGuard controlled repair** with an open same-repository PR and a
   document. Leave live/publish false first to inspect the request artifact.
5. Run live analysis, inspect the artifact/diff, then approve the publication job
   only after that review. The publish job has write permissions; analysis has read
   permissions. The artifact SHA is passed from the same analysis run and verified.
6. Rerun the publish job with the same artifact to verify reuse. Regenerating analysis
   can produce a different patch; that is deliberately rejected for the same branch.

The workflow uses manual dispatch, trusted-tool checkout, no persisted checkout
credentials, one-document scope and per-source-PR concurrency. It does not use
`pull_request_target` to execute proposed code. Secrets and source evidence still
need your repository's approved data-sharing policy. Actual hosted execution and
environment protection must be verified in a separate installation trial.

## Tests

```powershell
.venv\Scripts\python.exe -m pytest tests/code/test_sections.py tests/code/test_publication.py tests/code/test_operations.py -v
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m ruff check src tests examples
.venv\Scripts\python.exe -m mypy src
```

Assertions are directly in those three test files. Publication tests use real local
Git histories and a stateful fake GitHub API; they never open real PRs. They cover
reruns, 429 recovery, concurrent creation, changed heads, forks, closed/modified
drafts, tampered artifacts and missing credentials. These tests do not replace the
hosted acceptance trial.
