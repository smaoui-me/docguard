import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent

from docguard.code.models import EntityKind
from docguard.code.python_parser import _parse_source, parse_python_file


class TestPythonParserIds(unittest.TestCase):
    def test_overloads_and_implementation_are_all_retained(self):
        source = dedent("""\
            @overload
            def convert(value: int) -> int: ...
            @overload
            def convert(value: str) -> str: ...
            def convert(value):
                return value
        """)

        entities = _parse_source(source, "module.py")

        self.assertEqual(
            [entity.id for entity in entities],
            [
                "module.py:convert",
                "module.py:convert#2",
                "module.py:convert#3",
            ],
        )
        self.assertEqual(
            [entity.qualified_name for entity in entities], ["convert"] * 3
        )
        self.assertEqual([entity.name for entity in entities], ["convert"] * 3)
        self.assertEqual(
            [entity.return_annotation for entity in entities], ["int", "str", None]
        )
        self.assertEqual(
            [entity.decorators for entity in entities],
            [
                ("overload",),
                ("overload",),
                (),
            ],
        )
        self.assertEqual(entities, _parse_source(source, "module.py"))
        shifted = _parse_source("# Comment\n\n" + source, "module.py")
        self.assertEqual(
            [entity.id for entity in entities], [entity.id for entity in shifted]
        )

    def test_property_accessors_get_distinct_ids(self):
        source = dedent("""\
            class Client:
                @property
                def host(self):
                    return self._host
                @host.setter
                def host(self, value):
                    self._host = value
                @host.deleter
                def host(self):
                    del self._host
        """)

        entities = _parse_source(source, "module.py")

        self.assertEqual(
            [entity.id for entity in entities],
            [
                "module.py:Client",
                "module.py:Client.host",
                "module.py:Client.host#2",
                "module.py:Client.host#3",
            ],
        )
        self.assertEqual(
            [entity.decorators for entity in entities[1:]],
            [
                ("property",),
                ("host.setter",),
                ("host.deleter",),
            ],
        )

    def test_conditional_definitions_share_a_counter_across_kinds(self):
        source = dedent("""\
            if enabled:
                def handler(): pass
            else:
                async def handler(): pass
            class handler:
                pass
        """)

        entities = _parse_source(source, "module.py")

        self.assertEqual(
            [entity.id for entity in entities],
            [
                "module.py:handler",
                "module.py:handler#2",
                "module.py:handler#3",
            ],
        )
        self.assertEqual(
            [entity.kind for entity in entities],
            [
                EntityKind.FUNCTION,
                EntityKind.ASYNC_FUNCTION,
                EntityKind.CLASS,
            ],
        )

    def test_repeated_parent_definitions_and_nested_names_remain_unique(self):
        source = dedent("""\
            class Client:
                def run(self):
                    def helper(): pass
            class Client:
                def run(self):
                    def helper(): pass
            class Other:
                def run(self): pass
            def run(): pass
        """)

        entities = _parse_source(source, "module.py")

        self.assertEqual(
            [entity.id for entity in entities],
            [
                "module.py:Client",
                "module.py:Client.run",
                "module.py:Client.run.helper",
                "module.py:Client#2",
                "module.py:Client.run#2",
                "module.py:Client.run.helper#2",
                "module.py:Other",
                "module.py:Other.run",
                "module.py:run",
            ],
        )
        self.assertEqual(len({entity.id for entity in entities}), len(entities))

    def test_duplicate_counters_reset_per_file_and_parse(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for filename in ("first.py", "second.py"):
                path = root / filename
                path.write_text("def f(): pass\ndef f(): pass\n", encoding="utf-8")
                for _ in range(2):
                    with self.subTest(filename=filename):
                        entities = parse_python_file(path, repository_root=root)
                        self.assertEqual(
                            [entity.id for entity in entities],
                            [
                                f"{filename}:f",
                                f"{filename}:f#2",
                            ],
                        )

    def test_relative_and_absolute_paths_produce_identical_entities(self):
        # Keep the temporary file on the same drive as cwd for Windows relpath.
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "module.py"
            path.write_text("def greet():\n    pass\n", encoding="utf-8")
            relative_path = Path(os.path.relpath(path))

            absolute = parse_python_file(path)
            relative = parse_python_file(relative_path)

            self.assertEqual(absolute, relative)
            self.assertEqual(absolute[0].id, f"{path.resolve().as_posix()}:greet")

    def test_repository_relative_ids_survive_checkout_relocation(self):
        source = "class Client:\n    def connect(self):\n        pass\n"
        with TemporaryDirectory() as directory:
            checkouts = [
                Path(directory) / name for name in ("checkout_a", "checkout_b")
            ]
            snapshots = []
            for root in checkouts:
                path = root / "src" / "client.py"
                path.parent.mkdir(parents=True)
                path.write_text(source, encoding="utf-8")
                snapshots.append(parse_python_file(path, repository_root=root))

            self.assertEqual(snapshots[0], snapshots[1])
            self.assertEqual(
                [entity.id for entity in snapshots[0]],
                ["src/client.py:Client", "src/client.py:Client.connect"],
            )
            self.assertTrue(
                all(entity.file_path == "src/client.py" for entity in snapshots[0])
            )

    def test_relative_repository_root_and_dot_segments(self):
        with TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            (root / "src").mkdir()
            path = root / "module.py"
            path.write_text("def greet():\n    pass\n", encoding="utf-8")

            entities = parse_python_file(
                root / "src" / ".." / "module.py",
                repository_root=Path(os.path.relpath(root)),
            )

            self.assertEqual(entities[0].id, "module.py:greet")

    def test_ids_survive_line_shifts(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "module.py"
            source = "def greet():\n    pass\n"
            path.write_text(source, encoding="utf-8")
            before = parse_python_file(path, repository_root=root)[0]
            path.write_text("# Added comment\n\n" + source, encoding="utf-8")
            after = parse_python_file(path, repository_root=root)[0]

            self.assertEqual(before.id, after.id)
            self.assertEqual(after.start_line, before.start_line + 2)

    def test_same_function_in_different_files_has_different_ids(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            ids = []
            for name in ("first.py", "second.py"):
                path = root / name
                path.write_text("def greet():\n    pass\n", encoding="utf-8")
                ids.append(parse_python_file(path, repository_root=root)[0].id)

            self.assertEqual(ids, ["first.py:greet", "second.py:greet"])

    def test_file_outside_repository_is_rejected(self):
        with TemporaryDirectory() as directory:
            root = Path(directory) / "repo"
            root.mkdir()
            path = Path(directory) / "outside.py"
            path.write_text("def greet():\n    pass\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                parse_python_file(path, repository_root=root)

    def test_invalid_repository_roots(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "module.py"
            path.write_text("", encoding="utf-8")

            with self.assertRaises(FileNotFoundError):
                parse_python_file(path, repository_root=root / "missing")
            with self.assertRaises(NotADirectoryError):
                parse_python_file(path, repository_root=path)

    def test_syntax_error_uses_repository_relative_filename(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "broken.py"
            path.write_text("def broken(:\n    pass\n", encoding="utf-8")

            with self.assertRaises(SyntaxError) as raised:
                parse_python_file(path, repository_root=root)

            self.assertEqual(raised.exception.filename, "broken.py")
