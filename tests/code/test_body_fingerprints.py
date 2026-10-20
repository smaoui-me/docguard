import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.code.comparison import compare_snapshots
from docguard.code.python_parser import _parse_source
from docguard.code.snapshots import SnapshotError, load_snapshot, save_snapshot
from docguard.docs.mapping import DocumentMapping
from docguard.docs.review import review_documents


def index(source):
    return {entity.id: entity for entity in _parse_source(source, "m.py")}


class TestBodyFingerprints(unittest.TestCase):
    def test_syntax_changes_are_detected_without_line_changes(self):
        before = index("def f(price):\n    return price\n")
        for expression in ("price * 1.2", "round(price)", "0"):
            with self.subTest(expression=expression):
                after = index(f"def f(price):\n    return {expression}\n")
                result = compare_snapshots(before, after)
                self.assertEqual(result.modified[0].changed_fields, ("body",))
                self.assertEqual(result.moved, ())
        self.assertRegex(before["m.py:f"].body_fingerprint, r"^[0-9a-f]{64}$")

    def test_comments_formatting_quotes_and_redundant_parentheses_are_ignored(self):
        before = index('def f(x):\n    return x + "hello"\n')
        for source in (
            "# Comment\ndef f(x):\n    return (x + 'hello')  # Comment\n",
            "def f(x):\n    return (\n        x + 'hello'\n    )\n",
        ):
            with self.subTest(source=source):
                after = index(source)
                self.assertEqual(compare_snapshots(before, after).modified, ())

    def test_own_docstring_changes_only_report_docstring(self):
        before = index('def f():\n    """Old docs."""\n    return 1\n')
        for source in (
            'def f():\n    """New docs."""\n    return 1\n',
            "def f():\n    return 1\n",
        ):
            with self.subTest(source=source):
                result = compare_snapshots(before, index(source))
                self.assertEqual(result.modified[0].changed_fields, ("docstring",))

    def test_signature_and_decorators_are_not_part_of_body(self):
        before = index("def f(x=1):\n    return x\n")
        after = index("@cached\ndef f(x: int=2) -> int:\n    return x\n")
        self.assertEqual(
            before["m.py:f"].body_fingerprint, after["m.py:f"].body_fingerprint
        )
        self.assertEqual(
            compare_snapshots(before, after).modified[0].changed_fields,
            ("parameters", "return_annotation", "decorators"),
        )

    def test_all_function_kinds_and_class_exclusion(self):
        for prefix in ("def", "async def"):
            for in_class in (False, True):
                with self.subTest(prefix=prefix, in_class=in_class):
                    source = f"{prefix} f(x):\n    return x\n"
                    if in_class:
                        source = "class C:\n" + "".join(
                            "    " + line for line in source.splitlines(True)
                        )
                    before = index(source)
                    after = index(source.replace("return x", "return x + 1"))
                    changes = compare_snapshots(before, after)
                    self.assertEqual(len(changes.modified), 1)
                    self.assertEqual(changes.modified[0].changed_fields, ("body",))
                    if in_class:
                        self.assertIsNone(before["m.py:C"].body_fingerprint)

    def test_nested_body_changes_affect_enclosing_and_nested_function(self):
        source = "def outer():\n    def inner():\n        return 1\n    return inner\n"
        changes = compare_snapshots(
            index(source), index(source.replace("return 1", "return 2"))
        )
        self.assertEqual(
            [item.after.id for item in changes.modified],
            ["m.py:outer", "m.py:outer.inner"],
        )
        self.assertTrue(
            all(item.changed_fields == ("body",) for item in changes.modified)
        )

    def test_non_docstring_string_literal_is_part_of_body(self):
        source = 'def f():\n    x = 1\n    "old"\n    return x\n'
        changes = compare_snapshots(
            index(source), index(source.replace('"old"', '"new"'))
        )
        self.assertEqual(changes.modified[0].changed_fields, ("body",))

    def test_docstring_only_function_can_be_fingerprinted(self):
        before = index('def f():\n    """Only docs."""\n')
        after = index('def f():\n    """Changed docs."""\n')
        self.assertEqual(
            compare_snapshots(before, after).modified[0].changed_fields, ("docstring",)
        )

    def test_snapshot_round_trip_drives_document_review(self):
        before = index("def f(price):\n    return price\n")
        after = index("def f(price):\n    return price * 1.2\n")
        with TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            save_snapshot(before, path)
            restored = load_snapshot(path)
        self.assertEqual(restored, before)
        report = review_documents(
            (DocumentMapping("docs/prices.md", ("m.py:f",)),), restored, after
        )
        self.assertEqual(report.documents[0].reasons[0].changed_fields, ("body",))

    def test_v1_snapshot_requires_regeneration(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "v1.json"
            path.write_text(
                json.dumps({"schema_version": 1, "entities": []}), encoding="utf-8"
            )
            with self.assertRaisesRegex(SnapshotError, "Regenerate the baseline"):
                load_snapshot(path)
