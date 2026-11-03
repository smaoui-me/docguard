# Evaluating actual upstream pull requests

The first pilot uses HTTPX PRs [#3378](https://github.com/encode/httpx/pull/3378)
and [#3364](https://github.com/encode/httpx/pull/3364). Their full base/head commit IDs
are pinned in `evaluations/upstream/httpx.toml`. This is a development pilot with
provisional labels pending independent review, not a held-out benchmark.

## What is included

| Case | Input | Provisional expectation |
| --- | --- | --- |
| `httpx_3378_authentic` | Actual Request documentation section and code | `unchanged`: the string-method example still works; it never promised byte inputs |
| `httpx_3378_stale_claim` | Actual code, with an explicitly authored obsolete byte-input claim added to docs | `revise`: remove the unsupported byte-input claim |
| `httpx_3364_authentic` | Actual Request section and mapped Request/URL helpers | `unchanged`: existing prose does not promise query-string merging |
| `httpx_3364_dependency_ablation` | Actual Request code, an authored merging claim, with URL helpers deliberately withheld | `needs_review`: the new helper's effects cannot be established from supplied evidence |

Two cases use authentic head documentation; two are **controlled variants**, not
upstream documentation bugs. The manifest supports `base_docs` for a different
repair task: head code with the actual base documentation. No such variant is
needed for this initial pilot because these PRs did not provide a useful outdated
claim in their original Request prose.

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

HTTP 401/403/429 stops further requests and records unrun cases. There are no retries.
Use a new output filename on each run. Results include model output, citations,
validation checks, timing and token usage when returned by the provider. Monetary
cost is null: no prices are guessed. Preview validation occurs in temporary trees;
the upstream checkout/cache and your project documents are not modified.

Exit 0 means preparation succeeded or all completed live cases passed automatic
checks; 1 means a live failure, operational error or unrun cases; 2 means invalid
configuration or failed preparation. Exit 0 is not human approval of correctness.

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
