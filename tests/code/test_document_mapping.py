import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.docs.mapping import DocumentMapping, MappingError, load_mapping


class TestDocumentMapping(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.root = self.base / "repo"
        (self.root / "docs").mkdir(parents=True)
        (self.root / "docs/a.md").write_text("Café documentation", encoding="utf-8")
        (self.root / "docs/b.md").touch()
        self.path = self.base / "mapping.json"

    def write(self, documents):
        self.path.write_text(
            json.dumps({"schema_version": 1, "documents": documents}), encoding="utf-8"
        )

    def test_mapping_sorted_and_paths_relative_to_root_not_mapping_file(self):
        self.write({"docs/b.md": ["m.py:z", "m.py:a"], "docs/a.md": ["m.py:a"]})
        self.assertEqual(
            load_mapping(self.path, self.root),
            (
                DocumentMapping("docs/a.md", ("m.py:a",)),
                DocumentMapping("docs/b.md", ("m.py:a", "m.py:z")),
            ),
        )

    def test_empty_mapping(self):
        self.write({})
        self.assertEqual(load_mapping(self.path, self.root), ())

    def test_invalid_schema(self):
        cases = [
            [],
            {},
            {"schema_version": 1, "documents": []},
            {"schema_version": 1, "documents": {}, "extra": 0},
        ]
        cases.extend(
            {"schema_version": version, "documents": {}}
            for version in (True, 2, "1", None)
        )
        for case in cases:
            with self.subTest(case=case):
                self.path.write_text(json.dumps(case), encoding="utf-8")
                with self.assertRaises(MappingError):
                    load_mapping(self.path, self.root)

    def test_invalid_references(self):
        for ids in ([], "m.py:f", [None], [1], [""], ["   "], ["m.py:f", "m.py:f"]):
            with self.subTest(ids=ids):
                self.write({"docs/a.md": ids})
                with self.assertRaises(MappingError):
                    load_mapping(self.path, self.root)

    def test_invalid_document_paths(self):
        for document in (
            "",
            ".",
            "../outside.md",
            "/absolute.md",
            "C:/absolute.md",
            "C:relative.md",
            "docs\\a.md",
            "./docs/a.md",
            "docs//a.md",
            "docs/../docs/a.md",
            "docs/missing.md",
            "docs",
        ):
            with self.subTest(document=document):
                self.write({document: ["m.py:f"]})
                with self.assertRaises(MappingError):
                    load_mapping(self.path, self.root)

    def test_malformed_encoding_json_and_duplicate_keys(self):
        for raw in (
            b"{",
            b"\xff",
            b'{"schema_version":1,"schema_version":1,"documents":{}}',
            b'{"schema_version":1,"documents":{"docs/a.md":["x"],"docs/a.md":["y"]}}',
        ):
            with self.subTest(raw=raw):
                self.path.write_bytes(raw)
                with self.assertRaises(MappingError):
                    load_mapping(self.path, self.root)

    def test_missing_mapping_and_invalid_root(self):
        with self.assertRaises(FileNotFoundError):
            load_mapping(self.path, self.root)
        self.write({})
        with self.assertRaises(FileNotFoundError):
            load_mapping(self.path, self.root / "missing")
        with self.assertRaises(NotADirectoryError):
            load_mapping(self.path, self.root / "docs/a.md")

    def test_symlink_escape_is_rejected(self):
        outside = self.base / "outside.md"
        outside.touch()
        try:
            (self.root / "docs/link.md").symlink_to(outside)
        except OSError as error:
            self.skipTest(f"Symlinks unavailable: {error}")
        self.write({"docs/link.md": ["m.py:f"]})
        with self.assertRaisesRegex(MappingError, "outside repository"):
            load_mapping(self.path, self.root)
