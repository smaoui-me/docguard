"""Command-line access to repository snapshots and metadata comparison."""

import argparse
import json
import sys
from functools import partial
from importlib.metadata import version
from pathlib import Path

from docguard.ai.benchmark import audit_benchmark, collect_candidates
from docguard.ai.config import load_config
from docguard.ai.dataset import evaluate_dataset
from docguard.ai.evaluation import evaluate
from docguard.ai.experiment_packet import prepare_packet, reference_labels
from docguard.ai.experiments import run_experiment, score_experiment
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.human_review import review_template, score_review
from docguard.ai.operations import summarize_evaluation
from docguard.ai.proposals import apply_proposal, suggest
from docguard.ai.provider import generate
from docguard.ai.reference_benchmark import evaluate_reference
from docguard.ai.review_ui import render_review_ui
from docguard.ai.upstream import evaluate_pr
from docguard.code.comparison import compare_snapshots
from docguard.code.index import index_repository
from docguard.code.snapshots import load_snapshot, save_snapshot
from docguard.docs.mapping import load_mapping
from docguard.docs.reporting import report_document, report_summary, report_text
from docguard.docs.review import review_documents
from docguard.git_review import review_git
from docguard.publication import publish_proposal


def main(argv: list[str] | None = None) -> int:
    """Return 0 for success/no changes, 1 for changes, and 2 for errors."""
    parser = argparse.ArgumentParser(prog="docguard", description=__doc__)
    parser.add_argument(
        "--version", action="version", version=f"docguard {version('docguard')}"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    snapshot = commands.add_parser("snapshot", help="Save a repository index as JSON")
    snapshot.add_argument("root", type=Path, help="Repository directory")
    snapshot.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Destination JSON file (replaces existing file)",
    )
    compare = commands.add_parser(
        "compare", help="Compare a saved baseline with current source"
    )
    compare.add_argument("baseline", type=Path, help="Previously saved snapshot")
    compare.add_argument(
        "--root",
        type=Path,
        required=True,
        help="Same logical repository root used for the baseline",
    )
    review = commands.add_parser(
        "review", help="Find documentation needing review after code changes"
    )
    review.add_argument("baseline", type=Path, help="Previously saved snapshot")
    review.add_argument("--root", type=Path, required=True, help="Repository root")
    review.add_argument(
        "--mapping",
        type=Path,
        required=True,
        help="Versioned JSON documentation mapping",
    )
    review.add_argument("--format", choices=("text", "json"), default="text")
    git_review = commands.add_parser(
        "review-git", help="Review committed changes against a Git merge base"
    )
    git_review.add_argument("--root", type=Path, required=True)
    git_review.add_argument(
        "--base", required=True, help="Target branch or commit, available locally"
    )
    git_review.add_argument(
        "--head", default="HEAD", help="Proposed commit (default: HEAD)"
    )
    git_review.add_argument(
        "--mapping", required=True, help="Path inside the head commit"
    )
    git_review.add_argument("--format", choices=("text", "json"), default="text")
    git_review.add_argument(
        "--summary", type=Path, help="Write an escaped Markdown summary"
    )
    git_review.add_argument(
        "--advisory",
        action="store_true",
        help="Return 0 for findings; errors still return 2",
    )
    ai = commands.add_parser(
        "suggest",
        help="Generate reviewable AI documentation proposals (sends context to the selected provider unless --dry-run)",
    )
    ai.add_argument("baseline", type=Path)
    ai.add_argument("--root", type=Path, required=True)
    ai.add_argument("--mapping", type=Path, required=True)
    ai.add_argument(
        "--output",
        type=Path,
        required=True,
        help="New JSON file; existing files are never overwritten",
    )
    ai.add_argument("--model")
    ai.add_argument("--provider", choices=("openai", "groq"))
    ai.add_argument(
        "--env-file",
        type=Path,
        help="Configuration file (default: .env in current working directory)",
    )
    ai.add_argument(
        "--document",
        action="append",
        default=[],
        help="Restrict to a flagged document; repeatable",
    )
    ai.add_argument("--max-documents", type=int, default=3)
    ai.add_argument(
        "--dry-run",
        action="store_true",
        help="Save request payloads locally without an API call",
    )
    apply = commands.add_parser(
        "apply-proposal",
        help="Explicitly apply one reviewed proposal, or preview its diff",
    )
    apply.add_argument("proposal", type=Path)
    apply.add_argument("--root", type=Path, required=True)
    apply.add_argument("--document", required=True)
    apply.add_argument(
        "--check",
        action="store_true",
        help="Print diff only; do not write the document",
    )
    evaluation = commands.add_parser(
        "evaluate-ai",
        help="Evaluate four synthetic cases; offline fixtures unless --live",
    )
    evaluation.add_argument("--output", type=Path, required=True)
    evaluation.add_argument(
        "--live",
        action="store_true",
        help="Send synthetic cases to the configured provider (incurs API usage)",
    )
    evaluation.add_argument("--repeats", type=int, default=1)
    evaluation.add_argument("--provider", choices=("openai", "groq"))
    evaluation.add_argument("--model")
    evaluation.add_argument("--env-file", type=Path)
    git_ai = commands.add_parser(
        "suggest-git", help="Propose documentation edits from committed Git evidence"
    )
    git_ai.add_argument("--root", type=Path, required=True)
    git_ai.add_argument("--base", required=True)
    git_ai.add_argument("--head", default="HEAD")
    git_ai.add_argument("--mapping", default="docguard-map.json")
    git_ai.add_argument("--output", type=Path, required=True)
    git_ai.add_argument("--document", action="append", default=[])
    git_ai.add_argument("--max-documents", type=int, default=3)
    git_ai.add_argument("--dry-run", action="store_true")
    git_ai.add_argument(
        "--evidence-policy", choices=("mapped", "direct"), default="mapped"
    )
    git_ai.add_argument("--provider", choices=("openai", "groq"))
    git_ai.add_argument("--model")
    git_ai.add_argument("--env-file", type=Path)
    git_apply = commands.add_parser(
        "apply-git-proposal", help="Verify Git evidence and preview/apply one document"
    )
    git_apply.add_argument("proposal", type=Path)
    git_apply.add_argument("--root", type=Path, required=True)
    git_apply.add_argument("--document", required=True)
    git_apply.add_argument("--check", action="store_true")
    corpus = commands.add_parser(
        "evaluate-git", help="Evaluate authored Git cases; fixtures unless --live"
    )
    corpus.add_argument(
        "--dataset", type=Path, default=Path("evaluations/git_cases.toml")
    )
    corpus.add_argument(
        "--split", choices=("development", "reserved", "all"), default="development"
    )
    corpus.add_argument("--case", action="append", default=[])
    corpus.add_argument("--output", type=Path, required=True)
    corpus.add_argument("--live", action="store_true")
    corpus.add_argument("--max-requests", type=int, default=3)
    corpus.add_argument("--provider", choices=("openai", "groq"))
    corpus.add_argument("--model")
    corpus.add_argument("--env-file", type=Path)
    upstream = commands.add_parser(
        "evaluate-pr",
        help="Evaluate pinned upstream PR projections; preparation only unless --live",
    )
    upstream.add_argument(
        "--repository",
        type=Path,
        required=True,
        help="Local upstream clone or bare Git cache",
    )
    upstream.add_argument(
        "--manifest", type=Path, default=Path("evaluations/upstream/httpx.toml")
    )
    upstream.add_argument("--case", action="append", default=[])
    upstream.add_argument("--output", type=Path, required=True)
    upstream.add_argument("--live", action="store_true")
    upstream.add_argument("--max-requests", type=int, default=3)
    upstream.add_argument(
        "--resume",
        action="store_true",
        help="Resume the report at --output; keep completed cases",
    )
    upstream.add_argument("--max-retries", type=int, default=2)
    upstream.add_argument("--max-retry-wait", type=float, default=30)
    upstream.add_argument("--provider", choices=("openai", "groq"))
    upstream.add_argument("--model")
    upstream.add_argument("--env-file", type=Path)
    human = commands.add_parser(
        "review-template",
        help="Create an unfilled human review form for completed evaluations",
    )
    human.add_argument("report", type=Path)
    human.add_argument("--output", type=Path, required=True)
    scoring = commands.add_parser(
        "score-review", help="Score explicit human judgments against their exact report"
    )
    scoring.add_argument("report", type=Path)
    scoring.add_argument("--reviews", type=Path, required=True)
    scoring.add_argument("--output", type=Path, required=True)
    publication = commands.add_parser(
        "publish-proposal",
        help="Preview or explicitly publish one validated Git proposal as a draft PR",
    )
    publication.add_argument("proposal", type=Path)
    publication.add_argument("--root", type=Path, required=True)
    publication.add_argument("--document", required=True)
    publication.add_argument("--repository", required=True, help="GitHub owner/name")
    publication.add_argument("--source-pr", type=int, required=True)
    publication.add_argument(
        "--publish",
        action="store_true",
        help="Authorize GitHub writes; default is a local preview",
    )
    candidates = commands.add_parser(
        "benchmark-candidates",
        help="Mine pinned PR review candidates from a local Git cache",
    )
    candidates.add_argument("--repository", type=Path, required=True)
    candidates.add_argument("--upstream", required=True, help="GitHub owner/name")
    candidates.add_argument("--limit", type=int, default=15)
    candidates.add_argument("--output", type=Path, required=True)
    operations = commands.add_parser(
        "summarize-evaluation",
        help="Summarize recorded quality and operational metrics without API calls",
    )
    operations.add_argument("report", type=Path)
    operations.add_argument("--output", type=Path, required=True)
    audit = commands.add_parser(
        "benchmark-audit",
        help="Check distinct PR counts and cross-manifest split leakage",
    )
    audit.add_argument("manifests", type=Path, nargs="+")
    audit.add_argument("--output", type=Path, required=True)
    packet = commands.add_parser(
        "review-pack", help="Prepare pinned evidence for manual labels; no model calls"
    )
    packet.add_argument("--manifest", type=Path, action="append", required=True)
    packet.add_argument("--repository", type=Path, action="append", required=True)
    packet.add_argument("--case", action="append", default=[])
    packet.add_argument("--output", type=Path, required=True)
    packet.add_argument(
        "--paired-upstream",
        action="store_true",
        help="Create old-doc/new-code and updated-doc/new-code cases from each selected seed",
    )
    packet.add_argument(
        "--discussion", type=Path, help="Optional JSON snapshot of GitHub PR comments"
    )
    reference = commands.add_parser(
        "reference-labels",
        help="Create explicitly provisional expectations from upstream doc changes",
    )
    reference.add_argument("packet", type=Path)
    reference.add_argument("--output", type=Path, required=True)
    ui = commands.add_parser(
        "review-ui", help="Create a standalone offline review page"
    )
    ui.add_argument("packet", type=Path)
    ui.add_argument("--report", type=Path)
    ui.add_argument(
        "--labels", type=Path, help="Preload reference or human labels for verification"
    )
    ui.add_argument("--output", type=Path, required=True)
    experiment = commands.add_parser(
        "evaluate-experiment",
        help="Compare baseline, evidence and validator methods on manually labeled cases",
    )
    experiment.add_argument("packet", type=Path)
    experiment.add_argument("--labels", type=Path, required=True)
    experiment.add_argument("--output", type=Path, required=True)
    experiment.add_argument("--live", action="store_true")
    experiment.add_argument("--resume", action="store_true")
    experiment.add_argument("--max-requests", type=int, default=5)
    experiment.add_argument("--delay-seconds", type=float, default=65)
    experiment.add_argument("--provider", choices=("openai", "groq"))
    experiment.add_argument("--model")
    experiment.add_argument(
        "--discussion-mode", choices=("withheld", "input"), default="withheld"
    )
    score_exp = commands.add_parser(
        "score-experiment", help="Score report-bound human ratings and validator errors"
    )
    score_exp.add_argument("report", type=Path)
    score_exp.add_argument("--reviews", type=Path, required=True)
    score_exp.add_argument("--output", type=Path, required=True)
    automated = commands.add_parser(
        "evaluate-reference",
        help="Generate documentation and automatically compare it with upstream corrections; no human labels",
    )
    automated.add_argument("packet", type=Path)
    automated.add_argument("--output-dir", type=Path, required=True)
    automated.add_argument("--live", action="store_true")
    automated.add_argument("--resume", action="store_true")
    automated.add_argument(
        "--retry-judge-errors",
        action="store_true",
        help="Retry each invalid judge response once, retaining the rejected response",
    )
    automated.add_argument("--max-requests", type=int, default=8)
    automated.add_argument("--delay-seconds", type=float, default=65)
    automated.add_argument("--provider", choices=("groq", "openai"))
    automated.add_argument("--model")
    args = parser.parse_args(argv)
    try:
        if args.command == "evaluate-reference":
            comparison = evaluate_reference(
                args.packet,
                args.output_dir,
                load_config(provider=args.provider, model=args.model),
                live=args.live,
                resume=args.resume,
                max_requests=args.max_requests,
                delay_seconds=args.delay_seconds,
                retry_judge_errors=args.retry_judge_errors,
            )
            print(json.dumps(comparison["metrics"], indent=2))
            print(
                f"Comparison: {args.output_dir / 'comparison.html'}; requests this invocation: {comparison['session_requests']}"
            )
            return int(
                args.live
                and comparison["metrics"]["overall"]["aligned"]
                != comparison["metrics"]["overall"]["total"]
            )
        if args.command == "reference-labels":
            reference_labels(args.packet, args.output)
            print(
                f"Saved provisional upstream-reference labels to {args.output}; no human review implied"
            )
            return 0
        if args.command == "review-pack":
            if len(args.manifest) != len(args.repository):
                raise ValueError(
                    "Pair each --manifest with one --repository in the same order"
                )
            prepare_packet(
                list(zip(args.manifest, args.repository)),
                args.output,
                args.case,
                paired_upstream=args.paired_upstream,
                discussion=args.discussion,
            )
            print(f"Saved pinned review evidence to {args.output}; no model calls")
            return 0
        if args.command == "review-ui":
            render_review_ui(
                args.packet, args.output, args.report, labels_path=args.labels
            )
            print(f"Open {args.output.resolve()} in your browser; no server required")
            return 0
        if args.command == "evaluate-experiment":
            experiment_result = run_experiment(
                args.packet,
                args.labels,
                args.output,
                load_config(provider=args.provider, model=args.model),
                live=args.live,
                resume=args.resume,
                max_requests=args.max_requests,
                delay_seconds=args.delay_seconds,
                discussion_mode=args.discussion_mode,
            )
            print(
                f"Saved experiment to {args.output}; requests this invocation: {experiment_result['session_requests']}"
            )
            return int(
                args.live
                and any(
                    r["status"] != "completed" for r in experiment_result["results"]
                )
            )
        if args.command == "score-experiment":
            score_experiment(args.report, args.reviews, args.output)
            print(f"Saved human acceptance and validator scores to {args.output}")
            return 0
        if args.command == "benchmark-audit":
            print(json.dumps(audit_benchmark(args.manifests, args.output), indent=2))
            return 0
        if args.command == "publish-proposal":
            result_plan = publish_proposal(
                args.proposal,
                args.root,
                args.document,
                args.repository,
                args.source_pr,
                publish=args.publish,
            )
            print(json.dumps(result_plan, indent=2))
            return 0
        if args.command == "benchmark-candidates":
            candidate_report = collect_candidates(
                args.repository, args.upstream, args.output, args.limit
            )
            print(
                f"Pending review candidates saved to {args.output}; independently reviewed: {candidate_report['independently_reviewed']}"
            )
            return 0
        if args.command == "summarize-evaluation":
            summary = summarize_evaluation(args.report, args.output)
            print(json.dumps(summary, indent=2))
            return 0
        if args.command == "review-template":
            review_template(args.report, args.output)
            print(f"Unfilled human review form: {args.output}")
            return 0
        if args.command == "score-review":
            human_result = score_review(args.report, args.reviews, args.output)
            print(
                f"Reviewed {human_result['reviewed_cases']}/{human_result['completed_cases']} completed cases. Report: {args.output}"
            )
            return 0
        if args.command == "evaluate-pr":
            config = load_config(args.env_file, args.provider, args.model)
            upstream_report = evaluate_pr(
                config,
                args.repository,
                args.manifest,
                args.output,
                selected=args.case,
                live=args.live,
                max_requests=args.max_requests,
                resume=args.resume,
                max_retries=args.max_retries,
                max_retry_wait=args.max_retry_wait,
            )
            print(
                f"{upstream_report['mode']}: {upstream_report['api_requests']} API requests, {upstream_report['errors']} errors, {upstream_report['not_run']} not run. Report: {args.output}"
            )
            rows = upstream_report["results"]
            assert isinstance(rows, list)
            return int(
                bool(
                    upstream_report["errors"]
                    or upstream_report["not_run"]
                    or any(row.get("automatic_pass") is False for row in rows)
                )
            )
        if args.command == "evaluate-git":
            config = load_config(args.env_file, args.provider, args.model)
            corpus_report = evaluate_dataset(
                config,
                args.dataset,
                args.output,
                split=args.split,
                selected=args.case,
                live=args.live,
                max_requests=args.max_requests,
            )
            print(
                f"{corpus_report['mode']}: {corpus_report['passed']}/{corpus_report['total']} cases passed; {corpus_report['not_run']} not run. Report: {args.output}"
            )
            return 0 if corpus_report["passed"] == corpus_report["selected"] else 1
        if args.command == "suggest-git":
            config = load_config(args.env_file, args.provider, args.model)
            count = suggest_git(
                args.root,
                args.base,
                args.head,
                args.mapping,
                args.output,
                config,
                dry_run=args.dry_run,
                selected=args.document,
                max_documents=args.max_documents,
                evidence_policy=args.evidence_policy,
            )
            print(
                f"Saved {count} {'request payloads (no API calls)' if args.dry_run else 'Git proposals'} to {args.output}"
            )
            return 0
        if args.command == "evaluate-ai":
            config = load_config(args.env_file, args.provider, args.model)
            evaluation_report = evaluate(
                config, args.output, live=args.live, repeats=args.repeats
            )
            print(
                f"{evaluation_report['mode']}: {evaluation_report['passed']}/{evaluation_report['total']} cases passed. Report: {args.output}"
            )
            return 0 if evaluation_report["passed"] == evaluation_report["total"] else 1
        if args.command == "suggest":
            config = load_config(args.env_file, args.provider, args.model)
            count = suggest(
                args.root,
                args.baseline,
                args.mapping,
                args.output,
                model=config.model,
                provider=config.provider,
                generator=partial(
                    generate, provider=config.provider, api_key=config.api_key
                ),
                dry_run=args.dry_run,
                selected=args.document,
                max_documents=args.max_documents,
            )
            kind = "request payloads (no API calls)" if args.dry_run else "proposals"
            print(f"Saved {count} {kind} to {args.output}")
            return 0
        if args.command in {"apply-proposal", "apply-git-proposal"}:
            apply_function = (
                apply_git_proposal
                if args.command == "apply-git-proposal"
                else apply_proposal
            )
            diff = apply_function(
                args.proposal, args.root, args.document, check=args.check
            )
            print(diff, end="" if diff.endswith("\n") else "\n")
            print(
                "Preview only; no files changed."
                if args.check
                else f"Applied proposal to {args.document}"
            )
            return 0
        if args.command == "snapshot":
            # Avoid replacing a Python source file with snapshot JSON.
            if args.output.suffix.lower() == ".py":
                raise ValueError(
                    "Snapshot output must not be a Python source file (.py)"
                )
            index = index_repository(args.root)
            save_snapshot(index, args.output)
            print(f"Saved {len(index)} entities to {args.output}")
            return 0

        if args.command == "review-git":
            result = review_git(args.root, args.base, args.head, args.mapping)
            if args.summary:
                args.summary.write_text(report_summary(result.report), encoding="utf-8")
            if args.format == "json":
                document = report_document(result.report)
                document["git"] = {
                    "base": result.base,
                    "head": result.head,
                    "merge_base": result.merge_base,
                }
                print(json.dumps(document, indent=2, sort_keys=True))
            else:
                print(report_text(result.report))
            return 0 if args.advisory else int(result.report.has_findings)

        before = load_snapshot(args.baseline)
        after = index_repository(args.root)
        if args.command == "review":
            mappings = load_mapping(args.mapping, args.root)
            report = review_documents(mappings, before, after)
            if args.format == "json":
                print(json.dumps(report_document(report), indent=2, sort_keys=True))
            else:
                print(report_text(report))
            return int(report.has_findings)
        changes = compare_snapshots(before, after)
        if not (changes.added or changes.removed or changes.modified or changes.moved):
            print("No changes detected.")
            return 0
        for entity in changes.added:
            print(f"ADDED {entity.id}")
        for entity in changes.removed:
            print(f"REMOVED {entity.id}")
        for change in changes.modified:
            print(f"MODIFIED {change.after.id}: {', '.join(change.changed_fields)}")
        for change in changes.moved:
            print(
                f"MOVED {change.after.id}: lines "
                f"{change.before.start_line}-{change.before.end_line} -> "
                f"{change.after.start_line}-{change.after.end_line}"
            )
        print(
            f"{len(changes.added)} added, {len(changes.removed)} removed, "
            f"{len(changes.modified)} modified, {len(changes.moved)} moved"
        )
        return 1
    except SyntaxError as error:
        print(
            f"docguard: error: {error.filename}:{error.lineno}: {error.msg}",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError) as error:
        print(f"docguard: error: {error}", file=sys.stderr)
        return 2
