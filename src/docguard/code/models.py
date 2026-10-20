from dataclasses import dataclass
from enum import Enum


class EntityKind(str, Enum):
    CLASS = "class"
    ASYNCHRONOUS_FUNCTION = "async_function"
    ASYNC_FUNCTION = "async_function"
    ASYNC_METHOD = "async_method"
    FUNCTION = "function"
    METHOD = "method"
    ASYNC_MODULE = "async_module"


class ParameterKind(str, Enum):
    POSITIONAL_ONLY = "positional_only"
    POSITIONAL_OR_KEYWORD = "positional_or_keyword"
    VAR_POSITIONAL = "var_positional"
    KEYWORD_ONLY = "keyword_only"
    VAR_KEYWORD = "var_keyword"


@dataclass(frozen=True)
class Parameter:
    name: str
    annotation: str | None
    default: str | None
    kind: ParameterKind = ParameterKind.POSITIONAL_OR_KEYWORD


@dataclass(frozen=True)
class CodeEntity:
    id: str
    name: str
    qualified_name: str
    kind: EntityKind

    file_path: str

    start_line: int
    end_line: int

    parameters: tuple[Parameter, ...]

    docstring: str | None
    decorators: tuple[str, ...]
    return_annotation: str | None = None
    body_fingerprint: str | None = None
