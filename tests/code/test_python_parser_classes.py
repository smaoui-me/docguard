import unittest
from textwrap import dedent

from docguard.code.models import EntityKind, Parameter
from docguard.code.python_parser import _parse_source


class TestPythonParserClasses(unittest.TestCase):
    def test_class_with_one_method(self):
        source = '''class Client:
    """An API client."""

    def connect(self, host: str) -> bool:
        """Connect to a host."""
        return True\n'''

        entities = _parse_source(source, file_path="example.py")

        self.assertEqual(len(entities), 2)
        entity = entities[0]
        self.assertEqual(entity.id, "example.py:Client")
        self.assertEqual(entity.name, "Client")
        self.assertEqual(entity.qualified_name, "Client")
        self.assertEqual(entity.kind, EntityKind.CLASS)
        self.assertEqual(entity.file_path, "example.py")
        self.assertEqual(entity.start_line, 1)
        self.assertEqual(entity.end_line, 6)
        self.assertEqual(entity.parameters, ())
        self.assertEqual(entity.docstring, "An API client.")
        self.assertEqual(entity.decorators, ())
        self.assertIsNone(entity.return_annotation)

        method = entities[1]
        self.assertEqual(method.id, "example.py:Client.connect")
        self.assertEqual(method.name, "connect")
        self.assertEqual(method.qualified_name, "Client.connect")
        self.assertEqual(method.kind, EntityKind.METHOD)
        self.assertEqual(method.file_path, "example.py")
        self.assertEqual((method.start_line, method.end_line), (4, 6))
        # Preserve the receiver as part of the source signature.
        self.assertEqual(
            method.parameters,
            (
                Parameter("self", None, None),
                Parameter("host", "str", None),
            ),
        )
        self.assertEqual(method.docstring, "Connect to a host.")
        self.assertEqual(method.decorators, ())
        self.assertEqual(method.return_annotation, "bool")

    def test_empty_class(self):
        entities = _parse_source("class Empty:\n    pass\n", "example.py")

        self.assertEqual(len(entities), 1)
        entity = entities[0]
        self.assertEqual(entity.qualified_name, "Empty")
        self.assertEqual(entity.kind, EntityKind.CLASS)
        self.assertEqual((entity.start_line, entity.end_line), (1, 2))
        self.assertEqual(entity.parameters, ())
        self.assertEqual(entity.decorators, ())
        self.assertIsNone(entity.docstring)
        self.assertIsNone(entity.return_annotation)

    def test_decorated_class(self):
        source = "@registered\n@dataclass(frozen=True)\nclass Record:\n    pass\n"

        entities = _parse_source(source, "example.py")

        self.assertEqual(len(entities), 1)
        self.assertEqual(
            entities[0].decorators, ("registered", "dataclass(frozen=True)")
        )
        self.assertEqual((entities[0].start_line, entities[0].end_line), (3, 4))

    def test_multiple_methods_including_async(self):
        source = dedent('''\
            class Client:
                def connect(self):
                    pass

                async def fetch(self, limit: int = 10) -> list[str]:
                    """Fetch results."""
                    return []

                def close(self):
                    pass
        ''')

        entities = _parse_source(source, "example.py")

        self.assertEqual(
            [(entity.qualified_name, entity.kind) for entity in entities],
            [
                ("Client", EntityKind.CLASS),
                ("Client.connect", EntityKind.METHOD),
                ("Client.fetch", EntityKind.ASYNC_METHOD),
                ("Client.close", EntityKind.METHOD),
            ],
        )
        method = entities[2]
        self.assertEqual(
            method.parameters,
            (
                Parameter("self", None, None),
                Parameter("limit", "int", "10"),
            ),
        )
        self.assertEqual(method.return_annotation, "list[str]")
        self.assertEqual(method.docstring, "Fetch results.")

    def test_classmethod_and_staticmethod_decorators(self):
        source = dedent("""\
            class Client:
                @classmethod
                def create(cls):
                    return cls()

                @staticmethod
                def valid(host: str) -> bool:
                    return bool(host)
        """)

        entities = _parse_source(source, "example.py")

        self.assertEqual(len(entities), 3)
        create, valid = entities[1:]
        self.assertEqual(create.qualified_name, "Client.create")
        self.assertEqual(create.kind, EntityKind.METHOD)
        self.assertEqual(create.decorators, ("classmethod",))
        self.assertEqual(valid.qualified_name, "Client.valid")
        self.assertEqual(valid.kind, EntityKind.METHOD)
        self.assertEqual(valid.decorators, ("staticmethod",))
        self.assertEqual(valid.parameters, (Parameter("host", "str", None),))

    def test_nested_class_and_scope_restoration(self):
        source = dedent("""\
            class Outer:
                class Inner:
                    def run(self):
                        pass

                def close(self):
                    pass

            def outside():
                pass
        """)

        entities = _parse_source(source, "example.py")

        self.assertEqual(
            [(entity.qualified_name, entity.kind) for entity in entities],
            [
                ("Outer", EntityKind.CLASS),
                ("Outer.Inner", EntityKind.CLASS),
                ("Outer.Inner.run", EntityKind.METHOD),
                ("Outer.close", EntityKind.METHOD),
                ("outside", EntityKind.FUNCTION),
            ],
        )
        self.assertEqual(entities[2].id, "example.py:Outer.Inner.run")

    def test_local_function_inside_method_is_not_a_method(self):
        source = dedent("""\
            class Client:
                def connect(self):
                    def helper():
                        pass
                    return helper()

                def close(self):
                    pass
        """)

        entities = _parse_source(source, "example.py")

        self.assertEqual(
            [(entity.qualified_name, entity.kind) for entity in entities],
            [
                ("Client", EntityKind.CLASS),
                ("Client.connect", EntityKind.METHOD),
                ("Client.connect.helper", EntityKind.FUNCTION),
                ("Client.close", EntityKind.METHOD),
            ],
        )
