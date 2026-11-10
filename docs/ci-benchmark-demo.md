# Proving value and integrating DocGuard into CI

Use **both** a controlled application demo and pinned real PR cases. They answer
different questions. A demo proves installation, workflow routing and publication.
Real cases test whether the decisions and edits are useful beyond the demo. Neither
automatically establishes human acceptance or developer time saved.

## Hosted evidence already available

[DocGuard CI run 42693012315](https://github.com/smaoui-me/docguard/actions/runs/42693012315)
completed successfully for commit `c7c4269529381645ba813d0e4b9ee53750235eb2`:

| Hosted job | Result | Job duration |
| --- | --- | --- |
| Ubuntu, Python 3.11 | Success | 48 seconds |
| Ubuntu, Python 3.14 | Success | 36 seconds |
| Windows, Python 3.11 | Success | 245 seconds |
| Windows, Python 3.14 | Success | 226 seconds |

These are job durations, including setup and checks, not model latency. This verifies
DocGuard's own CI and the Linux package smoke test. It does not yet verify a generated
documentation PR in a different repository or an independent developer's installation.

## Create a disposable application repository

The generator builds a separate Git repository without copying DocGuard's source or
credentials. Its workflows fetch the public tool at the reviewed commit above.

```powershell
.venv\Scripts\python.exe examples/create_ci_demo.py --output .docguard-demo-my-ci
```

It creates `main` plus four scenario branches:

| Branch | Application tests | Documentation expectation |
| --- | --- | --- |
| `scenario/stale` | Pass | `total` now multiplies by 1.2; the old claim needs repair |
| `scenario/already-correct` | Pass | Code and documentation were both updated; leave docs unchanged |
| `scenario/missing-evidence` | Pass | Explicitly required external source is unavailable; route to review without AI |
| `scenario/no-impact` | Pass | Comment/line movement only; no proposal needed |

This deliberately shows why passing application tests alone does not validate
documentation. The missing-evidence case uses `math.ceil`; its source is outside the
repository. An explicit requirement asks for that unavailable source. This is a
controlled gate test, not evidence that a model cannot understand the standard library.

The existing local `.docguard-demo-ci` was created and its four branches tested. It
has no remote, and no demo PR has been opened. For a fresh trial, create an empty
repository in your GitHub account, then substitute its actual URL below:

```powershell
git -C .docguard-demo-my-ci remote add origin https://github.com/OWNER/docguard-demo.git
git -C .docguard-demo-my-ci push -u origin main
git -C .docguard-demo-my-ci push origin scenario/stale scenario/already-correct scenario/missing-evidence scenario/no-impact
```

Open each scenario branch as a PR against `main`. Do not open these demonstration
PRs in HTTPX or Click. For third-party repositories, evaluate downloaded immutable
history locally; only integrate a workflow into repositories you control or have
permission to modify.

## The runner and pipeline

A **runner** is the machine executing a CI job. `runs-on: ubuntu-latest` selects a
GitHub-hosted machine; GitHub provisions it for the job and decommissions it afterward.
No Docker installation, server, or self-hosted runner registration is required for
this trial. [GitHub runner documentation](https://docs.github.com/en/actions/how-tos/manage-runners/github-hosted-runners/use-github-hosted-runners).

The generated application has three workflows:

1. **Demo application CI:** runs its unit tests on pushes and PRs, with no API secret.
2. **DocGuard documentation review:** examines the PR's Git changes and mapping,
   then uploads an advisory report. The trusted tool and proposed source are checked
   out separately. Proposed source is parsed as data by DocGuard.
3. **DocGuard controlled repair:** manually triggered for a specific source PR.
   It saves request/proposal artifacts; optional publication is a separate job.

Configure the demo in this order:

1. Confirm application and advisory jobs finish for all four PRs.
2. Dispatch controlled repair with the stale PR number, `docs/prices.md`, and both
   live/publish disabled. Inspect the saved source evidence and selected section.
3. Add `GROQ_API_KEY` in the **demo repository's Actions secrets**, then rerun with
   live enabled and publish disabled. Inspect the generated wording and diff.
4. Configure environment `docguard-publish` with required reviewers and allow workflow
   tokens to create PRs in repository settings. Required reviewers depend on GitHub
   visibility/plan; if unavailable, keep hosted publication disabled and explicitly
   publish locally after review. An environment name by itself is not approval.
5. Request publication, review the artifact, and approve the job. Expect a draft
   targeting the original source PR branch, so merging it adds documentation to that
   feature change. Rerun **the same publication job/artifact** and verify draft reuse.
6. Advance the source branch and try the old artifact; expect stale-head rejection.
   Keep screenshots/links for the acceptance record.

The demo pins DocGuard itself. Before a release, also pin third-party Actions to
reviewed immutable commits. Keep live benchmarks separate from required application
checks; provider quotas and model variability should not silently control deployment.
Self-hosted runners are unnecessary here and require extra isolation for untrusted
PR code. [GitHub runner security guidance](https://docs.github.com/en/actions/reference/security/secure-use).

## Benchmark runner: real PRs and explicit baselines

`examples/run_pilot.py` orchestrates the existing immutable HTTPX/Click manifests.
It treats upstream repositories as data and never installs or runs their code.
Use the existing caches, or acquire them explicitly:

```powershell
git clone --bare https://github.com/encode/httpx.git .docguard-upstream/httpx-full.git
git clone --bare https://github.com/pallets/click.git .docguard-upstream/click.git
```

Skip cloning a path that already exists. The manifests, rather than moving branches,
select the exact commits and files. Start with preparation only:

```powershell
.venv\Scripts\python.exe examples/run_pilot.py --output .docguard-demo-pilot-check
```

For a live run using your local `.env`:

```powershell
.venv\Scripts\python.exe examples/run_pilot.py --live --max-requests 3 --delay-seconds 65 --output .docguard-demo-pilot-my-live
```

The three-request budget intentionally may leave cases unrun; they remain visible
in coverage. Resume the same compatible selection/configuration:

```powershell
.venv\Scripts\python.exe examples/run_pilot.py --live --resume --max-requests 3 --delay-seconds 65 --output .docguard-demo-pilot-my-live
```

Budgets reset per invocation, including retries. A failed 429/credential response
stops the invocation. Every case has a checkpoint, and completed responses are not
requested again. An interrupted in-flight provider request may already have been
billed; exact-once billing is not guaranteed. A process killed before cleanup may
leave `pilot.lock`: remove it only after verifying no run remains active.

Read `summary.md`, `report.json`, and individual case reports inside the output
directory. The summary compares DocGuard with two explicit policies on the **same
completed cases**: leave documentation unchanged, and route every change to review.
It shows action agreement, missed edits, unnecessary edits and appropriate abstention.
Coverage includes errors/unrun cases. Contract-assisted variants are separate from
unassisted decisions. The baselines do not generate repairs; action agreement is not
a complete quality measure and does not imply all revised prose is true.

Use `python -m docguard summarize-evaluation OUTPUT/report.json --output operations.json`
for attempt latency, token usage, retries and failure summaries. Use the existing
human-review forms on the per-case evaluation reports for actual acceptance ratings.

`.github/workflows/benchmark.yml` makes the same experiment manually runnable on a
hosted Ubuntu runner, with bounded requests, pacing, a step summary, and artifacts
uploaded even when a case fails. It defaults to preparation only.
Choose the focused five-variant selection (default, six-request
ceiling) or all pilot cases (increase the budget deliberately for a full live run).
It does not run on every application PR or publish documentation. After committing/pushing that workflow,
dispatch it from GitHub Actions. Hosted runs start fresh; download artifacts to resume
locally, or explicitly implement cross-run artifact restoration before assuming that
rerunning an entire hosted job reuses earlier responses.

The private `smaoui-me/docguard-demo` trial is now created. See
[the hosted trial record](hosted-trial-20261109.md) for actual PRs, run links,
observed refusals, and unfinished acceptance checks.

## What would substantiate the value claim?

Current real cases are provisional, inspected regression examples. They can expose
failures and demonstrate selective behavior; they cannot establish broad reliability.
Promote candidates only after independent label/evidence review. Keep related PRs
in one split and freeze a new held-out set before further prompt tuning.

For a stronger experiment, give independent reviewers comparable tasks with and
without DocGuard, counterbalance task order, and record actual accepted edits,
unsupported claims, review time and corrections. Record refusals and provider errors
too. Do not turn fewer review routes into invented minutes saved. Publish all outcomes,
denominators, selected cases, model/prompt versions and limitations alongside the demo.
