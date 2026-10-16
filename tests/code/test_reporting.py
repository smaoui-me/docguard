import json
import unittest

from docguard.docs.reporting import report_document, report_summary, report_text
from docguard.docs.review import DocumentReview, ReviewReason, ReviewReport


class TestReporting(unittest.TestCase):
    def test_empty_json_report(self):
        report = ReviewReport((), ())
        document = json.loads(json.dumps(report_document(report)))
        self.assertEqual(
            document,
            {
                "schema_version": 1,
                "documents": [],
                "unmapped_added": [],
                "counts": {"documents": 0, "unmapped_added": 0},
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
