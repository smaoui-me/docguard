import unittest
from dataclasses import replace

from docguard.code.python_parser import _parse_source
from docguard.docs.mapping import DocumentMapping, MappingError
from docguard.docs.review import review_documents


def index(source):
    return {entity.id: entity for entity in _parse_source(source, "m.py")}


class TestDocumentReview(unittest.TestCase):
    def test_many_to_many_links_and_deterministic_reasons(self):
        before = index("def f(x=1): pass\ndef g(): pass\n")
        after = index("def f(x=2): pass\n")
        mappings = (
            DocumentMapping("z.md", ("m.py:g", "m.py:f")),
            DocumentMapping("a.md", ("m.py:f",)),
        )
        report = review_documents(mappings, before, after)
        self.assertEqual([item.document for item in report.documents], ["a.md", "z.md"])
        self.assertEqual(
            [
                (r.entity_id, r.change, r.changed_fields)
                for r in report.documents[1].reasons
            ],
            [
                ("m.py:f", "modified", ("parameters",)),
                ("m.py:g", "removed", ()),
            ],
        )
        self.assertEqual(report.unmapped_added, ())
        self.assertEqual(
            report, review_documents(tuple(reversed(mappings)), before, after)
        )

    def test_each_metadata_change_flags_document(self):
        before = index("def f(x=1): pass\n")
        entity = before["m.py:f"]
        cases = {
            "docstring": "New docs",
            "decorators": ("cache",),
            "return_annotation": "int",
            "parameters": (),
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                after = {entity.id: replace(entity, **{field: value})}
                report = review_documents(
                    (DocumentMapping("a.md", (entity.id,)),), before, after
                )
                self.assertEqual(
                    report.documents[0].reasons[0].changed_fields, (field,)
                )

    def test_line_only_and_unchanged_entities_do_not_flag_documents(self):
        source = "def f(): pass\n"
        before = index(source)
        for prefix in ("", "# Comment\n\n"):
            with self.subTest(prefix=prefix):
                report = review_documents(
                    (DocumentMapping("a.md", ("m.py:f",)),),
                    before,
                    index(prefix + source),
                )
                self.assertEqual(report.documents, ())
                self.assertEqual(report.unmapped_added, ())

    def test_unknown_reference_is_distinct_from_removed(self):
        before = index("def f(): pass\n")
        with self.assertRaisesRegex(MappingError, "Unknown entity ID.*typo"):
            review_documents((DocumentMapping("a.md", ("m.py:typo",)),), before, {})
        report = review_documents((DocumentMapping("a.md", ("m.py:f",)),), before, {})
        self.assertEqual(report.documents[0].reasons[0].change, "removed")

    def test_only_unmapped_new_entities_are_listed(self):
        before = index("def existing(): pass\n")
        after = index(
            "def existing(x): pass\ndef z(): pass\ndef a(): pass\ndef linked(): pass\n"
        )
        report = review_documents(
            (DocumentMapping("a.md", ("m.py:linked",)),), before, after
        )
        self.assertEqual(report.documents, ())
        self.assertEqual(report.unmapped_added, ("m.py:a", "m.py:z"))

    def test_duplicate_occurrence_reference(self):
        before = index("def f(): pass\ndef f(x=1): pass\n")
        after = index("def f(): pass\ndef f(x=2): pass\n")
        report = review_documents(
            (DocumentMapping("a.md", ("m.py:f#2",)),), before, after
        )
        self.assertEqual(report.documents[0].reasons[0].entity_id, "m.py:f#2")

    def test_duplicate_document_mapping_rejected(self):
        mapping = DocumentMapping("a.md", ("m.py:f",))
        before = index("def f(): pass")
        with self.assertRaisesRegex(MappingError, "Duplicate document"):
            review_documents((mapping, mapping), before, before)

    def test_empty_inputs(self):
        report = review_documents((), {}, {})
        self.assertEqual((report.documents, report.unmapped_added), ((), ()))
