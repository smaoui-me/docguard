import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from textwrap import dedent

from docguard.code.models import EntityKind, Parameter, ParameterKind
from docguard.code.python_parser import _parse_source, parse_python_file


class TestPythonParserFunctions(unittest.TestCase):
    def test_simple_function(self):
        source = 'def greet(name):\n    """Greet a person."""\n    return f"Hello, {name}!"\n'

        entities = _parse_source(source, file_path="example.py")

        self.assertEqual(len(entities), 1)
        entity = entities[0]
        self.assertEqual(entity.id, "example.py:greet")
        self.assertEqual(entity.name, "greet")
        self.assertEqual(entity.qualified_name, "greet")
        self.assertEqual(entity.kind, EntityKind.FUNCTION)
        self.assertEqual(entity.file_path, "example.py")
        self.assertEqual(entity.start_line, 1)
        self.assertEqual(entity.end_line, 3)
        self.assertEqual(entity.parameters, (Parameter("name", None, None),))
        self.assertEqual(entity.docstring, "Greet a person.")
        self.assertEqual(entity.decorators, ())
        self.assertIsNone(entity.return_annotation)

    def test_function_with_decorators_and_parameter_types(self):
        # This source is parsed, not executed, so the decorators need no imports.
        source = dedent('''\
            @logged
            @retry(attempts=3)
            def greet(
                name: str,
                /,
                greeting: str = "Hello",
                *extra_names: str,
                uppercase: bool,
                punctuation: str = "!",
                **options: str,
            ) -> str:
                """Greet several people with configurable formatting."""
                message = f"{greeting}, {', '.join((name, *extra_names))}{punctuation}"
                return message.upper() if uppercase else message
        ''')

        entities = _parse_source(source, file_path="example.py")

        self.assertEqual(len(entities), 1)
        entity = entities[0]
        self.assertEqual(entity.id, "example.py:greet")
        self.assertEqual(entity.name, "greet")
        self.assertEqual(entity.qualified_name, "greet")
        self.assertEqual(entity.kind, EntityKind.FUNCTION)
        self.assertEqual(entity.file_path, "example.py")
        # The AST starts the function at `def`, after its decorators.
        self.assertEqual(entity.start_line, 3)
        self.assertEqual(entity.end_line, 14)
        self.assertEqual(
            entity.parameters,
            (
                Parameter("name", "str", None, ParameterKind.POSITIONAL_ONLY),
                Parameter("greeting", "str", "'Hello'"),
                Parameter("extra_names", "str", None, ParameterKind.VAR_POSITIONAL),
                Parameter("uppercase", "bool", None, ParameterKind.KEYWORD_ONLY),
                Parameter("punctuation", "str", "'!'", ParameterKind.KEYWORD_ONLY),
                Parameter("options", "str", None, ParameterKind.VAR_KEYWORD),
            ),
        )
        self.assertEqual(
            entity.docstring,
            "Greet several people with configurable formatting.",
        )
        self.assertEqual(entity.decorators, ("logged", "retry(attempts=3)"))
        self.assertEqual(entity.return_annotation, "str")

    def test_function_without_parameters_or_metadata(self):
        entities = _parse_source("def ping():\n    pass\n", "example.py")

        self.assertEqual(len(entities), 1)
        entity = entities[0]
        self.assertEqual(entity.parameters, ())
        self.assertEqual(entity.decorators, ())
        self.assertIsNone(entity.docstring)
        self.assertIsNone(entity.return_annotation)

    def test_positional_defaults_align_with_last_parameters(self):
        source = "def configure(required, count: int = 10, retries=20):\n    pass\n"

        entities = _parse_source(source, "example.py")

        self.assertEqual(len(entities), 1)
        self.assertEqual(
            entities[0].parameters,
            (
                Parameter("required", None, None),
                Parameter("count", "int", "10"),
                Parameter("retries", None, "20"),
            ),
        )

    def test_positional_only_defaults(self):
        entities = _parse_source(
            "def configure(a, b=10, /, c=20):\n    pass\n",
            "example.py",
        )

        self.assertEqual(
            entities[0].parameters,
            (
                Parameter("a", None, None, ParameterKind.POSITIONAL_ONLY),
                Parameter("b", None, "10", ParameterKind.POSITIONAL_ONLY),
                Parameter("c", None, "20"),
            ),
        )

    def test_required_keyword_only_and_explicit_none_default(self):
        source = "def configure(*, required, optional: str | None = None):\n    pass\n"

        entities = _parse_source(source, "example.py")

        # None means absent; the string "None" means an explicit Python default.
        self.assertEqual(
            entities[0].parameters,
            (
                Parameter("required", None, None, ParameterKind.KEYWORD_ONLY),
                Parameter("optional", "str | None", "None", ParameterKind.KEYWORD_ONLY),
            ),
        )

    def test_false_and_zero_defaults_are_preserved(self):
        entities = _parse_source(
            "def configure(enabled=False, count=0):\n    pass\n",
            "example.py",
        )

        self.assertEqual(
            entities[0].parameters,
            (
                Parameter("enabled", None, "False"),
                Parameter("count", None, "0"),
            ),
        )

    def test_variadic_parameters(self):
        entities = _parse_source(
            "def collect(*args: int, **kwargs: str):\n    pass\n",
            "example.py",
        )

        self.assertEqual(
            entities[0].parameters,
            (
                Parameter("args", "int", None, ParameterKind.VAR_POSITIONAL),
                Parameter("kwargs", "str", None, ParameterKind.VAR_KEYWORD),
            ),
        )

    def test_async_function_metadata_matches_sync_function(self):
        source = dedent('''\
            @logged
            def fetch(url: str, timeout: int = 30) -> bytes:
                """Fetch a resource."""
                return b""
        ''')
        sync = _parse_source(source, "example.py")[0]
        async_entity = _parse_source(
            source.replace("def fetch", "async def fetch"), "example.py"
        )[0]

        self.assertEqual(sync.kind, EntityKind.FUNCTION)
        self.assertEqual(async_entity.kind, EntityKind.ASYNC_FUNCTION)
        for field in (
            "id",
            "name",
            "qualified_name",
            "file_path",
            "start_line",
            "end_line",
            "parameters",
            "return_annotation",
            "docstring",
            "decorators",
        ):
            with self.subTest(field=field):
                self.assertEqual(getattr(async_entity, field), getattr(sync, field))

    def test_nested_function_and_scope_restoration(self):
        source = dedent("""\
            def outer():
                def inner():
                    pass
                return inner

            def sibling():
                pass
        """)

        entities = _parse_source(source, "example.py")

        self.assertEqual(
            [entity.qualified_name for entity in entities],
            [
                "outer",
                "outer.inner",
                "sibling",
            ],
        )
        self.assertTrue(all(entity.kind == EntityKind.FUNCTION for entity in entities))
        self.assertEqual(entities[1].id, "example.py:outer.inner")

    def test_sources_without_entities(self):
        for source in (
            "",
            "# Only a comment\n",
            '"""Module docs."""\n',
            "value = 42\n",
        ):
            with self.subTest(source=source):
                self.assertEqual(_parse_source(source, "example.py"), [])

    def test_invalid_source_raises_syntax_error(self):
        with self.assertRaises(SyntaxError) as raised:
            _parse_source("def broken(:\n    pass\n", "broken.py")

        self.assertEqual(raised.exception.filename, "broken.py")

    def test_file_parsing_is_utf8_and_deterministic(self):
        source = 'def greet():\n    """Bonjour, caf\u00e9!"""\n    pass\n\ndef goodbye():\n    pass\n'
        with TemporaryDirectory() as directory:
            path = Path(directory) / "example.py"
            path.write_text(source, encoding="utf-8")

            first = parse_python_file(path)
            second = parse_python_file(path)

        self.assertEqual(first, second)
        self.assertEqual(
            [entity.id for entity in first],
            [
                f"{path}:greet",
                f"{path}:goodbye",
            ],
        )
        self.assertTrue(all(entity.file_path == str(path) for entity in first))
        self.assertEqual(first[0].docstring, "Bonjour, caf\u00e9!")

    def test_missing_file_raises_file_not_found(self):
        with TemporaryDirectory() as directory:
            with self.assertRaises(FileNotFoundError):
                parse_python_file(Path(directory) / "missing.py")

    def test_invalid_file_preserves_syntax_error_location(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "broken.py"
            path.write_text("def broken(:\n    pass\n", encoding="utf-8")

            with self.assertRaises(SyntaxError) as raised:
                parse_python_file(path)

            self.assertEqual(raised.exception.filename, str(path))
            self.assertEqual(raised.exception.lineno, 1)

    def test_source_is_not_executed(self):
        source = dedent("""\
            raise RuntimeError("Must not execute")

            @unknown_decorator
            def example(value=unknown_factory()):
                pass
        """)

        entities = _parse_source(source, "example.py")

        self.assertEqual(len(entities), 1)
        self.assertEqual(entities[0].decorators, ("unknown_decorator",))
        self.assertEqual(
            entities[0].parameters, (Parameter("value", None, "unknown_factory()"),)
        )
