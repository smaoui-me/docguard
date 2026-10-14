"""Command-line access to repository snapshots and metadata comparison."""

import argparse
import sys
from pathlib import Path

from docguard.code.comparison import compare_snapshots
from docguard.code.index import index_repository
from docguard.code.snapshots import load_snapshot, save_snapshot


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
    args = parser.parse_args(argv)
    try:
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

        before = load_snapshot(args.baseline)
        after = index_repository(args.root)
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
