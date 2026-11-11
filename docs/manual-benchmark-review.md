# Review real PR evidence and measure DocGuard's contribution

The benchmark now has a standalone browser review page and an actual five-method
experiment runner. No server, frontend build, or API key is needed to review cases.
Start with [upstream-authored reference pairs](upstream-reference-benchmark.md):
provisional expectations, your verification, and independent audits of a subset.
This infrastructure does not establish an improvement by itself; model runs and
repair assessments are still needed, with review coverage disclosed.

## Start with five cases from three PRs

| PR | Cases in the starter packet | What to inspect |
| --- | --- | --- |
| [HTTPX #3378](https://github.com/encode/httpx/pull/3378) | `httpx_3378_authentic`, `httpx_3378_stale_claim` | Changes to the accepted method argument; compare the authentic documentation with a variant containing an explicitly authored byte-support claim. |
| [HTTPX #3364](https://github.com/encode/httpx/pull/3364) | `httpx_3364_dependency_ablation` | Query-parameter behavior when relevant helper implementations are deliberately withheld. Decide what the supplied evidence can actually establish. |
| [Click #3239](https://github.com/pallets/click/pull/3239) | `click_3239_authentic`, `click_3239_base_docs` | Flag default handling; compare the current section and its historical version against the pinned implementation. |

These are five variants, **not five distinct PRs**. The authored claim and omitted
dependencies are controlled experiments, not genuine mistakes attributed to an
upstream author. All are previously inspected regression/development cases. Click
#3239 is no longer reserved as held-out data. The packet deliberately excludes the
manifests' provisional expected answers and rationales.

From the repository root, using the existing local Git caches:

```powershell
python -m docguard review-pack --manifest evaluations/upstream/httpx.toml --repository .docguard-upstream/httpx-full.git --manifest evaluations/upstream/click.toml --repository .docguard-upstream/click.git --case httpx_3378_authentic --case httpx_3378_stale_claim --case httpx_3364_dependency_ablation --case click_3239_authentic --case click_3239_base_docs --output .docguard-demo-review/packet.json
python -m docguard review-ui .docguard-demo-review/packet.json --output .docguard-demo-review/review.html
Start-Process .docguard-demo-review/review.html
```

Create the output directory first on a fresh installation. Outputs refuse to
overwrite existing files; use a new name to regenerate a packet or page. If you
already have the generated page, open it directly. For a new checkout, follow
[upstream evaluation](upstream-evaluation.md) to populate the pinned Git caches.
Packet preparation reads committed blobs and parses source; it does not execute
the upstream application's code, install its dependencies, or contact the model.

## Step 1: label the expected decision before seeing model answers

1. Read the supplied document. Write down the specific claim being checked.
2. Follow **Original PR**, **Pinned code diff**, and **Exact upstream doc**. Use
   the pinned commit versions, not the repository's current default branch.
3. Inspect the before/after evidence, then switch between mapped entities and
   expanded dependencies. Labels must reflect the evidence actually available to
   that method. Finding a helper on GitHub does not make it available to the model.
4. Select each expected decision explicitly: **Revise** for a proven stale claim
   with a supported correction, **Unchanged** when the evidence supports the
   existing claims, or **Needs review** when necessary evidence is missing.
5. Record your name and a rationale citing evidence IDs or source lines. A useful
   rationale identifies the claim, the code establishing or contradicting it, and
   any limitation. Do not label from a PR title or a regex match alone.
6. Click **Save judgment**. Use **Skip for now** for unresolved cases; skipping
   does not count as approval. Download the JSON regularly, then save it as
   `.docguard-demo-review/review-labels.json`. Import restores a downloaded draft.

Your own review is valuable, but leave **Independent reviewer** unchecked if you
helped build the implementation, case, or label. Ask another developer to review
the packet separately. Resolve disagreements and keep both original assessments
and the adjudication notes. The tool records an independence attestation; it
cannot verify a person's identity or expertise.

Browser storage is only a convenience. Exported JSON is the portable record. The
page contains source evidence; share it only where you may share that source.
It makes no network requests. Clicking an explicit GitHub link opens GitHub.

## Step 2: run the comparison with bounded API usage

All cases require label records before running. These can be human judgments or
explicitly provisional expectations from `reference-labels` for eligible pairs.
A no-network preparation checks the packet and labels:

```powershell
python -m docguard evaluate-experiment .docguard-demo-review/packet.json --labels .docguard-demo-review/review-labels.json --output .docguard-demo-review/preparation.json
```

For a live run, the configured model and key come from the existing environment
configuration. Never put the key into the packet, HTML, or review JSON.

```powershell
python -m docguard evaluate-experiment .docguard-demo-review/packet.json --labels .docguard-demo-review/review-labels.json --live --provider groq --model openai/gpt-oss-120b --max-requests 5 --delay-seconds 65 --output .docguard-demo-review/experiment.json
```

Repeat the same command with `--resume` until completed. A budget stop is expected
with five calls; the command exits nonzero while any method remains incomplete.
Use a new filename when changing labels, packet, model, prompts, or pacing.
Preparation-only reports cannot be resumed as live reports. An output lock blocks
concurrent writers. If the process is forcibly killed, confirm it is no longer
running before removing its `.json.lock` file.

| Method | Input and behavior |
| --- | --- |
| Leave unchanged | No API call; retain the original document. |
| Simple LLM | Short prompt, document, and the same mapped source evidence; structured response checks. No DocGuard diagnostics or claim gate. |
| DocGuard mapped | Current production generation prompt, mapped context, explicit claim availability gate, response and citation validation. |
| DocGuard direct | Same prompt and checks, with existing bounded dependency retrieval. |
| DocGuard validated | Reuse the direct method's exact candidate, then ask the same model to check support, completeness, preservation, and style. Failed checks route to review. |

The fifth method allows the retrieval contribution and validator contribution to
be assessed separately. It does not generate another candidate: otherwise a better
or worse second generation could be confused with a validator effect. These are
evaluation-only decisions and candidates, not publishable proposal artifacts.
Production preview/apply/publication guards remain separately tested; this runner
does not exercise them or add the experimental validator to production publication.

Each ordinary case uses up to three generation calls and one validator call before
retries. Five cases therefore usually require at most 20 successful calls. Explicit
claim gates and model abstentions can reduce this count. Every API attempt consumes
the invocation budget, including retries. There is one bounded retry for HTTP 429;
Retry-After up to 60 seconds is respected, and longer/repeated limits stop the run.
The 65-second pacing default is configurable; it does not guarantee compliance
with every provider's daily or token quotas. A response received and checkpointed
is reused on resume. A crash before receiving/saving a response can require a new
request; API-side exactly-once execution is not promised.

The experiment records compacted input byte counts, output token allowances,
provider-reported token usage, per-attempt latency, errors, retries, and fingerprints
of the packet, labels, and prompts. The shared generation's usage and model time
are charged to the validator method when comparing effective cost. They are not
additional physical calls. p50/p95 describe physical API attempts, not end-to-end
user wait time. Output limits use the production document-size heuristic (2,048 to
12,000 tokens); evidence sizes differ by method and are disclosed. Unknown token
usage stays null. Dollar costs need a dated pricing calculation; none are inferred.

## Step 3: review outputs and score quality

After finishing the run, generate its output review page:

```powershell
python -m docguard review-ui .docguard-demo-review/packet.json --report .docguard-demo-review/experiment.json --output .docguard-demo-review/repairs.html
Start-Process .docguard-demo-review/repairs.html
```

Review the original evidence and proposed text. Choose Yes/No for factual support,
completeness, preservation, and style. Separately decide whether the **candidate
before validation** is acceptable and whether you accept the **final decision**.
For example, a good candidate rejected by the validator is an acceptable candidate
but an unnecessary final review routing. For an abstention without an edited
candidate, judge the displayed original text and final routing separately.

Candidates appear as A–E rather than method names. This reduces immediate brand
bias but is not a blinded study: order is fixed, findings can reveal the method,
and report metadata is available. Use separately randomized assignments and an
independent study administrator for a genuinely blinded human experiment.

Export the ratings as `.docguard-demo-review/repair-reviews.json`, then run:

```powershell
python -m docguard score-experiment .docguard-demo-review/experiment.json --reviews .docguard-demo-review/repair-reviews.json --output .docguard-demo-review/human-scores.json
```

The exact report hash binds ratings to the reviewed outputs. Resuming or modifying
that report requires a new review page. Never apply previous ratings silently.
Automatic metrics and explicit human judgments remain separate:

- **Completion coverage:** completed decisions / attempted case-method slots.
  Errors, refusals, and budget stops remain visible, not correct abstentions.
- **Unnecessary edits:** predicted revise / human-labeled unchanged cases.
- **Missed edits:** predicted unchanged or review / human-labeled revise cases.
- **Appropriate abstention:** predicted review / human-labeled insufficient-evidence
  cases. Review routing is also reported across all completed cases.
- **Human acceptance:** approved final decisions / reviewed decisions; repair
  candidate acceptance is reported separately for initially proposed edits.
- **Validator errors:** bad candidates caught and good candidates rejected,
  measured against explicit human candidate-quality judgments.

Every rate includes numerator and denominator; an empty denominator is null.
Compare both completion coverage and the intersection of cases completed by all
methods. Partial runs otherwise favor methods that completed easier cases.
Expected actions are conditional on each evidence policy: report label differences
alongside scores, because expanded evidence can legitimately change the right
decision. Automatic action agreement does not establish semantic correctness.

## Advance from practice to credible release evidence

The 30 pinned entries in `evaluations/candidates/` are an intake queue, not reviewed
benchmark cases. Use [benchmark intake](benchmark-intake.md) to admit new PRs in
small batches. Include code-only stale-doc changes as well as PRs that fixed their
own documentation. Keep all variants and related changes in one split. The current
packet builder conservatively marks every generated packet as regression data;
it does not certify held-out status. A future independently administered held-out
release needs an explicit exposure record, frozen cohort and reviewer provenance.

Current packet limitations: selected Python files and one impacted Markdown
document per case; no automatic evaluation of genuine zero-impact cases; no
automatic retrieval outside the selected upstream files; no multiple-rater
aggregation/adjudication, confidence intervals, or time-saved study yet.

For stronger reliability claims, audit a representative subset and ambiguous cases,
disclose review coverage, freeze fresh groups, run repeated comparisons with fixed
budgets, and publish case outcomes and uncertainty. Development experiments can
use provisional or project-reviewed labels. Test installation with another developer.
Then complete the license, version/tag, hosted release workflow, and registry
configuration described in [distribution](distribution.md). An installable alpha
and an independently validated product are different release claims.

## Run the implementation checks

```powershell
python -m pytest tests/code/test_experiments.py tests/code/test_groq_provider.py -v
python -m pip install -e ".[browser-test]"
python -m playwright install chromium
$env:DOCGUARD_BROWSER_TESTS = "1"
python -m pytest tests/code/test_experiments.py -k browser -v
```

To use an already installed Edge instead of downloading Chromium, set
`$env:DOCGUARD_BROWSER_CHANNEL = "msedge"`. The browser test uses synthetic fixtures,
exports/imports labels, assesses a candidate, scores the downloaded ratings, and
checks that source text cannot execute as HTML. It makes no paid model calls.
