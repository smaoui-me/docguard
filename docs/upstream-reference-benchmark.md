# Benchmark against the engineers' corrections

For **fully automatic live output comparison**, use
[automatic reference evaluation](automatic-reference-evaluation.md). That workflow
requires no manual labels or review forms. The optional manual workflow below
remains available for inspecting or auditing results.

DocGuard can now build a paired experiment from one pinned upstream PR:

| Case | Model receives | Reviewer compares against |
| --- | --- | --- |
| `base_docs` | New code and the exact old documentation section | The upstream author's updated section |
| `authentic_head` | New code and the exact updated section | The same upstream change; check for unnecessary edits |

Reference sections, documentation diff, commit IDs, source blob hashes and selected
line ranges are stored outside model contexts. Neither generation nor the
experimental validator receives a separate reference answer. Updated-doc controls
naturally contain the updated section as their input. Both variants share one PR
group and split. Upstream source is parsed, never executed.

## Open the prepared starter

```powershell
Start-Process .docguard-demo-upstream-reference/review.html
```

It contains four cases from two PRs:

- [HTTPX #1573](https://github.com/encode/httpx/pull/1573): raw request data and
  deprecation warnings, with historical and updated documentation.
- [Click #3239](https://github.com/pallets/click/pull/3239): boolean/non-boolean flag
  defaults, with historical and updated documentation.

Seven public issue/review comments were captured. Each records its URL, commenter,
last-updated timestamp, text and hash. Commenters are not automatically treated as
authoritative maintainers. Discussion supplies context, not proof of correctness.
These previously inspected PRs remain development/regression cases.

## Prepare another pair

Use the existing local Git caches. Create the output directory first and choose
new output filenames if these already exist:

```powershell
python -m docguard review-pack --manifest evaluations/upstream/click.toml --repository .docguard-upstream/click.git --case click_3239_authentic --paired-upstream --output packet.json
python -m docguard reference-labels packet.json --output reference-labels.json
python -m docguard review-ui packet.json --labels reference-labels.json --output review.html
```

Select one authentic/base-doc seed per pair. Pairing rejects unchanged selected
sections, duplicate seed pairs, authored-stale claims and dependency-ablation seeds.
The existing manual-review workflow still supports those other case types.

Optionally pass `--discussion comments.json` to `review-pack`. It accepts a JSON
array of GitHub issue/review comments containing `html_url`, `body`, `user.login`
and `updated_at`. URLs must belong to a selected PR. Collect from
`GET /repos/OWNER/REPO/issues/NUMBER/comments` and
`GET /repos/OWNER/REPO/pulls/NUMBER/comments`, follow pagination, and combine the
arrays. Preserve the original metadata. Empty arrays are valid. Packet preparation
does not fetch GitHub or silently update saved snapshots.

## Verify labels without blocking on outside reviewers

| Review level | Meaning |
| --- | --- |
| `upstream_reference` | Provisional expectation derived from the upstream change and input variant; not human-verified |
| `project_reviewed` | A named person, including you, verified the claim and available evidence |
| `independently_audited` | A named reviewer attests they did not author DocGuard's implementation, case or expected label |

`reference-labels` seeds `revise` for old docs and `unchanged` for updated docs.
**A changed section alone does not prove staleness.** Cosmetic edits, unrelated
changes, missing evidence and imperfect upstream fixes can invalidate those
expectations. No reviewer is invented; automatic labels stay explicitly provisional.

In the UI, inspect the supplied code, upstream correction and discussion. Confirm
or change the expected decisions, enter your name and rationale, then click
**Save judgment**. That promotes only that case to project-reviewed. Check the
independence box only when applicable; upstream project expertise is welcome.
Download JSON to keep your work. You may change a provisional label to
`needs_review` if the selected evidence is insufficient.

Experiments accept provisional labels, your verified labels, or a mixture with
independently audited cases. Reports separate decision metrics and coverage by
review level. Ask another developer to audit a subset and ambiguous cases rather
than blocking all development. Preserve earlier exports and disagreement notes;
automatic multi-reviewer adjudication is not implemented.

## Run the comparison

Preparation makes no API calls:

```powershell
python -m docguard evaluate-experiment packet.json --labels reference-labels.json --output preparation.json
```

To use the configured provider/model with bounded requests:

```powershell
python -m docguard evaluate-experiment packet.json --labels reference-labels.json --live --max-requests 5 --delay-seconds 65 --output live.json
```

Add `--resume` to continue the same report. Use your exported labels when available.
Changing labels requires a new report; previous results must not silently become
human-verified. See the [experiment guide](manual-benchmark-review.md) for the five
methods, shared-candidate validator, budgets and metrics.

Discussion is withheld by default. Run a **separate report** with
`--discussion-mode input` to test whether PR explanations help. That sends the
snapshot to each generating method and validator. The mode is bound into resume
identity, preventing accidental mixing. Check labels against the evidence available
in that mode, disclose added context/cost, and report modes separately. Comments
may contain solutions or quoted corrected docs: this is answer-bearing assistance,
not a code-only experiment. Reference sections stay separate in both modes.

## Compare repairs by meaning

```powershell
python -m docguard review-ui packet.json --report live.json --output repairs.html
```

The repair page shows the candidate alongside code, upstream update, documentation
diff and discussion. Rate support, completeness, preservation, style and acceptance.
The additional reference selector records **Consistent in meaning**, **Different
but valid correction**, **Substantive disagreement**, or **Not assessed**.
Explain disagreements in your notes. Different wording can be correct; the upstream
patch can also contain mistakes or irrelevant rewrites.

Export ratings and use `score-experiment` as described in the experiment guide.
It counts these human judgments separately from action agreement, acceptance and
validator errors. It does not use exact string matching or similarity as proof of
correctness. Independent audit coverage is reported separately.

For stronger public quality claims, audit a representative subset and ambiguous
cases, report disagreements, then freeze fresh grouped cases without tuning on
their outcomes. Broader review increases confidence; it need not block prototype
experiments or your own domain-informed verification.
