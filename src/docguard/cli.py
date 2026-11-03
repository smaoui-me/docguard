"""Command-line access to repository snapshots and metadata comparison."""

import argparse
import json
import sys
from functools import partial
from pathlib import Path

from docguard.ai.config import load_config
from docguard.ai.dataset import evaluate_dataset
from docguard.ai.evaluation import evaluate
from docguard.ai.git_proposals import apply_git_proposal, suggest_git
from docguard.ai.proposals import apply_proposal, suggest
from docguard.ai.provider import generate
from docguard.ai.upstream import evaluate_pr
from docguard.code.comparison import compare_snapshots
from docguard.code.index import index_repository
from docguard.code.snapshots import load_snapshot, save_snapshot
from docguard.docs.mapping import load_mapping
from docguard.docs.reporting import report_document, report_summary, report_text
from docguard.docs.review import review_documents
from docguard.git_review import review_git


def main(argv: list[str] | None = None) -> int:
    """Return 0 for success/no changes, 1 for changes, and 2 for errors."""
    parser = argparse.ArgumentParser(prog="docguard", description=__doc__)
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
    upstream.add_argument("--provider", choices=("openai", "groq"))
    upstream.add_argument("--model")
    upstream.add_argument("--env-file", type=Path)
    args = parser.parse_args(argv)
    try:
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
