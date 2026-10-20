"""Calculate documentation impact from explicit links and metadata changes."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from docguard.code.comparison import compare_snapshots
from docguard.code.models import CodeEntity
from docguard.docs.mapping import DocumentMapping, MappingError


@dataclass(frozen=True)
class ReviewReason:
    entity_id: str
    change: str
    changed_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class DocumentReview:
    document: str
    reasons: tuple[ReviewReason, ...]


@dataclass(frozen=True)
class RemovedLink:
    document: str
    entity_id: str


@dataclass(frozen=True)
class ReviewReport:
    documents: tuple[DocumentReview, ...]
    unmapped_added: tuple[str, ...]
    removed_links: tuple[RemovedLink, ...] = ()

    @property
    def has_findings(self) -> bool:
        return bool(self.documents or self.unmapped_added or self.removed_links)


def removed_mapping_links(
    before: Sequence[DocumentMapping], after: Sequence[DocumentMapping]
) -> tuple[RemovedLink, ...]:
    """Compare explicit edges, independent of source changes or document contents."""
    old = {
        (item.document, entity_id) for item in before for entity_id in item.entity_ids
    }
    new = {
        (item.document, entity_id) for item in after for entity_id in item.entity_ids
    }
    return tuple(
        RemovedLink(document, entity_id) for document, entity_id in sorted(old - new)
    )


def review_documents(
    mappings: Sequence[DocumentMapping],
    before: Mapping[str, CodeEntity],
    after: Mapping[str, CodeEntity],
) -> ReviewReport:
    """Flag linked modifications/removals, ignore movement, list unmapped additions.

    References absent from BOTH snapshots are errors. A reference found only in
    the baseline is a removed entity, not a configuration typo.
    """
    changes = compare_snapshots(before, after)
    known = before.keys() | after.keys()
    linked: set[str] = set()
    seen_documents: set[str] = set()
    for mapping in mappings:
        if mapping.document in seen_documents:
            raise MappingError(f"Duplicate document mapping: {mapping.document}")
        seen_documents.add(mapping.document)
        for entity_id in mapping.entity_ids:
            if entity_id not in known:
                raise MappingError(
                    f"Unknown entity ID {entity_id!r} referenced by {mapping.document}"
                )
            linked.add(entity_id)
    reasons = {
        change.after.id: ReviewReason(
            change.after.id, "modified", change.changed_fields
        )
        for change in changes.modified
    }
    reasons.update(
        {entity.id: ReviewReason(entity.id, "removed") for entity in changes.removed}
    )
    documents: list[DocumentReview] = []
    for mapping in sorted(mappings, key=lambda item: item.document):
        affected = tuple(
            reasons[key] for key in sorted(set(mapping.entity_ids)) if key in reasons
        )
        if affected:
            documents.append(DocumentReview(mapping.document, affected))
    unmapped = tuple(entity.id for entity in changes.added if entity.id not in linked)
    return ReviewReport(tuple(documents), unmapped)
