# Release acceptance and demo plan

The current deliverable is a tested repair prototype with a controlled publication
path. It is not yet an externally validated production service. Use acceptance
evidence rather than a completion percentage.

## CI/CD rollout

Three workflows have different responsibilities:

| Workflow | Trigger | What it does | Credentials |
| --- | --- | --- | --- |
| `ci.yml` | PRs, pushes to master/main, manual | Offline tests, Ruff, mypy on Linux/Windows and Python 3.11/3.14; one isolated wheel-install check | Read-only repository token; no AI secrets |
| `docguard-review.yml` | PRs | Deterministic documentation impact analysis and advisory artifacts | Read-only repository token |
| `docguard-repair.yml` | Manual dispatch | Optional bounded AI analysis, then optional draft publication for an applicable revision | AI key in analysis; write token only in publication job |

The [first hosted CI run](https://github.com/smaoui-me/docguard/actions/runs/42693012315)
passed all four matrix jobs for commit `c7c4269`. Keep checking subsequent commits
before making their named checks required in a branch ruleset. Keep the documentation
review advisory until mappings have been checked against real changes.

Use [the CI demo and comparative benchmark guide](ci-benchmark-demo.md) for a
separate application repository, scenario branches, runner setup and real-PR metrics.

For repairs, follow [targeted-repair.md](targeted-repair.md): start with live and
publish disabled, inspect the saved request, then enable live analysis only. Add the
Groq key in GitHub Actions secrets, never in committed configuration. Configure the
`docguard-publish` environment with required reviewers before requesting publication.
Naming that environment in YAML alone does not enforce approval. If required reviewers
are unavailable for your repository/plan, leave workflow publication disabled and
use the explicit local publishing command after review.

The manual workflow must be present on the default branch for GitHub to receive its
dispatch event. See [GitHub workflow triggers](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow)
and [deployment review](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/review-deployments).
Initial publication trials should use a disposable repository with the trusted tool
and workflows installed; the current workflow expects that same-repository layout.
For another application's repository, reference the reusable analysis action at a
reviewed immutable DocGuard commit and adapt the trusted-tool checkout for publication.

Run live benchmarks separately from ordinary PR CI, with pinned datasets, explicit
request/retry budgets and checkpoint artifacts. Do not make a stochastic AI score
the sole merge gate. Release tags and package publication remain a later explicit
step after the hosted and independent-review acceptance gates below are met.

## External installation trial (pending)

The author-operated private demo now has [a hosted trial record](hosted-trial-20261109.md).
This does not satisfy the independent installation trial below.

Ask another developer to use a new environment and a disposable GitHub repository.
Give them this document and the README, without walking them through undocumented
steps. Record their actual feedback; do not prefill a successful result.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -e ".[dev]"
.venv\Scripts\docguard.exe --help
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe examples/section_demo.py --output .docguard-demo-install-trial
```

For a wheel installation instead of a checkout, build with `python -m pip wheel .
--no-deps --wheel-dir dist`, then install the resulting wheel in a clean virtual
environment. Example scripts and benchmark source files belong to the repository;
the installed CLI is the wheel's entry point. No published package/release is implied.

Trial record:

| Field | Result |
| --- | --- |
| Tester and date | Pending |
| OS and Python version | Pending |
| DocGuard commit/wheel hash | Pending |
| Fresh installation and CLI help | Pending |
| Offline supported repair | Pending |
| Missing-evidence route, zero AI calls | Pending |
| Protected publication environment configured | Pending |
| Hosted analysis artifact inspected | Pending |
| One live draft PR created in disposable repository | Pending |
| Publication rerun reused the same draft | Pending |
| Changed source head rejected | Pending |
| Fork/closed PR outcome understood | Pending |
| Confusing steps, errors and time to first useful result | Pending |

Use [targeted-repair.md](targeted-repair.md) for the workflow and token setup.
No hosted PR was created during automated development tests. GitHub environment
approval settings must be configured and verified separately from committing YAML.

## Three-minute demo video

1. **0:00–0:25 — Problem.** Show `total(price)` changing from returning `price` to
   `price * 1.2`, with the prices documentation still claiming unchanged behavior.
2. **0:25–1:05 — Evidence and proposed repair.** Run the section demo, identify the
   before/after source citations in `proposal.json`, then show the small diff.
   State whether the run is live AI, a recorded live run, or an offline fixture.
3. **1:05–1:35 — Control.** Show the unchanged support section and byte-preservation
   check. Show the stale reapplication failure. Explain why generation alone never
   changes a repository document.
4. **1:35–2:00 — Abstention.** Run the claims demo and show the exact missing helper
   requirement. Explain that this gate blocks the model call but does not establish
   truth when evidence is available.
5. **2:00–2:30 — GitHub integration.** After the hosted trial succeeds, show the
   approved publication job, its draft and reuse on rerun. Until then, show the
   local preview and explicitly say hosted publication is pending verification.
6. **2:30–3:00 — Honest results.** Show the five-PR pilot, its failures, the single
   live section smoke test, and the thirty pending candidates. Explain the difference
   between enforcement tests, model action accuracy and independent human acceptance.

## Remaining release gates

- Complete the hosted installation trial and fix its friction.
- Obtain independent labels and output reviews, then freeze a fresh held-out set.
- Repeat bounded live evaluations against unchanged labels and report all runs.
- Verify CI on Linux/Python 3.11 as well as the locally tested Windows/Python 3.14.
- Pin third-party GitHub Actions to reviewed immutable commits for a release.
- Tag a reviewed release commit and document the supported installation/version.
- Establish operating budgets, artifact retention and who handles review failures.

Additional languages, automated link discovery, a browser UI and embeddings remain
separate product/research milestones. They should follow measured failures and user
needs, not replace the acceptance work above.
