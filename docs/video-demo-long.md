# DocGuard demo: use it on a project

A practical 5-6 minute walkthrough. Show a stale document, generate a repair with
Groq, review the diff and apply it. Speak briefly and let the screen show the result.
The [short version](video-demo-short.md) covers the same workflow in 60-90 seconds.

## Prepare before recording

Use PowerShell from the DocGuard repository root. Have Python 3.11+, Git and the
project environment installed:

```powershell
# Only if you have not created the environment:
python -m venv .venv

.venv\Scripts\python.exe -m pip install -e .
```

Configure your existing local `.env` before recording:

```dotenv
DOCGUARD_AI_PROVIDER=groq
DOCGUARD_MODEL=openai/gpt-oss-120b
GROQ_API_KEY=YOUR_REAL_GROQ_KEY
```

Close that file. All commands below run from the project root so DocGuard can
load it. The generation step makes a real API request using synthetic example code.

### Prepare the example once

Choose a new directory for each recording. This preparation creates example Git
history without an API call:

```powershell
$Demo = ".docguard-demo-showcase-take1"
.venv\Scripts\python.exe examples/section_demo.py --output $Demo
if ($LASTEXITCODE -ne 0) { throw "Example setup failed" }
$Repo = "$Demo/repo"
```

That helper already applied a fixture repair. Restore only the example's README
to its committed version so you can demonstrate generation, preview and application
yourself, one step at a time:

```powershell
.venv\Scripts\python.exe -c "import subprocess, sys; from pathlib import Path; p = Path(sys.argv[1]); data = subprocess.run(['git', '-C', str(p), 'show', 'HEAD:README.md'], check=True, capture_output=True).stdout; (p / 'README.md').write_bytes(data)" $Repo
if ($LASTEXITCODE -ne 0) { throw "Example reset failed" }

$Base = git -C $Repo rev-list --max-parents=0 HEAD
$Head = git -C $Repo rev-parse HEAD
$Proposal = "$Demo/live-proposal.json"
```

This restores the demo file byte for byte. The code still returns `price * 1.2`,
and its documentation now says `returns price unchanged`. Keep this terminal open:
the following scenes use these variables.

Do not show the helper's old `proposal.json` or `evaluation.json` during the video.
Your fresh API output will be in `live-proposal.json`.

### Open these screens

| Screen | File |
| --- | --- |
| Left editor | `.docguard-demo-showcase-take1/repo/api.py` |
| Right editor | `.docguard-demo-showcase-take1/repo/README.md` |
| Extra tab | `.docguard-demo-showcase-take1/repo/docguard-map.json` |
| Closing tab | Root `README.md`, preview at **Try it in five minutes** |
| Optional CI tab | `docs/ci-integration.md` |

Use `Ctrl+P` to open files and split the source/document editors. Make the font
readable, close unrelated tabs and keep the terminal visible. You do not need
benchmark reports, test files, provider source or architecture diagrams for this video.

## 0:00-0:30 ? Show what needs fixing

**Screen:** source and documentation side by side. Highlight `* 1.2`, then
`returns price unchanged`.

**Say:**

> This function changed, but the documentation didn't. Let's use DocGuard to
> update the relevant section.

Leave the mismatch visible for a moment. No project-history introduction needed.

## 0:30-1:00 ? Show the mapping

**Screen:** the example's `docguard-map.json`. Point to `api.py:total` and
`["# Billing", "## Prices"]`.

**Say:**

> I link this function to the Prices section. That's the section I want DocGuard
> to check when the function changes.

The mapping already exists in the example. For another project, the user commits
a mapping with their actual file paths, entity IDs and headings.

## 1:00-2:00 ? Generate a repair with a real API call

**Screen:** terminal. Paste:

```powershell
.venv\Scripts\python.exe -m docguard suggest-git --root $Repo --base $Base --head $Head --mapping docguard-map.json --document README.md --max-documents 1 --provider groq --model openai/gpt-oss-120b --output $Proposal
$LASTEXITCODE
```

**Say:**

> I give DocGuard the repository and the commits to compare. This sends the
> relevant code and documentation to Groq and saves a proposal.

This command is live by default. Do **not** add `--dry-run`. Unlike the all-in-one
example helper, it does not apply the repair.

