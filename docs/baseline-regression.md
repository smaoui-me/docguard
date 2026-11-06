# Comparing AI changes against a saved baseline

The November 5 baseline exposed three different problems: an unsupported dependency
inference, an omitted deprecation warning, and one HTTP 413 request rejection.
A successful edit also changed unrelated formatting. These require separate measures.

## Implementation

`src/docguard/ai/provider.py` contains the system prompt and request construction.
Prompt version 3 (Git version 2) requires evidence for both revision and unchanged
decisions. A helper's name or call alone cannot establish its behavior. Missing
evidence only requires abstention when it matters to a documented claim. Newly
introduced warnings, exceptions, deprecations, and compatibility restrictions can
require updates even when the old prose is still literally true. Unaffected text
must be copied exactly, including trailing blank lines.

This is a model instruction, not a deterministic guarantee of grounded reasoning.
Citation validation still proves only that the cited ID exists.

Requests retain complete source evidence, diffs, entity metadata, and evidence gaps.
An identical `current_source` is replaced by its evidence ID. An identical historical
document is represented by `previous_document_same_as_current`. JSON uses compact
separators. Neither transformation truncates source or changes the gold labels.

The output-token allowance is bounded between 2,048 and 12,000 using the UTF-8 document
byte length plus 2,048. It is a heuristic allowance for a full-document response and
reasoning, not an exact tokenizer or a model/account limit. A length-truncated response
still fails explicitly. These changes reduce redundant input and reserved output;
they cannot guarantee that every provider will accept every request.

`src/docguard/ai/preservation.py` diagnoses trailing-newline changes, surface-only
edits, and newly introduced Markdown links or role-style cross-references. These are
separate review signals, not semantic pass/fail labels. A necessary link addition may
be flagged; an unnecessary semantic rewrite may go undetected. Existing required
claim/preserved-text checks remain unchanged for baseline comparability.

## Reproduce the regression experiment

From the repository root with the existing pinned upstream caches and `.env`:

```powershell
python -m pytest -q
python examples/evaluate_regression.py --output evaluation-regression-preparation.json
python examples/evaluate_regression.py --live --output evaluation-regression-live.json
```

The first evaluation makes no API calls. The second sends the pinned code and document
excerpts to the configured provider. Use new output names for a new experiment.
The default baseline is `evaluation-paced-live-20261105.json`; override with `--baseline`.
The runner verifies the model/provider, case selection, and full manifest hashes.
Keep the baseline's individual case reports alongside its aggregate report.

Live runs wait 65 seconds between cases, permit at most one bounded retry per case,
respect `Retry-After` up to 60 seconds, and stop on unresolved 429 or credential errors.
The request budget is 12 per invocation, including retries. A 413 is recorded, not
retried unchanged. Quotas can still vary by account and concurrent activity.

Each case is checkpointed. If interrupted before the final aggregate is created,
rerun the same command: compatible completed case reports are reused without another
API request. An interrupted in-flight request cannot be guaranteed exactly once.
The budget resets on a new invocation. Prompt/configuration changes reject resume.

The aggregate includes baseline/current metrics and per-case transitions. Preservation
diagnostics are recomputed on the saved baseline outputs using the same implementation.
Keep API completion, decision accuracy, edit recall, abstention, and preservation
findings separate. Inspect diffs and complete independent human review before claiming
semantic correctness or acceptance.

All ten cases have now been inspected, including the original held-out Click cases.
This rerun is a regression experiment, not fresh held-out evidence. One stochastic run
does not isolate each implementation change or establish generalization. Subsequent
experiments should include repeated runs and new independently reviewed PR groups.
