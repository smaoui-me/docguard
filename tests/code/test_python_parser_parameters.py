import unittest

from docguard.code.models import Parameter, ParameterKind
from docguard.code.python_parser import _parse_source


class TestPythonParserParameters(unittest.TestCase):
    def test_all_kinds_in_sync_and_async_functions(self):
        expected = (
            Parameter("a", "int", None, ParameterKind.POSITIONAL_ONLY),
            Parameter("b", "int", "10", ParameterKind.POSITIONAL_OR_KEYWORD),
            Parameter("args", "str", None, ParameterKind.VAR_POSITIONAL),
            Parameter("required", "bool", None, ParameterKind.KEYWORD_ONLY),
            Parameter("optional", "str | None", "None", ParameterKind.KEYWORD_ONLY),
            Parameter("kwargs", "object", None, ParameterKind.VAR_KEYWORD),
        )
        for prefix in ("def", "async def"):
            with self.subTest(prefix=prefix):
                source = (
                    f"{prefix} example(a: int, /, b: int = 10, *args: str, "
                    "required: bool, optional: str | None = None, **kwargs: object):\n"
                    "    pass\n"
                )
                entities = _parse_source(source, "example.py")
                self.assertEqual(len(entities), 1)
                self.assertEqual(entities[0].parameters, expected)

    def test_same_parameter_name_can_have_different_kinds(self):
        cases = (
            ("value, /", ParameterKind.POSITIONAL_ONLY),
            ("value", ParameterKind.POSITIONAL_OR_KEYWORD),
            ("*value", ParameterKind.VAR_POSITIONAL),
            ("*, value", ParameterKind.KEYWORD_ONLY),
            ("**value", ParameterKind.VAR_KEYWORD),
        )
        for signature, kind in cases:
            with self.subTest(signature=signature):
                entities = _parse_source(
                    f"def f({signature}):\n    pass\n", "example.py"
                )
                self.assertEqual(
                    entities[0].parameters, (Parameter("value", None, None, kind),)
                )

    def test_defaults_cross_positional_only_boundary(self):
        source = "def f(a, b=10, /, c=20, *, required, optional=None):\n    pass\n"

        parameters = _parse_source(source, "example.py")[0].parameters

        self.assertEqual(
            parameters,
            (
                Parameter("a", None, None, ParameterKind.POSITIONAL_ONLY),
                Parameter("b", None, "10", ParameterKind.POSITIONAL_ONLY),
                Parameter("c", None, "20", ParameterKind.POSITIONAL_OR_KEYWORD),
                Parameter("required", None, None, ParameterKind.KEYWORD_ONLY),
                Parameter("optional", None, "None", ParameterKind.KEYWORD_ONLY),
            ),
        )

    def test_keyword_only_defaults_stay_with_their_parameters(self):
        source = "def f(*, first=0, required, last=False):\n    pass\n"

        parameters = _parse_source(source, "example.py")[0].parameters

        self.assertEqual(
            parameters,
            (
                Parameter("first", None, "0", ParameterKind.KEYWORD_ONLY),
                Parameter("required", None, None, ParameterKind.KEYWORD_ONLY),
                Parameter("last", None, "False", ParameterKind.KEYWORD_ONLY),
            ),
        )

    def test_method_receivers_are_preserved_with_their_kinds(self):
        for prefix in ("def", "async def"):
            for receiver, decorator in (("self", ""), ("cls", "    @classmethod\n")):
                with self.subTest(prefix=prefix, receiver=receiver):
                    source = (
                        f"class Client:\n{decorator}"
                        f"    {prefix} connect({receiver}, /, host: str, *, secure=True):\n"
                        "        pass\n"
                    )
                    entities = _parse_source(source, "example.py")
                    self.assertEqual(len(entities), 2)
                    self.assertEqual(
                        entities[1].parameters,
                        (
                            Parameter(
                                receiver, None, None, ParameterKind.POSITIONAL_ONLY
                            ),
                            Parameter(
                                "host", "str", None, ParameterKind.POSITIONAL_OR_KEYWORD
                            ),
                            Parameter(
                                "secure", None, "True", ParameterKind.KEYWORD_ONLY
                            ),
                        ),
                    )
