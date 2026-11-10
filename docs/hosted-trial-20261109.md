# Private hosted acceptance trial — 2026-11-09

Repository: https://github.com/smaoui-me/docguard-demo (private).
The application is synthetic; these checks validate integration, not model accuracy.
The trusted DocGuard checkout is pinned to
`c7c4269529381645ba813d0e4b9ee53750235eb2`.

## Scenarios and observed results

| Scenario | PR | Hosted outcome |
| --- | --- | --- |
| Stale documentation | [1](https://github.com/smaoui-me/docguard-demo/pull/1) | Hosted live analysis succeeded; reviewed repair published as draft #5 |
| Already-correct documentation | [2](https://github.com/smaoui-me/docguard-demo/pull/2) | Created; hosted AI decision not yet tested |
| Missing evidence | [3](https://github.com/smaoui-me/docguard-demo/pull/3) | Live-mode gate returned `needs_review` without invoking AI |
| Comment-only change | [4](https://github.com/smaoui-me/docguard-demo/pull/4) | Deterministic review succeeded with zero affected documents; explicit repair selection rejected |

Evidence:

- [Stale preparation run](https://github.com/smaoui-me/docguard-demo/actions/runs/42707307592): succeeded, publication skipped.
- [Application CI manual run](https://github.com/smaoui-me/docguard-demo/actions/runs/42707856830): succeeded on `main`, verifying the application's unittest suite on the hosted runner.
- [Missing-evidence run](https://github.com/smaoui-me/docguard-demo/actions/runs/42707313065): succeeded, publication skipped. Downloaded artifact confirms `missing evidence=after:math.py:ceil`, null content, and generation skipped.
- [No-impact refusal run](https://github.com/smaoui-me/docguard-demo/actions/runs/42707317892): failed with exit 2, `Selected document is not flagged for review`. This verifies rejection, **not** a successful no-op workflow. No artifact was uploaded by this failed run.

These runs used the initial scenario commits. Later empty commits deliberately
tested automatic event triggering; they did not change application behavior.

## Runner and permissions

Manual analysis ran on GitHub-hosted `ubuntu-latest` with Python 3.11. No self-hosted
runner installation was needed. After explicit user approval, the local Groq key
was encrypted with the repository public key and uploaded as `GROQ_API_KEY`.
One hosted live generation ran with `openai/gpt-oss-120b`. Repository default token
permissions remain read-only. The `docguard-publish` environment does not exist;
hosted publication stayed disabled. The reviewed artifact was published through
the explicit local publisher. No PR was merged.

## Live repair and publication follow-up

- [Hosted live generation](https://github.com/smaoui-me/docguard-demo/actions/runs/42724307143) succeeded. The exact diff replaced `returns price unchanged` with `returns price multiplied by 1.2`; the Support section remained unchanged.
- Local preview validated the artifact, source evidence and section scope before publication.
- [Draft repair #5](https://github.com/smaoui-me/docguard-demo/pull/5) targets `scenario/stale`. First publication returned `reused=false`; the identical artifact returned the same URL with `reused=true` on a second call.
- An empty commit then advanced the remote source branch. With the local checkout still pinned to the old source, publication was rejected with `Source PR head changed; regenerate before publication`. Draft #5 is intentionally based on that previous head; regenerate before further publication.
- Manual deterministic review artifacts were downloaded and inspected: [stale](https://github.com/smaoui-me/docguard-demo/actions/runs/42724397928) and [missing evidence](https://github.com/smaoui-me/docguard-demo/actions/runs/42724401931) each flagged one document; [no impact](https://github.com/smaoui-me/docguard-demo/actions/runs/42724406127) flagged zero. All three runs succeeded.
- Focused local validation: 21 demo/publication tests passed; Ruff and `git diff --check` passed.

Automatic push/PR runs were absent when inspected, including after fresh empty
commits on all four scenario branches. Their cause remains unresolved. Manual
workflow dispatch works. The application workflow now also permits manual dispatch
to separate application-runner verification from event-trigger verification.
The documentation-review workflow also accepts a manual `source_pr` input, resolves
and validates an open PR's commit SHAs, and runs the same advisory analysis. This
fallback is verified; it is not a fix for automatic event delivery. Actions is
enabled and no workflow branch/path filters explain the missing runs. The cause
remains unproven; do not claim `GITHUB_TOKEN` suppression without identifying the
actual credential mechanism.

## Remaining acceptance work

### Additional protection and trigger diagnostics

The repair workflow now checks for a configured `required_reviewers` rule with
at least one reviewer before any analysis when publication is requested. Missing
or unreadable environment configuration fails the job before AI generation. This
was pushed to the demo as `62b3bad`. Four local tests execute the protection check
against absent rules, timer-only rules, empty reviewers, and configured reviewers.

[Diagnostic PR #6](https://github.com/smaoui-me/docguard-demo/pull/6) was created
from a GitHub Contents API commit to test a second event-delivery path. Its automatic
check results have not yet been inspected; no success is claimed.

The user explicitly authorized enabling Actions PR creation while keeping default
token permissions read-only, and an owner-reviewed publication environment allowing
self-review of manually started runs. Those settings have **not** been changed:
the subsequent automatic approval review hit a usage limit. The hosted rejection
test was not dispatched either. This is an execution blocker, not an unsafe-action
finding. The approval remains valid for a later continuation.

GitHub's [environment documentation](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)
states that Free accounts cannot configure private-repository environments, and
required reviewers on Free/Pro/Team are limited to public repositories. The private
demo must not silently remove its approval gate to work around that restriction.
Choose a separately authorized public synthetic demo or a plan supporting the
required protection; otherwise retain reviewed local publication.

1. Resolve automatic push/PR triggering and inspect documentation-review artifacts.
2. Exercise the already-correct case in a bounded hosted live trial.
3. Configure required reviewers
   on `docguard-publish` if supported; otherwise keep hosted publication disabled
   and use the explicit local publication path after review.
4. Verify the protected hosted publication job separately; local publication,
   identical-artifact reuse, and remote stale-source rejection are now verified.
5. Have another developer independently install and use the project.

See [pilot-value-20261109.md](pilot-value-20261109.md) for the separate real-PR
pilot measurements and their limitations. Successful synthetic integration checks
do not make that provisional pilot an independently reviewed benchmark.
