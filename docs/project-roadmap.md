# Where DocGuard is — November 9, 2026

## Latest implementation

Section-scoped Git proposals now preserve bytes outside a mapped Markdown heading
path and revalidate that scope during apply. A reusable analysis action and explicit
draft publisher implement a local preview, source-head checks, same-repository
publication and idempotent reruns. Hosted execution remains an acceptance gate.

Thirty distinct pinned PR candidates are checked in, all pending review. The admitted
pilot is still five distinct PRs (ten original variants plus one claim-contract
experiment); intake does not increase the evaluated sample. Cross-manifest split
audits and operational summaries now expose counts and missing measurements.

Start with [targeted repair and publication](targeted-repair.md),
[benchmark intake](benchmark-intake.md), and [release acceptance](release-acceptance.md).
The phase table below describes the underlying project and its remaining work.

DocGuard is an evaluation-backed Python/Markdown documentation repair prototype.
The current milestone is **repair reliability**, corresponding to Phase 3 of the
project brief. Development has also reached into Phase 5 through pinned upstream PR
evaluations. The phases overlap; completing one experiment does not complete a phase.

## Status against the original brief

| Phase | What exists | What remains |
| --- | --- | --- |
| 1. Code-to-doc mapping | Python entities, snapshots, explicit document mappings, bounded dependency evidence, opt-in claim requirements | Reusable Markdown section index; suggested links with measured precision/recall; broader entity/language coverage |
| 2. Change detection | Git comparisons, metadata/body changes, separate line movement, mapped-document review, required-helper change triggers | Better relevance filtering and section-level impact; static changes do not prove a behavioral change |
| 3. Repair engine — current focus | Groq/OpenAI proposals, citations, preview/apply, stale guards, missing-evidence routing, bounded ATX section edits with outside-byte guarantees | Broader Markdown support, stronger semantic checks and claim coverage |
| 4. GitHub product | Read-only advisory workflow, reusable analysis action, bounded AI job, explicit draft publisher with rerun/head/lifecycle checks | Hosted installation trial, environment protection, immutable action pins and released action version |
| 5. Real-repository evaluation | Synthetic cases, ten original variants from five PRs, checkpointed live runs, human-review forms, separate contract experiment | Independent labels, larger distinct-PR benchmark, fresh held-out groups, repeated trials, human acceptance measurements |
| 6. Portfolio/release | CLI, docs, offline demos, recorded limitations | Supported release/install path, external install trial, end-to-end demo video, concise public evaluation summary |

The project is still Python-source focused. Other files are not automatically understood
as code merely because Git can read them. Markdown documents are the current repair target.

## What demonstrates senior-level engineering here

The strongest evidence will be decisions you can explain and measurements that support
them: where automation is allowed, when it abstains, how failures are reproduced, how
untrusted repository data is handled, and whether the tool saves reviewers time.
The opt-in claim gate is one such decision: known missing evidence prevents a paid
guess, while available evidence still requires semantic assessment.

Embeddings and a vector database are possible retrieval tools from the brief, not
requirements for every stage. First establish a labeled link-selection dataset and
measure the explicit-name/static-reference baseline. Introduce embedding retrieval
only as an experiment with measured improvements in relevant evidence coverage,
precision, latency, and cost. Keep low-confidence suggested mappings reviewable.

A second LLM pass is also an experiment, not an independent correctness oracle.
Measure whether it catches unsupported claims without causing excessive false
rejections. Keep deterministic gates and human review even if a critic model is added.

## Recommended milestones and acceptance criteria

### Implemented locally: one safe, targeted edit end to end

Build stable heading/section identities and propose replacements for a bounded section
or exact range. Require source/document hashes; apply only when the old range matches
exactly. Preserve all bytes outside it. Show the claim, evidence, decision origin,
missing evidence, and patch together in a readable review report.

Acceptance: changes to a target section succeed, unrelated sections remain byte-identical,
ambiguous headings and stale ranges are rejected, and generated proposals are never
applied merely because the model calls them high-confidence.

Knowledge: Markdown parsing, source ranges, optimistic concurrency, diff generation,
artifact validation, contract/integration testing. Existing Python and Git are sufficient
for the first version; a database or frontend is not required.

### Implemented; hosted acceptance pending: GitHub draft-PR workflow

Package the CLI as a reusable action with documented inputs/outputs and versioning.
Separate read-only analysis from a narrowly authorized publication step. Preserve the
current approach of treating proposed repository source as data. Account for forked
PRs, missing secrets, reruns, closed PRs, branch updates, duplicate proposals, and stale
HEADs. Use human approval for publication initially; do not introduce auto-merge based
on an LLM confidence score.

Acceptance: install it in a separate test repository; a deliberate code change produces
a review artifact and one draft documentation PR. A rerun updates or reuses the result
without duplicate PRs. Unavailable credentials and unsupported cases produce actionable
review results. Budget failures preserve checkpoints.

Knowledge: CI trust boundaries, scoped credentials, GitHub event payloads/API integration,
idempotency, artifact provenance, release packaging. Containerization is a packaging
choice to assess against the action's deployment requirements.

### In parallel: strengthen the benchmark and operating evidence

Expand toward approximately 30 **distinct PRs**, with independently reviewed claim
requirements and expected decisions. Keep all variants of a PR in one split. Cases
already inspected during development are regression cases, not fresh held-out data.
Measure completion separately from accuracy; include missed edits, unnecessary edits,
unsupported claims, abstention quality, reviewer acceptance, latency, tokens, retries,
and failures. Report contract-assisted and unassisted results separately.

Add structured per-run/case traces with versions and hashes, redacted errors, and explicit
budgets. Keep provider failure, policy block, invalid proposal, and semantic rejection
distinct. Evaluate repeated runs to quantify variability; avoid selecting only the best.

Acceptance: publish the dataset provenance, review rubric, denominators, limitations,
and reproducible commands. Independent judgments are actually supplied by reviewers,
not generated and labeled as human acceptance.

Knowledge: experimental design, leakage prevention, confidence/uncertainty reporting,
failure taxonomy, observability, and cost/latency tradeoffs.

### Finally: release and demonstrate the complete loop

Publish installation instructions and a tested release. Ask another developer to install
it without your help and record friction. Keep a small deterministic demo so the video
does not depend on API luck, and clearly label prerecorded/live/model-free portions.

A three-minute demo can show:

1. A code change makes one documentation claim stale.
2. The CI review displays the changed function and the evidence it selected.
3. A supported case produces a small documentation patch and draft PR.
4. A missing-dependency case routes to review with a specific reason.
5. The evaluation table shows both successes and failures, with the code and commands
   available for reproduction.

Avoid promising a completion percentage or a two-week delivery timeline from the brief.
Use acceptance criteria and external installation/review evidence to decide when each
milestone is done.
