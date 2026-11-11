# Integrating DocGuard into CI/CD

DocGuard runs alongside application tests. First use deterministic impact review
to identify documentation that might need attention. A maintainer can then request
AI analysis and inspect a proposal. Publishing that proposal is a separate step.
The [README diagrams](../README.md#how-it-works) show the data flow.

## GitHub: implemented workflows

| File | Purpose |
| --- | --- |
| [ci.yml](../.github/workflows/ci.yml) | Test DocGuard itself on Windows/Linux; lint, types, offline tests and review UI browser checks. |
| [docguard-review.yml](../.github/workflows/docguard-review.yml) | Automatic PR impact review and a manual fallback; upload JSON/Markdown and a job summary. No AI key. |
| [action.yml](../action.yml) | Composite analysis action for one mapped document; dry-run by default, optional live provider call. |
| [docguard-repair.yml](../.github/workflows/docguard-repair.yml) | Manually analyze an open same-repository PR; optional draft publication after environment approval. |
| [benchmark.yml](../.github/workflows/benchmark.yml) | Separately budgeted upstream pilot evaluation using `run_pilot.py`. This is not yet the new `evaluate-reference` workflow. |
| [release.yml](../.github/workflows/release.yml) | Test and build distributions/container; optional protected registry publication after release prerequisites. |

These workflows use GitHub-hosted Ubuntu runners; DocGuard's own test matrix also
uses Windows. There is no server you need to keep running. A generated repair
targets the original feature branch through a draft PR; normal application CI and
human review still apply before merging.

For another application's repository:

1. Commit a mapping for one Python entity and one Markdown document.
2. Use [the disposable CI demo generator](ci-benchmark-demo.md) as a working example.
   Pin the tool checkout/action to a reviewed DocGuard commit. The workflows in
   this repository assume they live alongside the tool; copying them unchanged
   into an application will not provide that trusted tool checkout.
3. Run advisory impact review with read-only credentials and full Git history.
   The tool and proposed application code are separate checkouts. Target source
   is parsed, not installed or executed by DocGuard.
4. For live analysis, add your provider key as an Actions secret. Keep analysis
   manual initially and inspect the proposal artifact before requesting publication.
5. Configure `docguard-publish` with required reviewers, permit Actions PR creation,
   and grant write permissions only to the publication job. The workflow checks
   the artifact digest and source state again before publishing.

The [hosted acceptance record](public-hosted-acceptance.md) records successful
automatic review and live analysis. It records publication waiting for approval;
hosted publication/rerun acceptance is still a separate outstanding check.
Do not switch to privileged fork execution just to expose secrets. GitHub normally
withholds Actions secrets from fork PRs; see [GitHub's secret rules](https://docs.github.com/en/code-security/reference/secret-security/secret-types)
and [workflow security guidance](https://docs.github.com/en/actions/reference/security/secure-use).

## GitLab: CLI reporting integration

DocGuard's Git commands work with a local checkout regardless of its host.
There is currently **no GitLab merge-request publisher, comment bot or hosted
GitLab acceptance run**. Start with a report artifact using the example below.

This job requires a Linux Docker/Kubernetes runner with network access to install
the reviewed tool. It uses standard detached merge-request pipelines, full Git
history and no provider secret. Merge-result and merge-train pipelines are excluded
because their commit semantics require a separate integration check.

Add this job to your application's `.gitlab-ci.yml` (merge its stages/variables
with your existing configuration). The pinned DocGuard commit supports
`review-git`; replace it with a reviewed newer commit when adopting newer features.

```yaml
docguard-review:
  stage: test
  image: python:3.11-bookworm
  variables:
    GIT_DEPTH: "0"
    GIT_SUBMODULE_STRATEGY: none
    DOCGUARD_REVISION: "6173ecf56dedd9fe570bc09daeb2857395db3523"
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event" && $CI_MERGE_REQUEST_EVENT_TYPE == "detached"'
  script:
    - |
      set -eu
      work_dir="$(mktemp -d)"
      cd "$work_dir"
      python -I -m venv tool
      tool/bin/python -I -m pip install --no-deps "git+https://github.com/smaoui-me/docguard.git@$DOCGUARD_REVISION"
      git -C "$CI_PROJECT_DIR" cat-file -e "${CI_MERGE_REQUEST_DIFF_BASE_SHA}^{commit}"
      mkdir -p "$CI_PROJECT_DIR/.docguard-ci"
      tool/bin/python -I -m docguard review-git \
        --root "$CI_PROJECT_DIR" \
        --base "$CI_MERGE_REQUEST_DIFF_BASE_SHA" --head "$CI_COMMIT_SHA" \
        --mapping docguard-map.json --format json --advisory \
        --summary "$CI_PROJECT_DIR/.docguard-ci/summary.md" \
        > "$CI_PROJECT_DIR/.docguard-ci/report.json"
  artifacts:
    when: always
    paths:
      - .docguard-ci/
    expire_in: 7 days
```

The head commit must contain the mapped document and mapping. Missing history,
invalid source or invalid mappings fail the job. Findings remain advisory because
of `--advisory`; remove that flag only when you want review findings to fail CI.
Artifacts remain available on errors, but may be incomplete; a failed job is not
a clean review. Add `.docguard-ci/` to the application's `.gitignore`.

For production adoption, pin the runner image digest and review inherited CI jobs,
variables and runner permissions. Keep fork pipelines unprivileged. GitLab's
[merge-request pipeline documentation](https://docs.gitlab.com/ci/pipelines/merge_request_pipelines/)
describes triggers and fork behavior; [predefined variables](https://docs.gitlab.com/ci/variables/predefined_variables/)
describe the base SHA and pipeline event type; [job artifacts](https://docs.gitlab.com/ci/jobs/job_artifacts/)
describe saved outputs. Validate the example using your GitLab project's CI Lint
and run a disposable MR before making it required. This example has not been
executed on a hosted GitLab runner in this project.

## Where the new reference benchmark fits

Use `review-pack --paired-upstream` to prepare a versioned packet from pinned
upstream Git history, then `evaluate-reference --live` in a separate manual or
scheduled job. Upload `comparison.html`, `comparison.json` and `generation.json`
even when the benchmark exits nonzero. Its exit code 1 means disagreement, errors
or incomplete cases; it does not mean your application's tests failed.

Keep the packet and output directory between runs when using `--resume`; restore
the same artifacts and configuration rather than generating a new packet silently.
Set request and pacing budgets, retain failures, and protect the live key. The
new runner is currently available through the CLI; adapting the existing hosted
benchmark workflow and verifying artifact-based resume is the next CI enhancement.
See [automatic reference evaluation](automatic-reference-evaluation.md).