Wait for completion. A successful command returns exit code `0`. If the wait is
long, shorten it in editing with a small **API wait shortened** caption.

## 2:00-2:40 ? Inspect what the model suggested

**Screen:** open `.docguard-demo-showcase-take1/live-proposal.json`. Find the
proposal's `action`, `summary` and `content`. Then return to the example README.

**Say:**

> Here is the suggested correction. The original document hasn't changed yet.
> I'll preview the actual diff before applying it.

The desired action for this example is `revise`, with wording that describes
multiplication by 1.2. Read the actual output. If it says `unchanged` or
`needs_review`, explain that result instead of continuing as though it repaired
the document.

## 2:40-3:30 ? Preview the change

**Screen:** terminal.

```powershell
.venv\Scripts\python.exe -m docguard apply-git-proposal $Proposal --root $Repo --document README.md --check
```

**Say:**

> This previews the edit. The Prices description changes, while the Support
> section stays as it was.

Pause on the red/green lines. Keep the Support section visible in the editor.
This step uses the saved proposal and makes no API call.

## 3:30-4:15 ? Apply and inspect

**Screen:** terminal, then the example README.

```powershell
.venv\Scripts\python.exe -m docguard apply-git-proposal $Proposal --root $Repo --document README.md
git -C $Repo diff -- README.md
```

**Say:**

> I'm happy with the diff, so I apply it. The documentation now matches the
> function. I can review and commit this change like any other edit.

Point to the corrected sentence and the untouched Support section. Do not commit
during the recording unless you want to demonstrate that extra step.

Optional ten-second extra: rerun the preview command. It should reject the proposal
because the document has changed. Say: **"An outdated proposal can't be applied again."**
Then move on; there is no need for a longer explanation.

## 4:15-5:00 ? Show how someone uses their own project

**Screen:** return to the mapping, then show this command template in the guide.
These are placeholders; do not execute them unchanged.

```powershell
python -m docguard suggest-git --root ../your-project --base BASE_SHA --head HEAD --mapping docguard-map.json --document docs/your-page.md --output your-proposal.json
python -m docguard apply-git-proposal your-proposal.json --root ../your-project --document docs/your-page.md --check
python -m docguard apply-git-proposal your-proposal.json --root ../your-project --document docs/your-page.md
```

**Say:**

> For your project, commit a mapping to the function and document you want to
> track. Choose the commits, generate a proposal, preview it and apply it.
> Those are the same three commands we just used.

Practical notes to put in the video description rather than read aloud:

- Python source and Markdown sections are the current supported scope.
- Source and mapping changes must be committed; Git review reads committed history.
- Both commits must be available locally.
- Run from the directory containing your AI configuration, or give `suggest-git`
  an explicit `--env-file` path.
- Use a new proposal filename for another generation.
- The [CLI reference](cli-reference.md) and [section mapping guide](targeted-repair.md)
  explain how to choose IDs and heading paths.

## 5:00-5:30 ? CI and closing

**Screen:** `docs/ci-integration.md`, then the README installation instructions.

**Say:**

> You can also run documentation review on pull requests and request an AI repair
> through the GitHub workflow. The integration guide includes setup instructions.
> To try it locally, install DocGuard and run the example with your own API key.

End on the repository name and installation commands. If you show the GitHub
workflow, describe it as an available workflow; this recording demonstrates the
local repair and does not open a hosted draft PR.

The timing is flexible: allow viewers time to read the code and diff. A clear
four-minute take is better than stretching it to six minutes. For a shorter cut,
use [the short script](video-demo-short.md).

## If something goes wrong

| What happened | What to do |
| --- | --- |
| Demo directory exists | Change `take1` to `take2` and repeat preparation. |
| Missing or invalid key | Correct `.env` before another take. Keep its contents off screen. |
| Rate limit or network failure | Keep the error output, wait as indicated and retry deliberately with a new proposal filename. |
| No applicable revision | Read the action and explanation. Do not run the success narration over that result. |
| Document changed since generation | Regenerate from the intended committed source/document state. The rejection is expected only in the optional reapply scene. |
| Variables disappeared | Reopen this guide and set them to the existing take's paths and Git commits; do not rerun the setup helper into the same directory. |

Generating the proposal is the only API step in this recording. Inspecting,
previewing and applying it reuse the saved response.
