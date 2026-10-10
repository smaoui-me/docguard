"""Parser module for extracting CodeEntity definitions from Python source code.

This module exposes a minimal public API so external callers (CLI, drift detector, tests)
never need to interact with Python's internal `ast` structures directly.
"""

import ast
from pathlib import Path

from docguard.code.models import CodeEntity, EntityKind, Parameter, ParameterKind


def parse_python_file(path: Path) -> list[CodeEntity]:
    """Parse a Python source file from disk into a list of CodeEntity objects.

    Args:
        path: Path to the .py file to inspect.

    Returns:
        A list of CodeEntity objects discovered in the file.

    Raises:
        FileNotFoundError: If the file does not exist.
        SyntaxError: If the file contains invalid Python syntax.
    """
    source_code = path.read_text(encoding="utf-8")
    return _parse_source(source_code, file_path=str(path))


def _parse_source(source: str, file_path: str) -> list[CodeEntity]:
    """Internal helper: parses source text into AST and extracts entities.

    Keeping this separate from `parse_python_file` makes testing fast
    because you can pass code strings directly in tests without disk I/O.
    """
    tree = ast.parse(source, filename=file_path)
    extractor = _EntityVisitor(file_path=file_path)
    extractor.visit(tree)
    return extractor.entities


class _EntityVisitor(ast.NodeVisitor):
    """Internal AST visitor that walks the syntax tree and collects CodeEntities."""

    def __init__(self, file_path: str) -> None:
        self.file_path = file_path
        self.entities: list[CodeEntity] = []
        self.scope_stack: list[tuple[str, bool]] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Handle synchronous function and method definitions."""
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        """Handle async function and method definitions."""
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Extract shared metadata and traverse the function's nested scope."""
        qualified_name = ".".join([name for name, _ in self.scope_stack] + [node.name])
        is_method = bool(self.scope_stack and self.scope_stack[-1][1])
        if isinstance(node, ast.AsyncFunctionDef):
            kind = EntityKind.ASYNC_METHOD if is_method else EntityKind.ASYNC_FUNCTION
        else:
            kind = EntityKind.METHOD if is_method else EntityKind.FUNCTION
        self.entities.append(
            CodeEntity(
                id=f"{self.file_path}:{qualified_name}",
                name=node.name,
                qualified_name=qualified_name,
                kind=kind,
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parameters=self._extract_parameters(node.args),
                docstring=ast.get_docstring(node),
                decorators=tuple(
                    ast.unparse(decorator) for decorator in node.decorator_list
                ),
                return_annotation=ast.unparse(node.returns) if node.returns else None,
            )
        )
        self.scope_stack.append((node.name, False))
        try:
            self.generic_visit(node)
        finally:
            self.scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """Handle class definitions."""
        qualified_name = ".".join([name for name, _ in self.scope_stack] + [node.name])
        self.entities.append(
            CodeEntity(
                id=f"{self.file_path}:{qualified_name}",
                name=node.name,
                qualified_name=qualified_name,
                kind=EntityKind.CLASS,
                file_path=self.file_path,
                start_line=node.lineno,
                end_line=node.end_lineno or node.lineno,
                parameters=(),
                docstring=ast.get_docstring(node),
                decorators=tuple(
                    ast.unparse(decorator) for decorator in node.decorator_list
                ),
            )
        )
        self.scope_stack.append((node.name, True))
        try:
            self.generic_visit(node)
        finally:
            self.scope_stack.pop()

    def _extract_parameters(self, args: ast.arguments) -> tuple[Parameter, ...]:
        """Helper to convert an ast.arguments node into a tuple of Parameter objects."""
        positional = args.posonlyargs + args.args
        defaults = [None] * (len(positional) - len(args.defaults)) + args.defaults
        arguments: list[tuple[ast.arg, ast.expr | None, ParameterKind]] = [
            (
                argument,
                default,
                ParameterKind.POSITIONAL_ONLY
                if index < len(args.posonlyargs)
                else ParameterKind.POSITIONAL_OR_KEYWORD,
            )
            for index, (argument, default) in enumerate(zip(positional, defaults))
        ]
        if args.vararg:
            arguments.append((args.vararg, None, ParameterKind.VAR_POSITIONAL))
        arguments.extend(
            (argument, default, ParameterKind.KEYWORD_ONLY)
            for argument, default in zip(args.kwonlyargs, args.kw_defaults)
        )
        if args.kwarg:
            arguments.append((args.kwarg, None, ParameterKind.VAR_KEYWORD))
        return tuple(
            Parameter(
                name=argument.arg,
                annotation=ast.unparse(argument.annotation)
                if argument.annotation
                else None,
                default=ast.unparse(default) if default is not None else None,
                kind=kind,
            )
            for argument, default, kind in arguments
        )
