# Live regression results — November 5, 2026

The changes improved completion and warning coverage, but did not solve unsupported
dependency inference. This is a single regression pass, not a general accuracy claim.

## Experiment

- Provider/model: Groq `openai/gpt-oss-120b`, unchanged from the baseline.
- Same ten cases from five upstream PRs; full manifest hashes verified unchanged.
- Prompt version 3 / Git prompt version 2, lossless request compaction, document-sized
  output allowance, and preservation diagnostics version 1.
- Ten API requests, no retries, 65-second inter-case cooldowns, cap of 12 requests.
- No HTTP 429 or HTTP 413 errors in the candidate run.
- Cases have been inspected during development. The original Click held-out label
  does not make this rerun a fresh held-out experiment. Gold labels remain provisional.

## Metrics

| Measure | Baseline | Candidate |
| --- | --- | --- |
| Completion | 9/10 | 10/10 |
| Correct decisions among completed cases | 7/9 (77.8%) | 8/10 (80%) |
| Correct decisions on the same nine completed cases | 7/9 | 8/9 |
| Required edits found | 3/4 | 4/4 |
| Edit precision | 3/3 | 4/5 |
| Unnecessary edits on expected-unchanged cases | 0/4 | 1/5 |
| Required abstention | 0/1 | 0/1 |
| Valid citation IDs | 9/9 | 10/10 |
| Human acceptance / semantic correctness | Not scored | Not scored |

All seven baseline passes remained passes. The deprecation case changed from fail
to pass. The missing-dependency case remained a failure. The previously uncompleted
Click case completed but failed its expected-unchanged decision. Thus the new
unnecessary edit is a newly observed failure, not a paired regression from a correct
baseline response.

## Case results

| Case | Baseline | Candidate |
| --- | --- | --- |
| HTTPX 3378, authentic | unchanged, pass | unchanged, pass |
| HTTPX 3378, stale claim | revise, pass | revise, pass |
| HTTPX 3364, authentic | unchanged, pass | unchanged, pass |
| HTTPX 3364, dependency ablation | unchanged, fail | unchanged, fail |
| HTTPX 1573, authentic | unchanged, pass | unchanged, pass |
| HTTPX 1573, base docs | unchanged, fail | revise, pass |
| HTTPX 1808, authentic | unchanged, pass | unchanged, pass |
| HTTPX 1808, base docs | revise, pass | revise, pass |
| Click 3239, authentic | HTTP 413 | revise, fail |
| Click 3239, base docs | revise, pass | revise, pass |

## Inspection of generated edits

**Warning coverage improved.** The HTTPX 1573 revision now mentions the runtime
`DeprecationWarning` and the supported `content` alternative. It retains the code
examples and the compatibility statement. It also rewrites the affected paragraph,
so a passing automated check should not be interpreted as byte-exact minimal editing.

**Dependency grounding did not improve.** In the ablated HTTPX 3364 case, the model
again inferred that `URL(url, params=params)` merges parameters without having the
helper implementation. It explicitly argued that no evidence contradicted the claim,
despite the new instruction explaining why that is insufficient. Its citation ID was
valid, but its conclusion was unsupported. Stronger instructions alone are inadequate.

**The formerly oversized request completed but over-edited.** Click's authentic HEAD
document already describes literal boolean defaults. The AI appended a redundant
`.. versionchanged:: 8.3.3` note. The version occurs in the supplied source; it was not
invented. The insertion is nevertheless unnecessary under the benchmark rubric, and
its directive syntax needs renderer review. Do not count successful API completion as
a correct documentation decision.

**Preservation is still imperfect.** The same heuristic was run against saved baseline
outputs and candidate outputs. Both the redirect repair and stale Click repair still
lose trailing newlines. The stale Click repair no longer changes unrelated `as-is`
punctuation or adds the earlier role-style cross-reference. The unnecessary authentic
Click edit also loses a trailing blank line. Three of five candidate revisions are
flagged, compared with two of three baseline revisions; on the three common revisions,
two are flagged in each run. These signals do not establish semantic correctness and
do not catch every new markup construct or unnecessary rewrite.

## Request efficiency

Rebuilding the same archived inputs reduced serialized request sizes by approximately
8–17%, including the longer instructions. The output allowance fell from 12,000 to
2,232–6,995 tokens for these cases. Full source evidence and diffs were retained.

For the **same nine completed cases**, reported token usage was:

| Tokens | Baseline | Candidate |
| --- | ---: | ---: |
| Input | 46,630 | 38,181 |
| Output | 5,019 | 6,417 |
| Total | 51,649 | 44,598 |

Input usage fell about 18%; total usage fell about 14%. Output usage increased.
Comparing totals across all requests would be misleading because the candidate also
completed the formerly rejected case. No monetary cost was inferred. The experiment
changes several factors together, so it does not isolate which change caused each
behavioral difference or prove a provider quota threshold.

## Verification and artifacts

The full offline suite passed with **340 tests, 4 skipped, and 179 subtests**.
Six subsequently added orchestration/preservation integration tests also passed.
Ruff, mypy, and `git diff --check` passed. Tests cover lossless/non-mutating compaction,
UTF-8 and bounded output allowances, preservation findings, unchanged gold labels,
model/manifest mismatch rejection, checkpoint reuse, and rate-limit stopping.

Local artifacts (evaluation JSON files are ignored by Git):

- `evaluation-paced-live-20261105.json`: unchanged original baseline.
- `evaluation-priorities-live-20261105.json`: candidate metrics and paired comparison.
- `evaluation-priorities-live-20261105-*.json`: individual case checkpoints and outputs.
- `evaluation-priorities-request-sizes-20261105.json`: archived-input size comparison.
- `evaluation-priorities-live-20261105-review-template.json`: unfilled human review form.

See [reproduction instructions](baseline-regression.md) for exact commands and limits.

## Remaining work

Prioritize claim-specific evidence requirements and explicit review routing when a
required dependency is unavailable. Avoid a blanket rule that every unresolved call
requires abstention; unrelated dependencies should not block verifiable claims.
Distinguish missing user-facing guidance from optional version-history additions.
Consider constrained edits and deterministic formatting preservation rather than
relying solely on full-document generation. Evaluate these changes on new independently
reviewed PR groups and repeated runs before claiming reliable generalization.
