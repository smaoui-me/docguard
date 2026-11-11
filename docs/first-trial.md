# First trial with a friend

DocGuard is ready for an alpha trial. Share access to a clean source checkout at
a specific commit, or a verified wheel and this guide. The registry release and
an independent installation trial are still pending. Your friend's first run can
provide that installation evidence; it does not establish model accuracy.

## Install

Prerequisites: Python 3.11+ and Git on PATH. From a fresh terminal:

```powershell
git clone https://github.com/smaoui-me/docguard.git
cd docguard
git rev-parse HEAD
python -m venv .venv
.venv\Scripts\python.exe -m pip install .
.venv\Scripts\python.exe examples/verify_installation.py
```

Record the commit printed by Git. To test an exact candidate, run
`git checkout COMMIT_SHA` before installation, replacing the placeholder with the
shared commit. The commit must be pushed before someone can fetch it; a local
commit alone is not available to friends. For Linux/macOS replace
`.venv\Scripts\python.exe` with `.venv/bin/python`.

The verification script creates temporary Git history and checks the installed
package, command-line entry point, offline evaluation, review UI and error exits.
It should finish with `PASS: clean installation, ...`. No API key is needed.

## Watch a repair without paying for an API call

```powershell
.venv\Scripts\python.exe examples/section_demo.py --output .docguard-demo-friend
```

Inspect these files:

- `.docguard-demo-friend/evaluation.json`: `passed` and each individual check.
- `.docguard-demo-friend/proposal.json`: proposed correction and evidence.
- `.docguard-demo-friend/repo/README.md`: the updated Prices section and untouched Support section.
- `.docguard-demo-friend/publication-preview.json`: proposed publication plan; no GitHub write occurs.

This demo uses a fixed response. It verifies generation/preview do not edit the
document, application changes only the selected section, and stale reapplication
is rejected. Choose a new output directory for another run.

## Try a real model

Copy `.env.example` to `.env`, enter your own Groq or OpenAI key and select your
provider/model. Follow [AI configuration](ai-workflow.md). Then run:

```powershell
.venv\Scripts\python.exe examples/section_demo.py --live --output .docguard-demo-friend-live
```

This makes one generation request using synthetic pricing code/documentation.
Inspect both the wording and the preservation checks. A passing demo is a small
smoke test, not a quality score. For comparisons against actual engineers' PR
corrections, use [automatic reference evaluation](automatic-reference-evaluation.md).

## Try your own repository and CI

Start with a disposable branch in a Python project. Commit a `docguard-map.json`
linking one Markdown file to a function, then commit a change to that function.
Use [the CLI reference](cli-reference.md) to run `review-git` against the two
commits. The source and mapping must be committed; working-tree edits are ignored.
Then follow [CI integration](ci-integration.md). Start with advisory reporting
before enabling live repair or publication.

Send back the commit SHA, OS, Python/Git versions, command, exit code, sanitized
error output and whether the proposed wording was useful. Include expected versus
actual behavior. Do not include `.env`, API keys or private source in a public issue.
Keep installation feedback separate from automated benchmark agreement scores.
