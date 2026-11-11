# Live upstream-reference pilot: 2026-11-10

DocGuard generated documentation from code and input documentation, then compared
the output with the repository's actual documentation correction. No manual labels
or external reviewer were required. Upstream corrections and PR discussion were
withheld from generation. A separate call to the same model judged semantic
agreement; exact matches needed no judge call.

Provider: Groq. Generator and judge: `openai/gpt-oss-120b`.
This is a development pilot with two previously inspected PRs and four variants,
not a held-out benchmark or independently verified accuracy measurement.

## Results

| PR and input | Generated action | Comparison result |
| --- | --- | --- |
| HTTPX #1573, old documentation | Revise | Same direction, incomplete: describes the deprecation but omits planned removal in HTTPX 1.0. |
| HTTPX #1573, updated documentation | Unchanged | Aligned: exact reference match. |
| Click #3239, old documentation | Revise | Unscored: judge supplied noncontiguous quotations, including after one validation retry. |
| Click #3239, updated documentation | Unchanged | Aligned: exact reference match. |

- Assessment coverage: **3/4 (75%)**.
- Directional agreement among completed assessments: **3/3**.
- Complete reference agreement among completed assessments: **2/3 (66.7%)**.
- End-to-end complete agreement across selected cases: **2/4 (50%)**.
- Updated-document controls: **2/2 aligned**.
- Old-document repairs: **0 aligned, 1 needs revision, 1 assessment error**.

The aggregate agreement includes the two unchanged controls; it must not be
presented as repair accuracy. The HTTPX omission may indicate missing roadmap
context, rather than a false statement in the generated text. The Click error
does not establish that its repair is wrong: the assessment failed validation.
Both rejected judge responses remain in the report instead of being counted as
successful assessments. No further retries were made.

## Pinned inputs

| Repository / PR | Base commit | Head commit |
| --- | --- | --- |
| HTTPX #1573 | `073a3284abbcecad68033053acf595ff749800a7` | `963d2984be4963257cb53c3f14797caf33a0c4ea` |
| Click #3239 | `60cad4ad6583bf885c62d6f4597f3555d1ee1a0f` | `a683017931b5bcb211e18685fa623e968727aa3b` |

Local packet: `.docguard-demo-upstream-reference/packet.json`.
Local reports: `.docguard-demo-reference-live/comparison.html` and
`comparison.json`, with original model outputs in `generation.json`.
`comparison-first-pass.json` preserves the result before the validation retry.
These generated artifacts are ignored by Git; this note records the pilot outcome.

## Requests and reproducibility

Seven API attempts: four generations and three judge requests, including the
single validation retry. There were no HTTP errors or rate-limit responses.
Requests were paced at 65 seconds. Reported usage was 46,194 input tokens and
6,613 output tokens (52,807 total). Summed request time was 23.131 seconds;
this excludes pacing and is not end-to-end runtime.

```powershell
python -m docguard evaluate-reference .docguard-demo-upstream-reference/packet.json --live --max-requests 8 --delay-seconds 65 --output-dir .docguard-demo-reference-live
python -m docguard evaluate-reference .docguard-demo-upstream-reference/packet.json --live --resume --retry-judge-errors --max-requests 2 --delay-seconds 65 --output-dir .docguard-demo-reference-live
Start-Process .docguard-demo-reference-live/comparison.html
```

Use a new output directory for an independent rerun. A live run returns exit code
1 when any case disagrees, fails, or remains incomplete.

## Validation and next work

The affected experiment/provider suite passed 66 tests and 10 subtests, including
browser tests. After adding bounded invalid-response retries, targeted reference
tests passed 14 tests with one browser test skipped. Ruff and mypy passed.

Next, improve the judge's structured quotation format and test it on new cases;
retain this pilot as the baseline rather than replacing its failures. Expand to
more distinct, pinned PRs and repeat runs, reporting repair and unchanged-control
results separately. This workflow needs no human input, but agreement with an
upstream reference and a same-model judge remains an automated measurement.

See [the automatic evaluation guide](automatic-reference-evaluation.md) for the
workflow, metrics and resume behavior.
