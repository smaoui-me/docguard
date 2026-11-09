# Claim-specific evidence requirements

DocGuard can now enforce a declared evidence requirement before calling a model.
The requirement checks **availability**, not whether a claim is true. It is opt-in;
version 1 mappings retain their existing behavior.

## Example

Commit a version 2 mapping alongside the source and documentation:

```json
{
  "schema_version": 2,
  "documents": {
    "README.md": {
      "entity_ids": ["api.py:total"],
      "claims": [
        {
          "id": "price-result",
          "quote": "total(price) returns the price unchanged.",
          "required_evidence": [
            "after:api.py:total",
            "after:api.py:transform"
          ]
        }
      ]
    }
  }
}
```

The quote identifies the claim to check; it is not an assertion that it is correct.
Required IDs use existing Python entity IDs prefixed with `before:` or `after:`.
Use `after:` for current behavior, and `before:` when a historical implementation is
necessary, for example to explain a removal. These are exact entity IDs; renames and
overloads still need explicit mapping maintenance.

For affected documents, DocGuard:

1. Resolves requirements against the pinned merge-base and HEAD trees.
2. Adds available required snippets even if heuristic dependency retrieval would not
   select them. Source is parsed as data, never imported or executed.
3. Requires exactly one occurrence of the quoted text in the HEAD document.
4. Checks that every required evidence ID is present on the specified revision side.
5. If either check fails, emits `needs_review` with the claim ID and missing evidence
   or anchor ambiguity. **The model is not called.** One blocked claim routes the whole
   document to review; partial automatic repair is not implemented.
6. Otherwise, sends the evidence to the model for semantic assessment. The model may
   still abstain. Available evidence does not guarantee a correct model response.

Existing context limits still apply. Large requirements fail explicitly before an API
call instead of truncating code. Requirements are bounded to 50 claims per document,
50 evidence IDs per claim, and 4,000 characters per quote.

Required helpers also participate in change detection. A change, deletion, or addition
of a required helper can flag the document even if the originally mapped function is
unchanged. Required references missing from both snapshots are permitted and cause
review when the document is affected; unknown primary `entity_ids` remain configuration
errors. Unrelated unresolved calls do not automatically block a document.

## Artifacts and application

Inspect `review.claim_requirements` in dry-run and proposal artifacts. It contains
the gate version and per-claim status, quote matches (0, 1, or 2 meaning two or more),
and missing evidence IDs. A blocked document is omitted from dry-run `requests`, but
remains in the review findings. A normal run writes its deterministic `needs_review`
proposal with no replacement content.

Apply reconstructs the gate from the committed mapping and source. Changing an artifact
from `needs_review` to `revise` cannot bypass a missing requirement. Existing source,
document, and mapping staleness checks still apply. As before, artifacts are not signed
and this does not establish arbitrary semantic authenticity for ready proposals.

Snapshot-only `suggest` rejects claim mappings explicitly: it cannot supply historical
source. Use `suggest-git`. Requirements are operator-maintained, not automatically
extracted from prose. After accepting a changed claim, update its quoted anchor in the
mapping; stale or ambiguous anchors deliberately require review next time. A contract
edit alone is not currently a change-detection trigger.

Treat changes to these requirements as policy changes during code review. The gate
uses the committed HEAD mapping; someone who can change that mapping can remove a
requirement. Rechecking an artifact prevents that artifact from bypassing the declared
policy, but it does not make repository policy immutable.

## Test it without an API key

From the repository root:

```powershell
python -m pytest tests/code/test_claim_requirements.py -v
python examples/claim_requirements_demo.py --output .docguard-demo-my-claims
```

Choose a new directory each time. The demo creates two disposable Git repositories:

- `missing/proposal.json`: an actual `needs_review` proposal; the helper is unavailable.
- `available/requests.json`: a dry-run request containing the required helper. It is
  ready for AI assessment, not an AI-generated correction.

Both paths make zero API requests. Inspect each committed `docguard-map.json` and
`api.py`. To test a stale anchor, change the quote in the available repository's mapping
and commit it. Then run a dry-run against the base commit printed by the demo:

```powershell
python -m docguard suggest-git --root .docguard-demo-my-claims/available --base BASE_SHA_FROM_DEMO --head HEAD --output claims-anchor-check.json --dry-run
```

The result should contain zero requests and a `needs_review` claim route. Use a new
output filename on each run. Git mode reads committed data, so uncommitted mapping
edits do not affect generation.

## Evaluation evidence

`evaluations/upstream/httpx_claims.toml` is a **separate operator-annotated variant** of
the known HTTPX query-parameter dependency-ablation case. It declares that the merge
claim needs `after:httpx/_urls.py:URL.__init__`, which the projection intentionally omits.
The original baseline manifest and labels were not modified.

On November 6, the variant produced `needs_review`, passed its automatic checks, and
made **zero API requests**. The local report is
`evaluation-claims-routing-20261106.json`; `decision_source` is `deterministic_gate`.
Its `live` mode means the evaluator was permitted to generate a decision, not that
it called a model. Token usage is absent. This tests policy enforcement, not a model
accuracy gain. The previous 8/10 live score remains the historical baseline.

The upstream runner accepts optional `[[cases.claims]]` entries, validates them, and
creates a version 2 projection mapping. It records decision origin and distinguishes
affected documents from the number of paid requests. Resume identity includes the
gate version; changed manifests/configuration cannot silently mix results.
