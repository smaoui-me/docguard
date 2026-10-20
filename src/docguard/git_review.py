"""Review committed Git trees without switching branches or executing target code."""

import subprocess
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath, PureWindowsPath
from tempfile import TemporaryDirectory

from docguard.code.index import index_repository
from docguard.docs.mapping import load_mapping
from docguard.docs.review import ReviewReport, removed_mapping_links, review_documents


class GitReviewError(ValueError):
    """Git history or a committed tree cannot be reviewed."""


def _git(root: Path, *args: str, input_data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), *args],
            input=input_data,
            capture_output=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired as error:
        raise GitReviewError("Git command timed out") from error
    if result.returncode:
        raise GitReviewError(
            result.stderr.decode("utf-8", errors="replace").strip()
            or "Git command failed"
        )
    return result.stdout


def _relative_path(name: str) -> Path:
    relative = PurePosixPath(name)
    if (
        not name
        or name == "."
        or "\\" in name
        or ":" in name
        or relative.is_absolute()
        or PureWindowsPath(name).drive
        or ".." in relative.parts
        or relative.as_posix() != name
        or any(part.lower() == ".git" for part in relative.parts)
    ):
        raise GitReviewError(f"Unsupported repository-relative path: {name!r}")
    return Path(*relative.parts)


def _export_tree(root: Path, revision: str, destination: Path) -> None:
    """Read tracked regular blobs directly; skip symlinks and reject submodules."""
    entries: list[tuple[Path, bytes]] = []
    for record in _git(root, "ls-tree", "-r", "-z", "--full-tree", revision).split(
        b"\0"
    ):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        mode, kind, oid = metadata.split()
        if mode == b"120000":
            continue
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise GitReviewError(
                "Submodules and non-regular Git entries are not supported"
            )
        entries.append((_relative_path(raw_path.decode("utf-8")), oid))
    if not entries:
        return
    blobs = _git(
        root,
        "cat-file",
        "--batch",
        input_data=b"".join(oid + b"\n" for _, oid in entries),
    )
    offset = 0
    for relative, oid in entries:
        boundary = blobs.index(b"\n", offset)
        actual_oid, kind, raw_size = blobs[offset:boundary].split()
        size = int(raw_size)
        if actual_oid != oid or kind != b"blob":
            raise GitReviewError("Unexpected Git blob response")
        offset = boundary + 1
        path = destination / relative
        if path.exists():
            raise GitReviewError(f"Colliding paths on this filesystem: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(blobs[offset : offset + size])
        offset += size + 1


@dataclass(frozen=True)
class GitReview:
    base: str
    head: str
    merge_base: str
    report: ReviewReport


def review_git(root: Path, base: str, head: str, mapping: str) -> GitReview:
    """Review merge-base(base, head) against head, using head's committed mapping.

    Uncommitted changes and untracked files are intentionally ignored. History
    must be available locally; this function never fetches from the network.
    root must be the actual worktree root, not a directory inside another repo.
    """
    root = root.resolve(strict=True)
    discovered_root = Path(
        _git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip()
    ).resolve(strict=True)
    if root != discovered_root:
        raise GitReviewError(
            f"Expected a Git repository root: {root}; Git found parent repository "
            f"{discovered_root}. Pass that root explicitly if it is intended."
        )
    mapping_path = _relative_path(mapping)
    base_sha = (
        _git(root, "rev-parse", "--verify", "--end-of-options", f"{base}^{{commit}}")
        .decode()
        .strip()
    )
    head_sha = (
        _git(root, "rev-parse", "--verify", "--end-of-options", f"{head}^{{commit}}")
        .decode()
        .strip()
    )
    bases = _git(root, "merge-base", "--all", base_sha, head_sha).decode().splitlines()
    if len(bases) != 1:
        raise GitReviewError(
            "Expected one merge base; fetch full history or resolve ambiguous ancestry"
        )
    with TemporaryDirectory(prefix="docguard-review-") as directory:
        old, new = Path(directory) / "base", Path(directory) / "head"
        old.mkdir()
        new.mkdir()
        _export_tree(root, bases[0], old)
        _export_tree(root, head_sha, new)
        before, after = index_repository(old), index_repository(new)
        mappings = load_mapping(new / mapping_path, new)
        # The mapping may be introduced for the first time by this PR.
        baseline_mapping = old / mapping_path
        old_mappings = (
            load_mapping(baseline_mapping, old) if baseline_mapping.exists() else ()
        )
        report = review_documents(mappings, before, after)
        report = replace(
            report, removed_links=removed_mapping_links(old_mappings, mappings)
        )
    return GitReview(base_sha, head_sha, bases[0], report)
