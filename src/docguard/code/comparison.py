"""Compare entity metadata and source locations independently, matching by ID."""

from collections.abc import Mapping
from dataclasses import dataclass

from docguard.code.models import CodeEntity

METADATA_FIELDS = (
    "name",
    "qualified_name",
    "kind",
    "file_path",
    "parameters",
    "return_annotation",
    "decorators",
    "docstring",
)
LOCATION_FIELDS = ("start_line", "end_line")


@dataclass(frozen=True)
class EntityChange:
    before: CodeEntity
    after: CodeEntity
    changed_fields: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotComparison:
    added: tuple[CodeEntity, ...]
    removed: tuple[CodeEntity, ...]
    modified: tuple[EntityChange, ...]
    moved: tuple[EntityChange, ...]


def compare_snapshots(
    before: Mapping[str, CodeEntity], after: Mapping[str, CodeEntity]
) -> SnapshotComparison:
    """Return ID-sorted changes. An entity may be both modified and moved.

    Movement means changed source line bounds, not a rename or a file move.
    Body-only edits are not detectable from the current metadata model.
    """
    for index in (before, after):
        for key, entity in index.items():
            if key != entity.id:
                raise ValueError(
                    f"Index key {key!r} does not match entity ID {entity.id!r}"
                )
    added = tuple(after[key] for key in sorted(after.keys() - before.keys()))
    removed = tuple(before[key] for key in sorted(before.keys() - after.keys()))
    modified: list[EntityChange] = []
    moved: list[EntityChange] = []
    for key in sorted(before.keys() & after.keys()):
        old, new = before[key], after[key]
        metadata = tuple(
            field
            for field in METADATA_FIELDS
            if getattr(old, field) != getattr(new, field)
        )
        locations = tuple(
            field
            for field in LOCATION_FIELDS
            if getattr(old, field) != getattr(new, field)
        )
        if metadata:
            modified.append(EntityChange(old, new, metadata))
        if locations:
            moved.append(EntityChange(old, new, locations))
    return SnapshotComparison(added, removed, tuple(modified), tuple(moved))
