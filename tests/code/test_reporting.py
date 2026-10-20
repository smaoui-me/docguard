import json
import unittest

from docguard.docs.reporting import report_document, report_summary, report_text
from docguard.docs.review import DocumentReview, RemovedLink, ReviewReason, ReviewReport


class TestReporting(unittest.TestCase):
    def test_empty_json_report(self):
        report = ReviewReport((), ())
        document = json.loads(json.dumps(report_document(report)))
        self.assertEqual(
            document,
            {
                "schema_version": 2,
                "documents": [],
                "unmapped_added": [],
                "removed_links": [],
                "counts": {"documents": 0, "unmapped_added": 0, "removed_links": 0},
            },
        )
        self.assertEqual(report_text(report), "No documentation review findings.")

    def test_summary_escapes_markup(self):
        report = ReviewReport(
            (
                DocumentReview(
                    "docs/<script>.md",
                    (ReviewReason("m.py:f", "modified", ("parameters",)),),
                ),
            ),
            (),
        )
        summary = report_summary(report)
        self.assertNotIn("<script>", summary)
        self.assertIn("&lt;script&gt;", summary)
        self.assertIn("parameters", summary)

    def test_removed_link_is_a_finding_in_every_output(self):
        report = ReviewReport((), (), (RemovedLink("docs/<old>.md", "m.py:f"),))
        self.assertTrue(report.has_findings)
        self.assertFalse(ReviewReport((), ()).has_findings)
        document = json.loads(json.dumps(report_document(report)))
        self.assertEqual(
            document["removed_links"],
            [{"document": "docs/<old>.md", "entity_id": "m.py:f"}],
        )
        self.assertEqual(document["counts"]["removed_links"], 1)
        self.assertIn("REMOVED LINK docs/<old>.md -> m.py:f", report_text(report))
        self.assertNotIn("No documentation review findings", report_text(report))
        self.assertIn("docs/&lt;old&gt;.md", report_summary(report))
