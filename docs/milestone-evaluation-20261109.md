# Repair and publication milestone evaluation — November 9, 2026

## What changed

- Optional v2 mapping heading paths constrain Git proposals to one ATX Markdown section.
  Application independently checks scope and exact original bytes. Unrelated mixed
  newlines, Unicode and whitespace are preserved by construction.
- `publish-proposal` defaults to offline preview. Explicit publication revalidates
  evidence, verifies the current source PR, and creates/reuses one matching draft.
  Forks, stale heads, changed repair branches and closed/modified drafts are refused.
- `action.yml` provides bounded analysis. A manually dispatched workflow separates
  analysis from environment-controlled publication and routes non-revisions to artifact
  review. Hosted execution and approval settings remain unverified externally.
- Thirty distinct pinned candidate PRs are checked in, with null expected labels and
  pending reviews. `benchmark-audit` detects cross-manifest split leakage and distinguishes
  PRs from variants. `summarize-evaluation` exposes quality denominators and operations.
- A console entry point, repeatable section demo and external acceptance checklist
  support installation and presentation.

## Automated verification

On this Windows/Python 3.14 environment:

| Check | Observed result |
| --- | --- |
| Full suite after main implementation | 409 passed, 4 skipped, 179 subtests; 419.17 seconds |
| Focused regression after additional edge cases | 85 passed, 1 skipped, 22 subtests; 87.49 seconds |
| Operational input-validation follow-up | 9 passed |
| Final section/workflow guard checks | 16 passed |
| Ruff and strict mypy | Passed; 32 source files type checked |
| Offline section demo | All five checks passed; zero API calls |
| Local wheel installation into a fresh environment | Installed; isolated module and console entry point help succeeded |

Full and focused counts overlap; do not add them together as distinct coverage.
The full-run log is `.pytest_cache/release-milestone-tests.txt`; focused results are
in `.pytest_cache/release-focused-tests.txt`. Skips are not counted as passes.
GitHub publication is exercised with real local Git history and a stateful fake API,
including 429 recovery and concurrent reruns. No actual GitHub PR was created.

The first package attempt lacked the build backend. An isolated build downloaded
the declared setuptools requirement; after changing the output directory from the
cache to `dist`, the wheel built and installed successfully. This is an automated
local packaging check, not an independent developer's acceptance trial.

## Live model smoke test

The first restricted-network attempt failed to connect. A single subsequent
network-enabled Groq request completed successfully using `openai/gpt-oss-120b`.

| Measurement | Result |
| --- | --- |
| Generation including local evidence preparation | 2.423 seconds |
| Input tokens | 1,529 |
| Output tokens | 390 |
| Total tokens | 1,919 |
| Model output | Corrected the selected claim to `price multiplied by 1.2` |
| Generation and preview preserve document | Both passed |
| Outside-section bytes identical | Passed |
| Multiplier mentioned | Passed |
| Stale reapplication refused | Passed |
| GitHub writes | 0 |

Artifacts are local and ignored by Git:
`.docguard-demo-sections-live-network-20261109/proposal.json`,
`publication-preview.json`, `evaluation.json`, and `repo/README.md`.
The equivalent offline run is `.docguard-demo-sections-20261109`.
This is one simple authored smoke case, not a new benchmark score or evidence of
generalization. The multiplier check is deliberately narrow; the generated prose
was also inspected.

## Comparison with existing evidence

The historical original pilot and November 5 candidate results were summarized
without rerunning or changing their labels:

| Metric | Original run | November 5 candidate run |
| --- | --- | --- |
| Completion | 9/10 | 10/10 |
| Unnecessary edits among completed expected-unchanged cases | 0/4 | 1/5 |
| Missed edits among completed expected-revise cases | 1/4 | 0/4 |
| Required abstention achieved | 0/1 | 0/1 |

These are **historical** comparisons, not improvements caused by today's work.
The last original-pilot score remains 8/10 automatic passes. The missing-dependency
inference and unnecessary Click edit remain semantic failures in that record.
Opt-in claim requirements and section enforcement address explicit availability and
editing boundaries; they do not prove all in-section claims or decisions correct.

An audit of the current upstream manifests found 11 variants from **five distinct
PRs**, including the separate claim-contract experiment. Declared splits were
consistent across files. No independent labels were verified. The thirty new
candidates do not increase either the reviewed or evaluated sample.

## Current phase and next acceptance gates

DocGuard has an end-to-end local repair prototype and a locally tested publication
implementation: Phase 3 repair reliability is substantially implemented for the
supported subset, while Phase 4 product integration needs hosted acceptance.
Phase 5 evaluation infrastructure exists but benchmark independence and scale remain
unfinished. Phase 6 packaging/demo support exists but no public release or external
trial has been completed.

Next, install the workflow in a disposable repository and verify an approved draft,
rerun reuse and stale-head failure. Have another developer follow the instructions.
Then review a small diverse batch from the candidate queue, freeze fresh held-out
groups, and repeat bounded evaluations with independent output ratings. Only after
those checks should a release claim broader reliability. See
[release acceptance](release-acceptance.md) and [benchmark intake](benchmark-intake.md).
