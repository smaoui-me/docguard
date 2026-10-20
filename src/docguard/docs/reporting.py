"""Stable report serialization shared by local and Git review commands."""

from dataclasses import asdict
from html import escape

from docguard.docs.review import ReviewReport


def report_document(report: ReviewReport) -> dict[str, object]:
    return {
        "schema_version": 2,
        **asdict(report),
        "counts": {
            "documents": len(report.documents),
            "unmapped_added": len(report.unmapped_added),
            "removed_links": len(report.removed_links),
        },
    }


def report_text(report: ReviewReport) -> str:
    lines: list[str] = []
    for document in report.documents:
        lines.append(f"REVIEW {document.document}")
        for reason in document.reasons:
            details = (
                f": {', '.join(reason.changed_fields)}" if reason.changed_fields else ""
            )
            lines.append(f"  {reason.entity_id} {reason.change}{details}")
    for entity_id in report.unmapped_added:
        lines.append(f"UNMAPPED ADDED {entity_id}")
    for link in report.removed_links:
        lines.append(f"REMOVED LINK {link.document} -> {link.entity_id}")
    if not lines:
        return "No documentation review findings."
    lines.append(
        f"{len(report.documents)} documents to review, {len(report.unmapped_added)} unmapped additions"
    )
    if report.removed_links:
        lines.append(f"{len(report.removed_links)} documentation links removed")
    return "\n".join(lines)


def report_summary(report: ReviewReport) -> str:
    return (
        "## DocGuard documentation review\n\n<pre>"
        + escape(report_text(report))
        + "</pre>\n"
    )
