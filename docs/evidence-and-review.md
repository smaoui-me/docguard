# Dependency evidence and human evaluation

DocGuard can enrich Git proposals with static Python dependencies and record human
judgments of evaluated proposals. These are separate capabilities: more source
context is not proof that an AI answer is correct.

## See the difference without an API key

```powershell
.\.venv\Scripts\python.exe examples/evidence_demo.py --output .docguard-demo-evidence-manual
```

The script refuses to overwrite an existing directory. Choose a fresh directory
when repeating it. It creates two commits where `total(price)` changes from
returning `price` to calling `transform(price)`, which multiplies by 1.2.
Only `total` is mapped to the README. No fixture code is executed.

Two request files are created in the demo directory:

- `mapped-requests.json`: the before/after `total` definitions only.
- `direct-requests.json`: the same evidence plus `after:api.py:transform`.

Open them in the editor to inspect the exact payload. These files contain requests,
not generated model answers. No API call occurs during this demo.

For a real proposal from your configured provider:

```powershell
.\.venv\Scripts\python.exe -m docguard suggest-git --root .docguard-demo-evidence-manual --base HEAD~1 --evidence-policy direct --output dependency-proposal.json
.\.venv\Scripts\python.exe -m docguard apply-git-proposal dependency-proposal.json --root .docguard-demo-evidence-manual --document README.md --check
```

The first command makes an API request. Add `--dry-run` and use another output
filename to inspect the payload instead. Preview does not write the document.

## Selection rules

`mapped` remains the default. `direct` performs a deterministic breadth-first walk
starting from mapped functions or methods, independently for base and head:

- Follow uniquely resolved module-level functions, local imports (including aliases
  and relative imports), and explicit local class constructors.
- Include referenced literal module assignments, including constant-only modules.
  These are initial values, not claims about runtime mutation.
- Include dependency decorators in the source snippet and record unresolved
  decorator references.
- Preserve exact source text, revision, line range, hash, and selection reason.

Each side permits at most 12 additional snippets, two dependency levels and 8,000
serialized characters. The existing total 40,000-character context limit still
applies; mapped evidence is retained and extra evidence is omitted when necessary.
`evidence_gaps` records unresolved or omitted references. Gap reporting is bounded
and indicates when additional gaps were omitted.

This is static reference retrieval, not runtime call-graph analysis. It does not
resolve arbitrary receiver methods, inheritance, monkey patching, closures,
conditional/duplicate bindings, wildcard imports, or third-party dependencies.
Ambiguous module matches are rejected. Class-level mappings do not automatically
expand every method; map the relevant methods explicitly. Callers are not retrieved.

Dependency retrieval happens after the existing change review selects a document.
A change only inside an unmapped helper does **not** yet trigger review of its
callers' documentation. Mapping discovery and dependency-aware impact detection
remain future work. No code, imports, decorators or build scripts are executed.

## Use it in an evaluation

Add `evidence_policy = "direct"` to a development upstream case and make sure its
`source_paths` include the modules that should be available for retrieval. The
projection deliberately limits available files; the collector cannot recover
dependencies absent from that scope. Existing cases stay on `mapped` so the
missing-dependency ablation and reserved cases do not silently change.

Compare identical cases with different evidence policies as explicit variants in
the same split/group. Measure decisions and human judgments as well as context
size. Merely collecting more snippets is not a quality improvement metric.
Changed manifests or selector versions require fresh reports, not `--resume` of
results from an older configuration.

## Record human judgments

Start from a completed or partially completed upstream evaluation report:

```powershell
.\.venv\Scripts\python.exe -m docguard review-template evaluation-httpx-resumable-v2.json --output my-human-review.json
```

Only completed model cases get form rows. Each row starts with null judgments;
the tool never fills in a person's verdict. Inspect the report's source evidence,
original document, proposal and automated checks, then fill:

- `reviewer`: who performed the review.
- `independent`: whether they were independent of the implementation and labels.
- `expected_action`: the reviewer's justified `revise`, `unchanged`, or `needs_review`.
- `supported`: whether the decision and generated claims are supported by evidence.
- `complete`: whether it addresses the necessary documentation changes/uncertainty.
- `preserves_unrelated`: whether unrelated content remains intact.
- `accepted`: whether the reviewer accepts the proposal/decision as delivered.
- `notes`: specific rationale, source references, and any label disagreement.

Use JSON booleans (`true`/`false`), not strings. Leave a row entirely null while it
is pending. Partially filled ratings are rejected rather than silently scored.

```powershell
.\.venv\Scripts\python.exe -m docguard score-review evaluation-httpx-resumable-v2.json --reviews my-human-review.json --output my-human-scores.json
```

Scores include coverage of completed cases, acceptance, supported claims,
completeness, preservation, agreement with provisional labels, and model action
accuracy against reviewer labels. Every rate includes numerator and denominator;
zero reviewed cases yield null quality rates. Independent reviews are summarized
separately. Total selected and completed case counts keep operational coverage
visible; reviewing only successful cases does not establish whole-suite quality.

The form contains the exact source-report hash. Resume, edits, or replacement of
that report invalidate the form, so finalize a run before collecting final reviews.
Duplicate, unknown and unfinished cases are rejected. Original reports and gold
labels are never rewritten. Independence and identity are human attestations,
not authenticated identities. Resolve label disagreements before declaring a
reviewed benchmark; do not count AI-generated judgments as independent review.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest tests/code/test_evidence.py tests/code/test_human_review.py tests/code/test_git_proposals.py -v
```

These cover static resolution, cycles, budgets, shadowing, unresolved dependencies,
source non-execution, artifact tampering, legacy artifact preview, pending review
scores, malformed forms, changed reports and reviewer independence denominators.

For paced before/after AI comparisons with unchanged benchmark labels, see
[baseline regression evaluation](baseline-regression.md). It also explains the
request compaction and preservation diagnostics added after the first live pilot.
