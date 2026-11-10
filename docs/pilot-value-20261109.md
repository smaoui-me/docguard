# Comparative live pilot — November 9, 2026

This run tests selective documentation decisions against simple policies. It is
**not** an independently reviewed benchmark, a complete rerun of the ten-case pilot,
or proof of production reliability. Five selected variants cover three distinct PRs:
HTTPX 3378, HTTPX 3364 and Click 3239. These cases were already inspected during
development, and the labels remain provisional.

## Observed decisions

Model: Groq `openai/gpt-oss-120b`, prompt version 3, Git prompt version 4.
The existing immutable manifests and expected decisions were unchanged. Each
checkpoint records their hashes, source pins and evidence. No labels enter the
model requests.

| Case | Expected | Actual | Decision source | Automatic checks |
| --- | --- | --- | --- | --- |
| HTTPX 3378 authentic HEAD documentation | unchanged | unchanged | Model | Passed |
| HTTPX 3378 authored stale-claim variant | revise | revise | Model | Passed |
| HTTPX 3364 dependency-ablation variant | needs_review | needs_review | Model | Passed |
| Click 3239 authentic HEAD documentation | unchanged | unchanged | Model | Passed |
| HTTPX 3364 explicit-requirement variant | needs_review | needs_review | Deterministic gate | Passed |

The stale-claim variant uses real PR source plus an explicitly authored obsolete
statement. The dependency-ablation variant intentionally omits source. Neither is
an untouched production PR document; those variants remain clearly identified.

The generated revision removed the claim that Request accepts bytes and documented
the supported string argument and uppercasing. The ablation response explicitly
identified the missing `URL(..., params=...)` behavior as preventing verification.
The Click response correctly recognized that the documentation already described
literal boolean handling. The explicit contract blocked model generation entirely.
These outputs were inspected during implementation, not independently reviewed.

## Comparison on the same four model cases

| Policy | Action agreement | Missed required edits | Unnecessary edits | Appropriate abstention |
| --- | --- | --- | --- | --- |
| DocGuard | 4/4 | 0/1 | 0/2 | 1/1 |
| Leave all docs unchanged | 2/4 | 1/1 | 0/2 | 0/1 |
| Route every change to review | 1/4 | 1/1 | 0/2 | 1/1 |

The baselines are deterministic decision policies, not competing model-generated
repairs. Review-all can be a sensible safe operational baseline despite lower action
agreement; a human may repair its routed cases. No human repair outcome or time is
measured here. DocGuard's demonstrated contribution in this sample is selective
behavior: one proposed repair, two untouched documents, and one evidence-aware
abstention. Do not translate those counts into invented developer hours saved.

Contract-assisted results are separate: 1/1 routed to review, matching review-all on
that case, with zero model calls. Do not add this result to model accuracy.

## Operations and resumption

| Measurement | Observed |
| --- | --- |
| Selected variants completed | 5/5 |
| Distinct PRs | 3 |
| Model requests | 4 |
| Deterministic gate decisions | 1 |
| HTTP failures / retries | 0 / 0 |
| Input / output tokens | 17,653 / 2,495 |
| Total tokens | 20,148 |
| Per-request p50 / p95 latency | 2.008 / 3.462 seconds |
| New requests on resumed invocation | 0 |
| Independent human acceptance | Not measured |
| Monetary cost or developer time saved | Not inferred |

Latency uses nearest-rank percentiles over four attempts and excludes the deliberate
65-second inter-case pacing. The initial invocation allowed at most six requests,
including retries. The gate case consumed no request. Completed checkpoints were
then resumed locally and independently revalidated, with no additional API calls.

Local artifacts (ignored by Git):

- `.docguard-demo-pilot-live/report.json`: aggregate, configuration identity, decisions,
  attempts and comparisons.
- `.docguard-demo-pilot-live/summary.md`: readable comparison table.
- `.docguard-demo-pilot-live/operations.json`: operational summary bound to report hash.
- Individual case JSON files in the same directory: full evidence and proposals.
- `.docguard-demo-pilot-preparation`: preparation-only run; zero API calls.

## Reproduce this exact selection

Use a new output directory and the existing upstream caches:

```powershell
.venv\Scripts\python.exe examples/run_pilot.py --live --max-requests 6 --delay-seconds 65 --output .docguard-demo-pilot-repeat --case httpx_3378_authentic --case httpx_3378_stale_claim --case httpx_3364_dependency_ablation --case click_3239_authentic --case httpx_3364_explicit_requirements
```

Add `--resume` with the same output/selection to reuse compatible completed cases.
Remove `--live` and choose a new output for preparation only. A changed model, prompt,
manifest or case selection rejects resume. The new orchestration tests cover request
budgets, 429 stopping, bounded pacing, interrupted runs, checkpoint corruption,
configuration mismatch, and no duplicate successful requests.

## What remains unproven

The dependency and Click cases failed in an earlier run and passed here. This does
not isolate a cause: model variability, prompt revisions and the selected sample
prevent a causal claim. Preserve the earlier failures and repeat trials instead of
reporting only this successful run.

The ten-case historical pilot is not replaced by this five-variant selection. The
thirty intake candidates still need review. Next: independent labels, a fresh grouped
held-out split, repeated bounded trials, and human ratings of correctness, completeness,
preservation and acceptance. Measure actual reviewer time in a counterbalanced
comparison before making productivity claims.

For the separate operational demo and hosted runner integration, see
[ci-benchmark-demo.md](ci-benchmark-demo.md). The existing DocGuard CI matrix passed
on GitHub. The private application demo now has four scenario PRs and hosted
analysis evidence; see [the hosted trial record](hosted-trial-20261109.md) for
passed checks and remaining acceptance gaps.
