import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from docguard.code.comparison import compare_snapshots
from docguard.code.index import index_repository
from docguard.code.models import EntityKind, Parameter, ParameterKind
from docguard.code.python_parser import _parse_source
from docguard.code.snapshots import load_snapshot, save_snapshot


class TestSnapshotComparison(unittest.TestCase):
    def test_modified_and_moved_results_are_sorted_without_mutating_inputs(self):
        entities = _parse_source("def z(): pass\ndef a(): pass\n", "module.py")
        before = {entity.id: entity for entity in entities}
        after = {
            entity.id: replace(
                entity,
                docstring="Updated",
                start_line=entity.start_line + 1,
                end_line=entity.end_line + 1,
            )
            for entity in entities
        }
        before_copy, after_copy = dict(before), dict(after)

        result = compare_snapshots(before, after)

        self.assertEqual(
            [change.after.id for change in result.modified],
            ["module.py:a", "module.py:z"],
        )
        self.assertEqual(
            [change.after.id for change in result.moved], ["module.py:a", "module.py:z"]
        )
        self.assertEqual(before, before_copy)
        self.assertEqual(after, after_copy)

    def setUp(self):
        self.entity = _parse_source(
            "def f(value: int = 1) -> int:\n    return value\n", "module.py"
        )[0]
        self.before = {self.entity.id: self.entity}

    def test_identical_and_empty_snapshots(self):
        for before in ({}, self.before):
            result = compare_snapshots(before, before)
            self.assertEqual(
                (result.added, result.removed, result.modified, result.moved),
                ((), (), (), ()),
            )

    def test_added_removed_sorted_and_renames_are_not_inferred(self):
        new = replace(self.entity, id="module.py:g", name="g", qualified_name="g")
        other = replace(self.entity, id="module.py:a", name="a", qualified_name="a")
        result = compare_snapshots(self.before, {new.id: new, other.id: other})
        self.assertEqual(result.added, (other, new))
        self.assertEqual(result.removed, (self.entity,))
        self.assertEqual(result.modified, ())
        self.assertEqual(result.moved, ())

    def test_each_metadata_field_is_reported(self):
        cases = {
            "name": "g",
            "qualified_name": "outer.f",
            "kind": EntityKind.ASYNC_FUNCTION,
            "file_path": "other.py",
            "parameters": (Parameter("value", "str", "'x'"),),
            "return_annotation": "str",
            "decorators": ("cache",),
            "docstring": "New docs",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                new = replace(self.entity, **{field: value})
                result = compare_snapshots(self.before, {new.id: new})
                self.assertEqual(len(result.modified), 1)
                self.assertEqual(result.modified[0].changed_fields, (field,))
                self.assertEqual(result.modified[0].before, self.entity)
                self.assertEqual(result.modified[0].after, new)
                self.assertEqual(result.moved, ())

    def test_parameter_details_and_order_affect_signature(self):
        parameter = self.entity.parameters[0]
        cases = (
            (replace(parameter, name="other"),),
            (replace(parameter, annotation="str"),),
            (replace(parameter, default="2"),),
            (replace(parameter, kind=ParameterKind.KEYWORD_ONLY),),
            (),
        )
        for parameters in cases:
            with self.subTest(parameters=parameters):
                new = replace(self.entity, parameters=parameters)
                result = compare_snapshots(self.before, {new.id: new})
                self.assertEqual(result.modified[0].changed_fields, ("parameters",))
        old = replace(
            self.entity, parameters=(parameter, Parameter("other", None, None))
        )
        new = replace(old, parameters=tuple(reversed(old.parameters)))
        self.assertEqual(
            compare_snapshots({old.id: old}, {new.id: new}).modified[0].changed_fields,
            ("parameters",),
        )

    def test_line_changes_are_separate_and_can_overlap_metadata_changes(self):
        for docs in (None, "Changed documentation"):
            with self.subTest(docstring=docs):
                new = replace(self.entity, start_line=5, end_line=6, docstring=docs)
                result = compare_snapshots(self.before, {new.id: new})
                self.assertEqual(len(result.modified), int(docs is not None))
                self.assertEqual(
                    result.moved[0].changed_fields, ("start_line", "end_line")
                )
        new = replace(self.entity, end_line=3)
        self.assertEqual(
            compare_snapshots(self.before, {new.id: new}).moved[0].changed_fields,
            ("end_line",),
        )

    def test_body_only_changes_are_out_of_scope(self):
        new = _parse_source(
            "def f(value: int = 1) -> int:\n    return value + 1\n", "module.py"
        )[0]
        result = compare_snapshots(self.before, {new.id: new})
        self.assertEqual(result.modified, ())
        self.assertEqual(result.moved, ())

    def test_invalid_index_keys_are_rejected(self):
        for before, after in (
            ({"wrong": self.entity}, {}),
            ({}, {"wrong": self.entity}),
        ):
            with self.assertRaises(ValueError):
                compare_snapshots(before, after)

    def test_index_save_load_edit_compare_workflow(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            module = root / "module.py"
            module.write_text(
                "def keep(value=1):\n    pass\ndef gone(): pass\n", encoding="utf-8"
            )
            original = index_repository(root)
            path = root / "snapshot.json"
            save_snapshot(original, path)
            module.write_text(
                "# Added comment\n\ndef keep(value=2):\n    pass\ndef added(): pass\n",
                encoding="utf-8",
            )
            current = index_repository(root)
            result = compare_snapshots(load_snapshot(path), current)
            self.assertEqual(
                [entity.id for entity in result.added], ["module.py:added"]
            )
            self.assertEqual(
                [entity.id for entity in result.removed], ["module.py:gone"]
            )
            self.assertEqual(result.modified[0].changed_fields, ("parameters",))
            self.assertEqual(result.moved[0].changed_fields, ("start_line", "end_line"))
            self.assertEqual(original, load_snapshot(path))

    def test_comment_only_edit_reports_movement_without_modification(self):
        source = "def f():\n    pass\n"
        before = {entity.id: entity for entity in _parse_source(source, "module.py")}
        after = {
            entity.id: entity
            for entity in _parse_source("# Comment\n" + source, "module.py")
        }
        result = compare_snapshots(before, after)
        self.assertEqual(result.modified, ())
        self.assertEqual(len(result.moved), 1)
