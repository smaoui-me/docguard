import unittest

from docguard.docs.mapping import DocumentMapping
from docguard.docs.review import RemovedLink, removed_mapping_links


class TestMappingChanges(unittest.TestCase):
    def test_ordering_and_duplicates_do_not_count_as_removal(self):
        before = (DocumentMapping("a.md", ("m.py:f", "m.py:g")),)
        after = (DocumentMapping("a.md", ("m.py:g", "m.py:f", "m.py:f")),)
        self.assertEqual(removed_mapping_links(before, after), ())

    def test_multiple_documents_keep_independent_links(self):
        before = (
            DocumentMapping("z.md", ("m.py:g", "m.py:f")),
            DocumentMapping("a.md", ("m.py:f",)),
        )
        after = (DocumentMapping("a.md", ("m.py:f",)),)
        expected = (RemovedLink("z.md", "m.py:f"), RemovedLink("z.md", "m.py:g"))
        self.assertEqual(removed_mapping_links(before, after), expected)
        self.assertEqual(
            removed_mapping_links(tuple(reversed(before)), after), expected
        )

    def test_document_rename_reports_old_link(self):
        before = (DocumentMapping("old.md", ("m.py:f",)),)
        after = (DocumentMapping("new.md", ("m.py:f",)),)
        self.assertEqual(
            removed_mapping_links(before, after), (RemovedLink("old.md", "m.py:f"),)
        )

    def test_added_links_and_empty_mappings(self):
        self.assertEqual(removed_mapping_links((), ()), ())
        self.assertEqual(
            removed_mapping_links((), (DocumentMapping("a.md", ("m.py:f",)),)), ()
        )

    def test_duplicate_entity_occurrences_are_distinct_links(self):
        before = (DocumentMapping("a.md", ("m.py:f", "m.py:f#2")),)
        after = (DocumentMapping("a.md", ("m.py:f",)),)
        self.assertEqual(
            removed_mapping_links(before, after), (RemovedLink("a.md", "m.py:f#2"),)
        )
