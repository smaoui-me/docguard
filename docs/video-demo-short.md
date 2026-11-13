# DocGuard demo: 60-90 seconds

Show the product in use: stale document, live proposal, preview, corrected document.
Prepare the example and configure Groq using the
[long guide](video-demo-long.md#prepare-before-recording). Keep its PowerShell
terminal open with `$Repo`, `$Base`, `$Head` and `$Proposal` defined.

Use a fresh take for this video. If you already completed the long walkthrough,
its document has been repaired and its proposal filename already exists.

Open only the example's `api.py`, `README.md`, terminal and the root README.
The live command below makes one generation request. Shorten API waiting time
in editing and label the cut.

## 0:00-0:12 ? The problem

**Show:** function and stale document side by side.

**Say:**

> This function now multiplies the price by one point two, but its documentation
> still says it returns the original price. Let's fix that with DocGuard.

## 0:12-0:35 ? Generate

**Run:**

```powershell
.venv\Scripts\python.exe -m docguard suggest-git --root $Repo --base $Base --head $Head --document README.md --max-documents 1 --provider groq --model openai/gpt-oss-120b --output $Proposal
```

**Say:**

> I've mapped the function to this documentation section. DocGuard sends the
> relevant context to Groq and saves a suggested correction.

The default mapping path is `docguard-map.json`. Continue only if generation
succeeds and the proposal contains a suitable `revise` action.

## 0:35-0:55 ? Preview

**Run:**

```powershell
.venv\Scripts\python.exe -m docguard apply-git-proposal $Proposal --root $Repo --document README.md --check
```

**Say:**

> Here's the diff. It updates the Prices section and preserves the rest of the
> document. Nothing has been applied yet.

Pause on the proposed sentence.

## 0:55-1:15 ? Apply

**Run:**

```powershell
.venv\Scripts\python.exe -m docguard apply-git-proposal $Proposal --root $Repo --document README.md
```

**Show:** corrected README.

**Say:**

> I apply the proposal, and the documentation now matches the code. It's ready
> for normal review and commit.

## 1:15-1:30 ? Invite people to try it

**Show:** root README, **Try it in five minutes**.

**Say:**

> To use it on your Python project, add a documentation mapping, choose your
> commits, then generate, preview and apply. The README includes a runnable demo.

End. Keep benchmark scores, architecture and the source-code tour in the written
documentation. For this video, the before-and-after result is the main point.
