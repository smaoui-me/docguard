"""Mine immutable review candidates; never invent gold labels or human reviews."""

import re
from pathlib import Path

from docguard.ai.files import ProposalError, write_new_json
from docguard.ai.upstream import load_manifest
from docguard.git_review import _git


def collect_candidates(
    repository: Path, upstream: str, output: Path, limit: int = 15
) -> dict[str, object]:
    if (
        not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", upstream)
        or not 1 <= limit <= 100
    ):
        raise ProposalError("Specify owner/repository and a limit between 1 and 100")
    history = _git(
        repository,
        "log",
        "--first-parent",
        "--diff-merges=first-parent",
        "--max-count=3000",
        "--format=%x1e%H%x1f%P%x1f%s",
        "--name-only",
    ).decode("utf-8")
    candidates: list[dict[str, object]] = []
    seen: set[str] = set()
    for record in history.split("\x1e"):
        lines = record.strip().splitlines()
        if not lines:
            continue
        head, parents, title = lines[0].split("\x1f", 2)
        match = re.search(r"\(#(\d+)\)", title)
        paths = [name for name in lines[1:] if name.strip()]
        source = [
            name
            for name in paths
            if name.endswith(".py") and not name.startswith(("tests/", "test/"))
        ]
        docs = [
            name
            for name in paths
            if name.endswith((".md", ".rst"))
            and not any(
                word in name.lower() for word in ("changelog", "changes", "license")
            )
        ]
        if not match or not parents or not source or not docs or match[1] in seen:
            continue
        seen.add(match[1])
        candidates.append(
            {
                "id": upstream.replace("/", "_") + "_" + match[1],
                "repository": "https://github.com/" + upstream,
                "pr_url": f"https://github.com/{upstream}/pull/{match[1]}",
                "group": f"{upstream}#{match[1]}",
                "split": "unassigned",
                "base": parents.split()[0],
                "head": head,
                "title": title,
                "pin_basis": "integration commit and first parent; verify PR association during review",
                "provenance": "local first-parent Git history; PR number inferred from commit title",
                "source_paths": source,
                "document_paths": docs,
                "review_status": "pending",
                "expected_action": None,
                "reviewer": None,
                "independent": None,
                "rationale": None,
                "admitted": False,
            }
        )
        if len(candidates) == limit:
            break
    if len(candidates) < limit:
        raise ProposalError(
            f"Only {len(candidates)} qualifying candidates found; lower --limit or fetch more history"
        )
    result: dict[str, object] = {
        "schema_version": 1,
        "kind": "docguard.benchmark.candidates",
        "repository_head": _git(repository, "rev-parse", "HEAD").decode().strip(),
        "selection": "first-parent commits touching implementation and documentation; biased toward paired updates",
        "independently_reviewed": 0,
        "candidates": candidates,
    }
    write_new_json(output, result)
    return result


def audit_benchmark(manifests: list[Path], output: Path) -> dict[str, object]:
    """Check leakage groups across files, not just within individual manifests."""
    cases = [case for manifest in manifests for case in load_manifest(manifest)]
    ids: set[str] = set()
    splits: dict[str, str] = {}
    for case in cases:
        if case["id"] in ids:
            raise ProposalError("Duplicate case ID across manifests")
        ids.add(case["id"])
        split = case.get("split", "development")
        for key in (
            case["pr_url"],
            case["repository_url"] + ":" + case.get("group", case["pr_url"]),
        ):
            if key in splits and splits[key] != split:
                raise ProposalError(
                    "Related PR cases cross dataset splits across manifests"
                )
            splits[key] = split
    report: dict[str, object] = {
        "schema_version": 1,
        "cases": len(cases),
        "distinct_prs": len({case["pr_url"] for case in cases}),
        "repositories": sorted({case["repository_url"] for case in cases}),
        "split_consistency": True,
        "independent_labels_verified": False,
        "note": "A consistent split does not establish independence or freshness. Previously inspected cases remain regression data. Reviewers must verify pins, claims, labels, license and related PR grouping before admission.",
    }
    write_new_json(output, report)
    return report
