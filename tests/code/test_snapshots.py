import copy
import json
import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent
from unittest.mock import patch

from docguard.code.models import EntityKind, ParameterKind
from docguard.code.python_parser import _parse_source
from docguard.code.snapshots import SnapshotError, load_snapshot, save_snapshot


class TestSnapshots(unittest.TestCase):
    def setUp(self):
        source = dedent('''\
            @decorated
            class Client:
                """Café client."""
                async def fetch(self, /, url: str, *args: int, required, option=None, **kwargs: str) -> bytes:
                    """Fetch bytes."""
                    return b""
                def close(self): pass
            def f(): pass
            async def f(): pass
        ''')
        self.index = {
            entity.id: entity for entity in _parse_source(source, "src/client.py")
        }

    def test_round_trip_preserves_every_field_and_domain_types(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            save_snapshot(self.index, path)
            restored = load_snapshot(path)
            self.assertEqual(restored, self.index)
            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8"))["schema_version"], 2
            )
            self.assertIn("Café", path.read_text(encoding="utf-8"))
            for entity in restored.values():
                self.assertIsInstance(entity.kind, EntityKind)
                self.assertIsInstance(entity.parameters, tuple)
                self.assertIsInstance(entity.decorators, tuple)
                for parameter in entity.parameters:
                    self.assertIsInstance(parameter.kind, ParameterKind)

    def test_serialization_is_deterministic_and_empty_index_round_trips(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            save_snapshot(self.index, path)
            original = path.read_bytes()
            save_snapshot(dict(reversed(list(self.index.items()))), path)
            self.assertEqual(path.read_bytes(), original)
            save_snapshot({}, path)
            self.assertEqual(load_snapshot(path), {})

    def test_rejects_invalid_documents(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            save_snapshot(self.index, path)
            baseline = json.loads(path.read_text(encoding="utf-8"))
            cases = []
            for version in (1, 3, True, "2", None):
                cases.append({**baseline, "schema_version": version})
            cases.extend(
                [[], {}, {**baseline, "extra": 1}, {**baseline, "entities": {}}]
            )
            for field, value in (
                ("kind", "unknown"),
                ("start_line", True),
                ("start_line", 0),
                ("end_line", 0),
                ("name", 7),
                ("decorators", [None]),
                ("parameters", {}),
                ("docstring", 9),
                ("return_annotation", 7),
                ("body_fingerprint", 42),
                ("body_fingerprint", "invalid"),
                ("body_fingerprint", "A" * 64),
            ):
                document = copy.deepcopy(baseline)
                document["entities"][0][field] = value
                cases.append(document)
            document = copy.deepcopy(baseline)
            del document["entities"][0]["name"]
            cases.append(document)
            document = copy.deepcopy(baseline)
            document["entities"].append(document["entities"][0])
            cases.append(document)
            document = copy.deepcopy(baseline)
            method = next(item for item in document["entities"] if item["parameters"])
            method["parameters"][0]["kind"] = "unknown"
            cases.append(document)
            document = copy.deepcopy(baseline)
            document["entities"][0].update(start_line=10, end_line=5)
            cases.append(document)
            for number, document in enumerate(cases):
                with self.subTest(case=number):
                    path.write_text(json.dumps(document), encoding="utf-8")
                    with self.assertRaises(SnapshotError):
                        load_snapshot(path)

    def test_invalid_json_encoding_and_duplicate_keys(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            for content in (
                b"{",
                b"\xff",
                b'{"schema_version":1,"schema_version":1,"entities":[]}',
            ):
                with self.subTest(content=content):
                    path.write_bytes(content)
                    with self.assertRaises(SnapshotError):
                        load_snapshot(path)

    def test_missing_file_propagates(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                load_snapshot(Path(directory) / "missing.json")

    def test_bad_index_does_not_replace_existing_snapshot(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            save_snapshot(self.index, path)
            original = path.read_bytes()
            entity = next(iter(self.index.values()))
            for bad in ({"wrong": entity}, {entity.id: replace(entity, start_line=0)}):
                with self.assertRaises(SnapshotError):
                    save_snapshot(bad, path)
                self.assertEqual(path.read_bytes(), original)

    def test_failed_replacement_preserves_destination_and_cleans_temporary_file(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "snapshot.json"
            save_snapshot(self.index, path)
            original = path.read_bytes()
            with (
                patch(
                    "docguard.code.snapshots.os.replace",
                    side_effect=PermissionError("denied"),
                ),
                self.assertRaises(PermissionError),
            ):
                save_snapshot({}, path)
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(Path(directory).iterdir()), [path])
