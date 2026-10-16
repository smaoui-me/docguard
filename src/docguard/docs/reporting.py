"""Stable report serialization shared by local and Git review commands."""

from dataclasses import asdict
from html import escape

from docguard.docs.review import ReviewReport


def report_document(report: ReviewReport) -> dict[str, object]:
    return {
        "schema_version": 1,
        **asdict(report),
        "counts": {
            "documents": len(report.documents),
            "unmapped_added": len(report.unmapped_added),
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
    if not lines:
        return "No documentation review findings."
    lines.append(
        f"{len(report.documents)} documents to review, {len(report.unmapped_added)} unmapped additions"
    )
    return "\n".join(lines)


def report_summary(report: ReviewReport) -> str:
    return (
        "## DocGuard documentation review\n\n<pre>"
        + escape(report_text(report))
        + "</pre>\n"
    )
