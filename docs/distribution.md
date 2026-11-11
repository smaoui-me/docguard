# Installable release candidate

DocGuard is currently an alpha CLI and composite GitHub Action. The release
workflow prepares distributable artifacts; no PyPI or GHCR release is implied.
Python source analysis and mapped Markdown are the supported initial scope.
Git is required for Git review/proposals. Ordinary snapshot operations need Python
3.11+ only. An AI key is required only for live generation.

## Install and verify without an API key

From the source checkout, in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install ".[dev,release]"
.venv\Scripts\python.exe -m build --outdir dist/release-candidate
.venv\Scripts\python.exe -m twine check --strict dist/release-candidate/*.whl dist/release-candidate/*.tar.gz
.venv\Scripts\python.exe examples/check_distributions.py dist/release-candidate
python -m venv .docguard-demo-release-install
.docguard-demo-release-install\Scripts\python.exe -m pip install --no-index --no-deps dist/release-candidate/docguard-0.1.0-py3-none-any.whl
.docguard-demo-release-install\Scripts\python.exe examples/verify_installation.py
.docguard-demo-release-install\Scripts\docguard.exe --version
```

Use the actual artifact version if it changes. On Linux/macOS the environment's
interpreter is `bin/python` and the executable is `bin/docguard`. Do not install an
unverified package from PyPI merely because its name is `docguard`; ownership of
that registry name must be established before our first publication.

The acceptance script runs from a temporary directory, uses isolated Python
imports and the installed console entry point, creates real Git history, checks
impact detection and dry-run requests, runs offline evaluation, and checks error
exit behavior. It does not call a provider or GitHub. Offline fixture success
validates plumbing, not model quality. Real-PR evaluation still uses the repository's
versioned manifests and review protocol; those datasets are not embedded in the wheel.

The source distribution includes this acceptance script. `python -m build` builds
the wheel from the sdist, testing that the sdist contains the required package code.
`check_distributions.py` audits paths and payload categories and writes `SHA256SUMS`.
Checksums detect changed bytes relative to a trusted checksum file; they are not a
signature or proof of publisher identity.

## Container usage

The container installs the wheel, includes Git, and runs as UID/GID 10001. Its
allowlisted build context excludes `.env`, Git history, caches, and local demos.
No key is supplied during build. Start Docker Desktop/the Linux Docker daemon first.

```powershell
docker build -t docguard:0.1.0 .
docker run --rm --network none --read-only --tmpfs /tmp docguard:0.1.0 --version
docker run --rm --network none --read-only --tmpfs /tmp docguard:0.1.0 evaluate-ai --output /tmp/evaluation.json
```

The second command's report disappears with the container; use a writable output
mount to retain artifacts. A Linux example for a real repository:

```bash
mkdir -p "$PWD/output"
docker run --rm --user "$(id -u):$(id -g)" \
  --network none --read-only --tmpfs /tmp --cap-drop ALL \
  --security-opt no-new-privileges \
  --mount "type=bind,src=$PWD/demo,dst=/workspace,readonly" \
  --mount "type=bind,src=$PWD/output,dst=/output" \
  docguard:0.1.0 snapshot /workspace --output /output/baseline.json
```

Use absolute existing host paths. On Docker Desktop, use PowerShell's resolved
paths and ensure the output directory is writable by the container user. For Git
commands mount the complete repository including `.git` at `/workspace`; that
exact path is configured as a safe Git directory. Source mounts remain read-only
for analysis. Applying a repair requires an explicitly writable target checkout.

For live generation, pass only the required provider variable at runtime, for
example `--env GROQ_API_KEY` when it already exists in the host environment, and
allow network access. Do not put key values in command arguments, build arguments,
Dockerfiles, or images. The image does not automatically read the host `.env`.

`PYTHON_IMAGE` defaults to a pinned digest and can be overridden for update testing.
Package-manager downloads can still change: the current build is not claimed to
be byte-for-byte reproducible. Release publication reuses the tested image artifact
without rebuilding; deployments should record its registry digest.

## CI and publication

`.github/workflows/release.yml` runs on PRs or manual dispatch. Default `target=build`
does not publish. It runs lint, type checks and offline tests; builds/audits the
wheel and sdist; tests the installed wheel on Linux and Windows; and exercises the
container without network access, with a read-only root and restricted privileges.
Its artifacts are `distributions` and `tested-image`.

Before choosing a publishing target:

1. Choose a license, add its `LICENSE` text and `project.license` metadata. This
   project currently has no license declaration; publication fails until supplied.
2. Confirm ownership of the distribution name on TestPyPI/PyPI. Configure Trusted
   Publishing for owner `smaoui-me`, repository `docguard`, workflow `release.yml`,
   and environment `testpypi` or `pypi`. No persistent PyPI token is needed.
3. Configure required reviewers for `testpypi`, `pypi`, and/or `ghcr`. Merely naming
   an environment in YAML is insufficient; the workflow checks the configuration.
4. Choose a new package version, review the commit, and create its matching tag
   (for example `v0.1.0`). Dispatch the workflow **on that tag**, with `testpypi`
   first. The package version must match the tag exactly.
5. Inspect test artifacts and approve the environment gate. Repeat for `pypi` or
   `ghcr` only when ready. Nothing auto-merges and normal PRs cannot publish.

Python publication uploads the built artifacts with Trusted Publishing and the
publishing action's attestations. GHCR publication loads the tested image artifact
and pushes `ghcr.io/smaoui-me/docguard:VERSION`; it does not maintain `latest`.
An existing image version is refused when detected. Tags are not atomic locks:
avoid concurrent publication of the same version and consume images by digest.

Before a production release, also review dependency/image vulnerabilities, pin
approved action/base-image revisions, and record the supported update policy.
This scaffold does not yet provide a vulnerability scan or a signed container.

## Independent installation trial

Give another developer the wheel, trusted checksum file, source-distribution
acceptance script and these instructions. Ask them to use a clean machine or venv
without coaching. Record OS/Python/Git versions, artifact hash, command output,
installation problems, and whether they can explain the review/approval flow.
Keep their feedback separate from our automated acceptance tests; do not label
author-run tests as an independent trial.

## Local acceptance record — November 10, 2026

- Full offline suite: 428 passed, 4 skipped, 179 subtests passed.
- New archive/release-identity checks run separately: 13 passed.
- Ruff passed; mypy passed for 33 source files; release workflow passed actionlint.
- Wheel built from the sdist; both passed strict Twine metadata validation and
  distribution-payload checks. Checksums are in `dist/release-candidate/SHA256SUMS`.
- Clean Windows Python 3.14 installation passed the script bundled inside the sdist.
- Linux Python 3.11 container passed the same acceptance script as UID/GID 10001,
  without networking, with a read-only root filesystem and dropped capabilities.
- Bind-mount snapshot/compare passed with read-only source and separate output.

These are author-operated local checks. The new release workflow has not yet run
on GitHub, no registry publication occurred, and no independent installation trial
is implied. The existing public synthetic application CI is separate evidence.

### Benchmark/UI follow-up — November 10, 2026

- Full suite with the Edge browser check enabled: 456 passed, 4 skipped, 179
  subtests passed. After the final checkpoint validation hardening, the focused
  experiment suite passed all 14 tests, including browser export/import and scoring.
- Ruff checks and formatting passed; mypy passed for 36 source files.
- Updated wheel and source archive are in `dist/review-candidate/`; both passed
  strict Twine metadata validation and payload audits. `SHA256SUMS` binds this build.
- The disposable Windows environment was reinstalled from the new wheel. Its
  acceptance script now also exercises packaged HTML generation and new CLI help.
- The browser CI job is implemented but has not yet run on GitHub. The container
  acceptance above predates these new modules; no new container run is claimed.

No paid model calls or independent human judgments were made in this follow-up.
Use the [manual benchmark guide](manual-benchmark-review.md) to produce those
separate measurements. Existing pilot PRs remain development/regression data.

### Friend-trial candidate verification — November 10, 2026

- Full offline suite: 477 passed, 6 skipped, 179 subtests passed. The two opt-in
  Edge browser tests also passed separately.
- Ruff lint/format checks passed; mypy passed for 38 source files. README/guide
  links and repository documentation mappings validated.
- Built the current wheel from its source distribution in `dist/friend-trial/`.
  Both passed strict Twine checks and the distribution payload audit;
  `SHA256SUMS` records the artifact hashes.
- Installed that wheel without dependencies or registry access into a new
  Windows Python 3.14 virtual environment. The installed-package acceptance
  script passed, including Git review, offline evaluation and packaged review UI.
- The section-repair demo passed all five checks from the installed wheel:
  generation/preview preserved the document, application preserved outside bytes,
  the multiplier was documented, and stale reapplication was rejected.
  This used a fixed response, zero API requests and zero GitHub writes.

This is an author-operated installation check. Friends can now follow
[the first-trial guide](first-trial.md) for independent feedback. No new hosted
workflow, GitLab runner, container execution or registry publication is claimed
by this verification. The previous live reference comparison is recorded
separately in [the pilot report](reference-evaluation-20261110.md).
