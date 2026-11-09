# From PR candidates to a reviewed benchmark

`evaluations/candidates/httpx.json` and `click.json` contain **30 distinct candidate
PRs**: 15 from each repository, pinned to full integration commits and first parents.
All are pending, unassigned and not admitted. Expected actions and reviewers are
null. They are not thirty independently reviewed evaluation cases.

Candidate collection scans the existing local Git caches; it does not fetch PR
comments or run upstream code. PR links are inferred from commit titles containing
`(#123)`. During review, verify that association against the actual GitHub PR. The
pins describe the integration change, which may differ from the original PR head
after squash or merge. Source/document paths are leads for inspection, not mappings.

Reproduce collection with new output names:

```powershell
python -m docguard benchmark-candidates --repository .docguard-upstream/httpx-full.git --upstream encode/httpx --limit 15 --output httpx-candidates.json
python -m docguard benchmark-candidates --repository .docguard-upstream/click.git --upstream pallets/click --limit 15 --output click-candidates.json
```

The selector favors commits changing both implementation and documentation. That
is useful for authentic already-correct examples and base-document variants, but
creates selection bias: it misses many code-only stale-documentation changes.
Thirty candidates are an intake queue, not a balanced final benchmark. Replace
unsuitable candidates and deliberately add code-only changes, missing dependencies,
renames/deletions and genuine no-documentation-impact changes. Some candidates use
RST; the current upstream projection evaluator requires Markdown. Do not silently
convert them and label the result authentic; exclude or explicitly extend format
support with its own tests.

## Review and admit one case

1. A reviewer checks the PR URL, integration commit, parent, license and source diff.
   For example: `git --git-dir=.docguard-upstream/httpx-full.git show HEAD_SHA -- docs/api.md`.
   Replace HEAD_SHA and the document path with values from the candidate. Inspect
   the source paths and both revisions too; a PR title alone is insufficient.
2. Select one concrete document claim/section and relevant source entity IDs.
   Preserve before/after provenance. If a helper determines behavior, include it
   or record an intentional evidence-ablation variant separately.
3. Independently label `revise`, `unchanged` or `needs_review` before seeing a model
   output. Write the expected facts and a rationale with source lines. Distinguish
   authentic HEAD documents from base-document and authored-stale variants.
4. A second person checks the label, evidence sufficiency and preservation rubric.
   Record reviewer identity, date, disagreements and resolution. A model-generated
   label or an agent's inspection is not independent human review.
5. Assign all variants of that PR and related API-change groups to one split.
   Cases inspected while tuning become development/regression data. Freeze fresh
   held-out groups before prompt tuning; keep their labels out of requests.
6. Add the reviewed projection to an upstream TOML manifest using `httpx.toml` as
   the schema example. Record the actual review status and rationale, and retain
   external review notes alongside it. Start with preparation-only evaluation:

   ```powershell
   python -m docguard evaluate-pr --repository .docguard-upstream/httpx-full.git --manifest evaluations/upstream/YOUR_CASES.toml --output preparation.json
   python -m docguard benchmark-audit evaluations/upstream/httpx.toml evaluations/upstream/YOUR_CASES.toml --output split-audit.json
   ```

7. Inspect the saved evidence, then run a bounded live evaluation. Existing
   `evaluate-pr --live --max-requests 1` and `--resume` preserve checkpoints and
   bound retries. Never resume a report under changed model/prompt/manifest settings.
8. Create an unfilled output review form with `review-template`; an independent
   person evaluates claim accuracy, completeness, unrelated text and acceptance.
   `score-review` checks that ratings belong to the exact report bytes.

`benchmark-audit` rejects duplicate IDs and split leakage across multiple manifests.
It counts distinct PRs separately from variants. It does **not** certify independent
review merely because a manifest's free-text `review_status` says so.

## What to measure

Use `summarize-evaluation REPORT.json --output operations.json` on an upstream report
to derive completion, unnecessary edits, missed edits, appropriate abstention, case
status, decision origin, API attempts, retry waits, failure status, token usage and
nearest-rank p50/p95 attempt latency. Ratios include numerators and denominators;
undefined rates are null. Raw source, generated content and credentials are excluded.
Missing telemetry remains unknown. Use individual upstream checkpoints for attempt
statistics; older aggregate reports do not contain all attempt records.

Report action agreement separately from semantic correctness and human acceptance.
Report deterministic claim-gated results separately from model decisions. Use fixed
case selections and repeated runs for comparisons; do not discard provider failures
or present only the best run. Publication/section tests prove enforcement behavior,
not that the model's replacement prose is true.
