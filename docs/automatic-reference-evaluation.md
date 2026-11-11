# Automatic evaluation against repository documentation

This workflow uses the repository's actual documentation correction as the target.
It requires no manual labels, outside reviewer, or exported review form.

See the [recorded live pilot](reference-evaluation-20261110.md) for actual outputs,
agreement metrics, request usage and retained assessment failures.

1. Prepare paired upstream cases with `review-pack --paired-upstream`.
2. Generate a DocGuard output from the code and input document. The upstream
   correction and PR discussion are withheld from this generation.
3. Compare the generated document with the actual upstream corrected section.
4. If the texts match exactly, record reference agreement without another call.
5. Otherwise, ask an LLM judge to compare meaning using both documents, the
   upstream doc diff, original document and selected source evidence.

The judge checks direction, coverage of the correction, contradictions, unsupported
additions and preservation of still-valid text. Similar vocabulary alone is not a
pass. It supplies an explanation and exact quotes from both documents; invented
quotes or invalid responses are evaluation errors. Different wording can pass.

The final outcome is **aligned** or **needs_revision**. Generation abstentions
count as needing revision because no document correction was produced. Request
errors, refusals and invalid responses remain visible and reduce completion
coverage; they are not silently counted as semantic disagreements or successes.

## Run the prepared PR cases

On a fresh checkout, prepare a pair without relying on the author's local demo
files. Run from the DocGuard repository after installation:

```powershell
git clone --bare https://github.com/pallets/click.git .docguard-upstream/click.git
python -m docguard review-pack --manifest evaluations/upstream/click.toml --repository .docguard-upstream/click.git --case click_3239_authentic --paired-upstream --output packet-click.json
python -m docguard evaluate-reference packet-click.json --live --max-requests 5 --delay-seconds 65 --output-dir .docguard-demo-click-reference
Start-Process .docguard-demo-click-reference/comparison.html
```

Skip cloning if that cache already exists. Activate your virtual environment first
or use its Python executable explicitly. The manifest pins the two commits; fetched
source is never executed. This produces two Click variants, not the four-case
recorded pilot below. Preparation needs Git/network access; only `--live` uses an
API key. Choose new packet/output paths for a fresh run.

The starter packet contains four cases from HTTPX #1573 and Click #3239: old-doc
repair cases and updated-doc controls for each PR. Your configured provider and
model are loaded through the existing environment configuration.

```powershell
python -m docguard evaluate-reference .docguard-demo-upstream-reference/packet.json --live --max-requests 8 --delay-seconds 65 --output-dir .docguard-demo-reference-live
```

For a new trial choose a new output directory. To continue a budget-limited or
interrupted trial, repeat the command with `--resume`. Requests already received
and checkpointed are reused. A changed packet/model/prompt/pacing configuration or
changed frozen generation report is rejected. After forcibly killing a process,
verify that it has stopped before removing a leftover lock file.

Use `--resume --retry-judge-errors` to retry an invalid judge response once per
case. The rejected response remains in the JSON history, and the retry receives
formatting feedback and consumes the request budget. A second invalid response
remains an evaluation error rather than being silently accepted.

Omit `--live` to prepare without API calls. Preparation-only output cannot be
resumed as live output; start a new directory. The command returns 1 for a live
run with disagreement, errors, or incomplete cases, and 0 when every case aligns.

The eight-attempt limit is shared between generation and judging, including retries.
Four cases ordinarily use four generation calls and up to four judge calls. Exact
matches and generation abstentions avoid judge calls. The default pacing is 65
seconds. There is one bounded HTTP 429 retry; long/repeated rate limits stop for
resume rather than retrying indefinitely. This does not guarantee daily quota
availability. Generation and judge usage/latency are retained in their reports.

## Read the comparison

```powershell
Start-Process .docguard-demo-reference-live/comparison.html
```

The report is generated automatically. It displays each LLM output beside the
upstream document, with the outcome, rationale, original section, upstream diff,
and judge details. There are no rating buttons or manual assessment steps.

Files in the output directory:

- `comparison.html`: readable comparisons and metrics.
- `comparison.json`: raw outcomes, judge responses, request attempts, provenance
  hashes, model/prompt identity and limitations.
- `generation.json`: original model outputs, citations, usage and generation errors.
- `reference-labels.json`: automatically derived expectations used by the generation
  harness; these are never human-reviewed labels and do not decide semantic scores.

Metrics show evaluated/total coverage, aligned and needs-revision counts,
directional agreement, complete reference agreement among evaluated cases, and end-to-end agreement across all
selected cases. Old-doc repairs and updated-doc controls are reported separately.
Four variants from two PRs remain **two distinct PRs**, not four independent PRs.

Directional agreement can be positive while complete agreement fails: for example,
a candidate may describe a deprecation warning but omit the reference's planned
removal version. This difference can reveal missing context rather than a false
claim in the generated text. Preserve the explanation when interpreting scores.

## Interpreting the result

This is an **automated, repository-reference benchmark**. An upstream correction
is an externally authored target. The result does not establish independently
verified factual accuracy: an upstream patch can be imperfect, and a judge can
misclassify semantic agreement. Generation and judging currently use the same
configured model in separate calls; the judge sees the candidate and reference
but not the generator's hidden reasoning. Correlated model errors remain possible.

The existing pilot PRs were previously inspected during development, so results
are regression/pilot measurements rather than fresh held-out generalization.
No human input is required to run this workflow. Expand to more distinct pinned
PRs and repeated trials to assess consistency, retaining all failures and showing
coverage alongside agreement. Do not rename the agreement score simply "accuracy"
without specifying the reference and automated judge.
