# Public hosted acceptance — November 9, 2026

[docguard-public-demo](https://github.com/smaoui-me/docguard-public-demo) is a
fresh public repository containing only generated synthetic application code.
It demonstrates integration behavior, not independent benchmark accuracy.
The existing private demo was not made public.

## Provenance and configuration

The demo was generated with `examples/create_ci_demo.py`. All 17 historical
file blobs across five branches were checked against locally configured secret
values; no matches or committed `.env` files were found. This limited check is
not a general-purpose secret scanner. The history contains ten distinct paths:
application, test, Markdown, mapping, attributes, ignore rules and three workflows.

Trusted DocGuard source is pinned to
`c7c4269529381645ba813d0e4b9ee53750235eb2`; workflow templates include the later
manual-review fallback and reviewer-protection preflight. GitHub-hosted Ubuntu
runners use Python 3.11. Actions token defaults remain read-only; only the
publication job requests contents and PR write permissions. The repository allows
Actions PR creation. `GROQ_API_KEY` was uploaded encrypted after explicit approval.

The `docguard-publish` environment has `smaoui-me` as a required reviewer.
Self-review is allowed so the owner can approve their own manual demo runs.
This demonstrates a human gate, **not independent two-person approval**.

## Observed acceptance evidence

Five push-triggered application runs and eight PR-triggered application/review
runs completed successfully. The runs are visible in the
[Actions history](https://github.com/smaoui-me/docguard-public-demo/actions).
Automatic events are now verified in this repository; this does not explain the
private repository's previously absent automatic runs.

| Case | PR | Expected behavior |
| --- | --- | --- |
| Stale claim | [1](https://github.com/smaoui-me/docguard-public-demo/pull/1) | Propose multiplier correction and wait for approval |
| Already correct | [2](https://github.com/smaoui-me/docguard-public-demo/pull/2) | Leave documentation unchanged |
| Missing dependency evidence | [3](https://github.com/smaoui-me/docguard-public-demo/pull/3) | Route to review without AI generation |
| Comment-only change | [4](https://github.com/smaoui-me/docguard-public-demo/pull/4) | Deterministic review without a required repair |

[Protected live run 42763114006](https://github.com/smaoui-me/docguard-public-demo/actions/runs/42763114006)
completed analysis successfully and entered `waiting` for publication. The pending
deployment API confirmed the required reviewer. Its downloaded proposal changed
only `returns price unchanged` to `returns price multiplied by 1.2`. The Support
section was checked unchanged. No hosted draft publication is claimed yet.

Two further analysis-only runs completed successfully and their downloaded artifacts
matched the expected decisions:

- [Already correct, run 42763200329](https://github.com/smaoui-me/docguard-public-demo/actions/runs/42763200329): `unchanged`, null replacement content, no warnings.
- [Missing evidence, run 42763204134](https://github.com/smaoui-me/docguard-public-demo/actions/runs/42763204134): `needs_review`, null replacement content, missing `after:math.py:ceil`; AI generation skipped.

This trial used two model-generation requests in total (stale and already correct).
Five focused local demo/protection tests passed before upload. The existing local
publication and rerun checks remain documented in the private trial record; they
are not relabeled as hosted publication results.

The owner should inspect the artifact and use **Review deployments**, select
`docguard-publish`, and approve only if the proposed change is acceptable. The
assistant does not approve this human-review step on the owner's behalf.

## Remaining acceptance gates

1. Observe hosted publication after human approval; inspect its one-file draft diff.
2. Rerun only the publish job using the same artifact and verify draft reuse.
3. Verify hosted stale-source rejection; retain the earlier successful local
   publication/stale-source tests as separate evidence.
4. Independently review benchmark labels and freeze a held-out split before tuning.
5. Obtain another developer's installation trial and actual repair-acceptance ratings.

Synthetic CI success is not evidence of broad semantic correctness or time saved.
See [the measured pilot](pilot-value-20261109.md) for its denominators and limitations.
