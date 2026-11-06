# Evaluating actual upstream pull requests

The first pilot uses HTTPX PRs [#3378](https://github.com/encode/httpx/pull/3378)
and [#3364](https://github.com/encode/httpx/pull/3364). Their full base/head commit IDs
are pinned in `evaluations/upstream/httpx.toml`. This is a development pilot with
provisional labels pending independent review. Click PR [#3239](https://github.com/pallets/click/pull/3239) adds two reserved cases in `evaluations/upstream/click.toml`. They have not been used for prompt tuning; this small dataset is not a validated benchmark.

## What is included

| Case | Input | Provisional expectation |
| --- | --- | --- |
| `httpx_3378_authentic` | Actual Request documentation section and code | `unchanged`: the string-method example still works; it never promised byte inputs |
| `httpx_3378_stale_claim` | Actual code, with an explicitly authored obsolete byte-input claim added to docs | `revise`: remove the unsupported byte-input claim |
| `httpx_3364_authentic` | Actual Request section and mapped Request/URL helpers | `unchanged`: existing prose does not promise query-string merging |
| `click_3239_authentic` | Actual HEAD Flag Value documentation and default-resolution code | `unchanged`: docs already distinguish boolean and non-boolean defaults |
| `click_3239_base_docs` | Actual base Flag Value documentation with HEAD code | `revise`: the historical general rule needs the boolean exception |
| `httpx_1573_authentic_head` / `httpx_1573_base_docs` | Actual request-content docs and encoding implementation | `unchanged` / `revise`: document the new runtime deprecation warning |
| `httpx_1808_authentic_head` / `httpx_1808_base_docs` | Actual redirect docs and API/client defaults | `unchanged` / `revise`: redirect following becomes opt-in |
| `httpx_3364_dependency_ablation` | Actual Request code, an authored merging claim, with URL helpers deliberately withheld | `needs_review`: the new helper's effects cannot be established from supplied evidence |

There are ten cases across five PRs and two repositories. The HTTPX authored
claim and dependency ablation are **controlled variants**, not upstream bugs.
Click's `base_docs` case uses genuine historical prose without an authored prefix;
the real PR updated that prose, so this is a reconstruction of the repair task,
not a claim that the upstream bug remains unfixed.

Every case has a `split` and related-change `group`. Both Click variants belong to
the same reserved (`held_out`) group; HTTPX constructor cases are development.
Manifest validation rejects a PR/group split across partitions, and a repository
test checks grouping across all checked-in manifests. Do not tune prompts against
the reserved results. Labels were inspected against code and docs during
implementation; independent human review is still pending. See
`evaluations/upstream/REVIEW.md` for the review protocol.

The runner copies selected **complete source files** and the exact selected Markdown
section into disposable Git repositories. This is a scoped projection, not the
full upstream repository. It records original and projection commit IDs, source
hashes, document line ranges, full/selected/input document hashes, transformations,
and the upstream license text. Code citation lines still refer to exact original
source files; citation commit IDs in the nested proposal refer to the projection.
Use the report's provenance mapping to locate the corresponding upstream revisions.

Nothing is imported or executed from HTTPX. No upstream dependency installation or
test suite is required. The pilot assesses DocGuard; it does not independently
prove HTTPX's runtime behavior. Manifests and expected claims are not model input.

## Acquire the public repository once

From the DocGuard project root:

```powershell
git clone --bare --no-tags https://github.com/encode/httpx.git .docguard-upstream/httpx.git
```

If that directory already exists, reuse it. It is ignored by Git. Do not commit
the clone or generated reports. A full bare clone avoids lazy downloads during
evaluation. The runner requests local Git objects only; missing objects fail before
model calls. If you used a partial/shallow clone, download the required pinned
objects explicitly or use a fresh full clone. The runner does not fetch revisions.

## Prepare and inspect without calling a model

```powershell
.\.venv\Scripts\python.exe -m docguard evaluate-pr --repository .docguard-upstream/httpx.git --output pr-preparation.json
```

The report contains exact assembled requests and provenance. `mode` is
`preparation-only`: no model accuracy is assigned. All cases are preflighted before
any paid requests. The command refuses to overwrite an existing output file.

## Run the pilot live

Configure `.env` normally, then:

```powershell
.\.venv\Scripts\python.exe -m docguard evaluate-pr --repository .docguard-upstream/httpx.git --live --max-requests 4 --output pr-live.json
Get-Content pr-live.json
```

This allows at most four requests. Start with one case if quota is limited:

```powershell
.\.venv\Scripts\python.exe -m docguard evaluate-pr --repository .docguard-upstream/httpx.git --case httpx_3378_authentic --live --output pr-one-case.json
```

HTTP 401/403 stops immediately. HTTP 429 retries up to `--max-retries` (default 2),
using numeric or HTTP-date `Retry-After`, or 1, 2, ... seconds of exponential
backoff if it is absent/invalid. If the delay exceeds `--max-retry-wait` (default
30 seconds), DocGuard stops rather than retrying earlier than requested. Other
HTTP failures and uncertain network failures are not automatically retried.
Every attempt consumes `--max-requests`; this is a **per-invocation** budget,
including retries. Unused cases remain in the report when the budget runs out.
Use a new output filename for an independent run. Results include model output, citations,
validation checks, timing and token usage when returned by the provider. Monetary
cost is null: no prices are guessed. Preview validation occurs in temporary trees;
the upstream checkout/cache and your project documents are not modified.

Exit 0 means preparation succeeded or all completed live cases passed automatic
checks; 1 means a live failure, operational error or unrun cases; 2 means invalid
configuration or failed preparation. Exit 0 is not human approval of correctness.

## Resume without repeating completed cases

Reports use schema version 2. They are checkpointed atomically before each API
attempt, after attempts, and after each case. This retains earlier results if a
later case fails or you interrupt with Ctrl+C.

```powershell
.\.venv\Scripts\python.exe -m docguard evaluate-pr --repository .docguard-upstream/httpx.git --live --max-requests 2 --output pr-resumable.json
# Later: same manifest, selection, provider, model, and prompts; another budget of 2.
.\.venv\Scripts\python.exe -m docguard evaluate-pr --repository .docguard-upstream/httpx.git --live --max-requests 2 --output pr-resumable.json --resume
```

Completed cases are kept even if their quality checks failed. Validation failures
are also retained. API failures and unfinished cases can be attempted again.
Dataset bytes, selected case IDs, mode, provider, model, prompt versions and the
request template hash must match. Credentials are not stored or fingerprinted, so
you can rotate your key. Preparation reports cannot be resumed as live runs, and
old schema-1 reports need a fresh run. Total API attempts and available token usage
accumulate; `session_requests` describes the current invocation.

A `.json.lock` file prevents concurrent writers. Ctrl+C normally releases it. A
hard process termination can leave it behind: check that no evaluator is running
before removing that lock. Never run two processes against the same report.
A crash after the provider accepted a request but before its result was saved is
ambiguous: resume may repeat that unfinished request. This is not an exactly-once
billing guarantee. Reports are local artifacts, not signed attestations.

## Prepare the Click cases

```powershell
git clone --bare --no-tags https://github.com/pallets/click.git .docguard-upstream/click.git
git -C .docguard-upstream/click.git fetch origin refs/pull/3239/head
.\.venv\Scripts\python.exe -m docguard evaluate-pr --repository .docguard-upstream/click.git --manifest evaluations/upstream/click.toml --output click-preparation.json
```

The fetch acquires the PR head even when it is absent from normal branch history.
The manifest's full commit IDs remain authoritative. Reuse an existing clone;
cloning again into it will fail. Add `--live --max-requests 3` and a new output path
for a model evaluation. No upstream tests or dependencies are installed.

## Metrics and denominators

Each rate stores `numerator`, `denominator` and `value`. A zero denominator produces
null, not a misleading zero or perfect score. Operational errors are not scored as
wrong model decisions; completion coverage must be read alongside quality rates.

| Metric | Definition | Limitation |
| --- | --- | --- |
| Completion coverage | Completed/selected cases | Reveals API errors and cases not run |
| Detection agreement | Relevant-document flag matches expected flag/prepared cases | Relevance is not the same as requiring an edit; this pilot lacks detector-negative cases |
| Action accuracy | Correct revise/unchanged/needs_review decisions/completed cases | Based on provisional labels |
| Edit precision | Correctly requested edits/all proposed edits in completed cases | Does not establish quality of the generated text |
| Edit recall | Correctly requested edits/all expected-edit cases that completed | Inspect coverage: unavailable cases are excluded |
| Unnecessary edit rate | Revisions on expected-unchanged cases/completed expected-unchanged cases | Measures avoidable churn |
| Required abstention recall | needs_review on expected-needs_review cases/completed such cases | Measures calibrated caution, not universal uncertainty detection |
| Automatic checks pass rate | All applicable checks pass/completed cases | Regex claims and preserved text are proxies |
| Citation validity | Responses with valid evidence IDs/responses assessed for citations | A real citation can still be misinterpreted |
| Model latency | Time spent in provider calls | Separate from projection/preparation work; machine/network dependent |
| Input/output tokens | Provider-reported usage | Missing usage stays null; no fabricated cost estimates |

Metrics are reported overall and by input variant. Do not mix controlled variants
with authentic cases and call the result "accuracy on real PRs." Four cases from
two PRs are too small and correlated for a general performance claim. All variants
of a PR belong in the same development/held-out group.

## Human evaluation remains necessary

Each case includes a pending `human_review` form. Review without seeing which model
or prompt produced the answer when practical. Inspect code, citations and complete
proposed prose; record:

- **Claim accuracy:** is every new claim supported? List unsupported statements.
- **Completeness:** were the required user-visible changes documented?
- **Preservation:** were unrelated statements, examples and formatting preserved?
- **Decision:** was editing, leaving unchanged, or requesting review appropriate?
- **Acceptance:** would you accept the change, revise it, or reject it? Give reasons.

Semantic correctness and human acceptance aggregates remain null until you build
and adjudicate those reviews; this runner does not turn regex success into a
hallucination score. Store completed reviews separately with the report filename
or hash, reviewer and rubric version. Manual form edits do not recompute summaries.

## Adding another actual PR

1. Inspect the PR discussion, diff, tests and affected docs. Verify that the number
   is a PR rather than a linked issue. Record its exact base/head and license.
2. Add a manifest case with relevant source paths, entity IDs, document section,
   variant, expected decision, rationale and minimal grading checks. Preserve the
   original input; never silently fabricate a documentation defect.
3. Prefer changes whose behavior can be assessed from a bounded context. Introduce
   multi-file and missing-context cases deliberately rather than silently truncating.
4. Have another person review the label. Mark disagreements and unresolved claims
   as provisional instead of forcing a gold answer.
5. Run preparation, inspect the payload and provenance, then run a small live batch.
6. Reserve whole PR groups for assessment; keep variants together. Public PRs may
   have appeared in training data, so public history is not a contamination-free holdout.

The upstream manifest contains metadata and authored claims, not copied HTTPX code.
Generated local projections/reports retain the upstream license. When redistributing
them, retain the attribution and license included in the report/projection.

## Automated tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/code/test_upstream_evaluation.py tests/code/test_ai_provider.py tests/code/test_groq_provider.py -vv
```

These are offline and use disposable local repositories and mocked providers. They
cover exact pins, scoped provenance, transformed docs, budget and output preflight,
no label/credential leakage, token usage, citation rejection, rate-limit stopping,
and metric denominator calculations. They do not clone public repositories or make
paid calls in CI.


## Evidence policies and human scoring

See [the evidence and human review guide](evidence-and-review.md) for the offline
comparison demo and the `review-template` / `score-review` commands. New optional
manifest fields are `evidence_policy = "direct"` (default `mapped`) and
`base_section` when an upstream PR renames a documentation heading. The selection
policy and source scope are part of the dataset configuration; do not change them
mid-run. Resume identity now also includes the evidence selector version. Reports
from before this change require a fresh run.

To acquire every HTTPX PR used by this expanded manifest, use a full bare cache
(reuse the existing directory if already created):

```powershell
git clone --bare --no-tags https://github.com/encode/httpx.git .docguard-upstream/httpx-full.git
git -C .docguard-upstream/httpx-full.git fetch origin refs/pull/3378/head refs/pull/3364/head refs/pull/1573/head refs/pull/1808/head
.\.venv\Scripts\python.exe -m docguard evaluate-pr --repository .docguard-upstream/httpx-full.git --output expanded-preparation.json
```

The latest expansion adds genuine historical documentation from PRs
[#1573](https://github.com/encode/httpx/pull/1573) and
[#1808](https://github.com/encode/httpx/pull/1808). Historical docs are deliberately
paired with new code for the repair cases. The original PR authors already updated
those docs; these cases do not assert that current HTTPX documentation is broken.
