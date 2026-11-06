# Upstream label review

Status: ten provisional cases, five real PRs, two repositories. No independent
human review has been completed. Do not present these as 30 reviewed real PRs.

## Evidence inspected

- HTTPX #3378: Request.__init__ removes bytes decoding and narrows the method
  annotation. Authentic Request documentation uses a string example. Its
  authored-stale variant explicitly adds an obsolete byte-support claim.
- HTTPX #3364: Request.__init__ changes query construction. The authentic case
  includes URL helpers; the controlled ablation deliberately withholds them.
- HTTPX #1573: encode_request adds a runtime DeprecationWarning for raw data.
  Base docs mention type-checker warnings and continued support, while HEAD docs
  disclose the deprecation warning. Both inputs are exact historical sections.
- HTTPX #1808: API and BaseClient redirect defaults change from enabled to disabled.
  The old HEAD-redirection section contradicts the new defaults. The authentic
  case uses base_section because the new document section is called Redirects.
- Click #3239: Option.get_default adds `and not self.is_bool_flag`. Historical
  Flag Value docs generalize `default=True` substitution to flags; HEAD limits
  that rule to non-boolean flags and adds boolean examples. The mapped parent
  get_default implementation and Context.lookup_default provide supporting
  default-resolution evidence. Selected files are exact upstream blobs; the
  full application and all its dependencies are not supplied to the model.

Full pins, mappings, expected actions, text checks, and rationales are in the TOML
manifests. Generated preparation reports record source hashes and exact selected
line ranges. A base_docs case reconstructs stale documentation; authentic_head
checks whether the documentation already supplied by the author is sufficient.

## Independent review checklist

1. Inspect the pinned base/head diff and original document section before looking
   at model output. Verify license and PR provenance.
2. Decide whether the supplied evidence supports revise, unchanged, or
   needs_review. Record why and which exact claims and source lines establish it.
3. Check all regex assertions against the intended meaning. They are proxies;
   correct paraphrases may fail them, and incorrect prose may pass them.
4. Record reviewer identity, date, agreement/disagreement and corrections in a
   reviewed change to the manifest. Resolve disagreements before freezing labels.
5. Keep every variant of a PR and closely related API changes in one split.
   Keep HTTPX for development and Click reserved. Do not adjust prompts based on
   reserved results. If a case leaks into tuning, move the whole group out of the
   held-out set and recruit a new group.
6. Add real PRs in small reviewed batches toward about 30 changes. Count distinct
   PRs separately from variants. Include genuine historical stale prose, no-edit
   negatives, missing dependencies, renames, deletions and multi-file behavior.

The tests validate pins/manifest shape, grouping and pipeline behavior. They
cannot replace an independent person's judgment of labels or generated claims.


## Record actual output reviews

Use `docguard review-template REPORT --output REVIEWS.json` to create a pending
form for completed model cases. Review source and proposed prose manually, fill
all boolean ratings and `expected_action`, and supply reviewer identity and notes.
Mark `independent` true only if the reviewer did not author the implementation,
case, or expected label. Use `docguard score-review REPORT --reviews REVIEWS.json
--output SCORES.json` to summarize judgments separately from automatic checks.
The exact report hash prevents applying a form to a changed/resumed report.
Identity and independence are attestations; the tool cannot verify them. A label
disagreement is surfaced for adjudication and does not silently rewrite gold data.
