"""Bounded static dependency evidence. Never import or execute inspected code."""

import ast
import json
from collections import deque
from pathlib import Path

from docguard.ai.files import digest, read_bytes, relative_path
from docguard.code.models import CodeEntity

EVIDENCE_VERSION = 1


class DependencyEvidence:
    """Resolve simple module bindings conservatively; dynamic dispatch stays unknown."""

    def __init__(self, root: Path, entities: dict[str, CodeEntity]):
        self.root = root.resolve(strict=True)
        self.entities = entities
        # Include constant-only modules without reading every module's source.
        from docguard.code.scanner import discover_python_files

        self.paths = sorted(
            {
                path.relative_to(self.root).as_posix()
                for path in discover_python_files(self.root)
            }
        )
        self.enclosed: set[int] = set()
        self.modules: dict[str, tuple[str, ast.Module, dict[str, list[ast.AST]]]] = {}

    def module(self, path: str) -> tuple[str, ast.Module, dict[str, list[ast.AST]]]:
        if path not in self.modules:
            source = read_bytes(self.root / relative_path(path)).decode("utf-8")
            tree = ast.parse(source)

            def scopes(node: ast.AST, depth: int = 0) -> None:
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
                ):
                    if depth:
                        self.enclosed.add(id(node))
                    depth += 1
                for child in ast.iter_child_nodes(node):
                    scopes(child, depth)

            scopes(tree)
            bindings: dict[str, list[ast.AST]] = {}

            # Record all competing stores, including conditional definitions.
            def visit(node: ast.AST) -> None:
                if isinstance(
                    node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
                ):
                    bindings.setdefault(node.name, []).append(node)
                    return
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        name = alias.asname or (
                            alias.name.split(".")[0]
                            if isinstance(node, ast.Import)
                            else alias.name
                        )
                        bindings.setdefault(name, []).append(node)
                    return
                if isinstance(node, ast.Name) and isinstance(
                    node.ctx, (ast.Store, ast.Del)
                ):
                    bindings.setdefault(node.id, []).append(node)
                for child in ast.iter_child_nodes(node):
                    visit(child)

            for node in tree.body:
                visit(node)
            # A unique literal assignment can be included as evidence.
            for node in tree.body:
                target = (
                    node.targets[0]
                    if isinstance(node, ast.Assign) and len(node.targets) == 1
                    else node.target
                    if isinstance(node, ast.AnnAssign)
                    else None
                )
                if (
                    isinstance(target, ast.Name)
                    and len(bindings.get(target.id, [])) == 1
                ):
                    value = (
                        node.value
                        if isinstance(node, (ast.Assign, ast.AnnAssign))
                        else None
                    )
                    if isinstance(
                        value,
                        (
                            ast.Constant,
                            ast.List,
                            ast.Tuple,
                            ast.Dict,
                            ast.Set,
                            ast.UnaryOp,
                        ),
                    ):
                        try:
                            ast.literal_eval(value)
                        except (ValueError, TypeError, RecursionError):
                            continue
                        bindings[target.id] = [node]
            self.modules[path] = source, tree, bindings
        return self.modules[path]

    def module_path(self, current: str, module: str, level: int) -> str | None:
        if level:
            parent = Path(current).parent
            for _ in range(level - 1):
                parent = parent.parent
            stem = (parent / module.replace(".", "/")).as_posix().rstrip("/")
            candidates = [
                p for p in self.paths if p in {stem + ".py", stem + "/__init__.py"}
            ]
        else:
            stem = module.replace(".", "/")
            candidates = [
                p
                for p in self.paths
                if p in {stem + ".py", stem + "/__init__.py"}
                or p.endswith("/" + stem + ".py")
                or p.endswith("/" + stem + "/__init__.py")
            ]
        return candidates[0] if len(candidates) == 1 else None

    def resolve(
        self, path: str, name: str, trail: frozenset[tuple[str, str]] = frozenset()
    ) -> tuple[str, ast.AST] | None:
        if (path, name) in trail or len(trail) >= 4:
            return None
        trail = trail | {(path, name)}
        _, tree, bindings = self.module(path)
        first, _, rest = name.partition(".")
        if "*" in bindings:
            return None
        matches = bindings.get(first, [])
        if len(matches) != 1 or matches[0] not in tree.body:
            return None  # shadowed, conditional, or dynamic assignment
        node = matches[0]
        if isinstance(node, ast.ImportFrom):
            aliases = [a for a in node.names if (a.asname or a.name) == first]
            target = self.module_path(path, node.module or "", node.level)
            if target and len(aliases) == 1:
                return self.resolve(
                    target, aliases[0].name + ("." + rest if rest else ""), trail
                )
        elif isinstance(node, ast.Import) and rest:
            alias = next(
                a for a in node.names if (a.asname or a.name.split(".")[0]) == first
            )
            target = self.module_path(path, alias.name, 0)
            suffix = (
                rest
                if alias.asname
                else name[len(alias.name) + 1 :]
                if name.startswith(alias.name + ".")
                else ""
            )
            if target and suffix:
                return self.resolve(target, suffix, trail)
        elif not rest and isinstance(
            node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Assign, ast.AnnAssign)
        ):
            return path, node
        elif not rest and isinstance(node, ast.ClassDef):
            constructors = [
                n
                for n in node.body
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == "__init__"
            ]
            if len(constructors) == 1:
                return path, constructors[0]
        return None

    def expand(
        self,
        seeds: list[str],
        side: str,
        revision: str,
        *,
        max_chars: int = 8000,
        max_items: int = 12,
        max_depth: int = 2,
    ) -> tuple[list[dict[str, object]], list[dict[str, str]]]:
        queue: deque[tuple[str, ast.AST, int]] = deque()
        seen: set[tuple[str, int]] = set()
        additions: list[dict[str, object]] = []
        issues: list[dict[str, str]] = []
        size = 0

        def issue(reference: str, reason: str) -> None:
            item = {"side": side, "reference": reference[:160], "reason": reason}
            if item not in issues:
                if len(issues) < 12:
                    issues.append(item)
                else:
                    issues[-1] = {
                        "side": side,
                        "reference": "*",
                        "reason": "additional evidence gaps omitted by report limit",
                    }

        for key in seeds:
            entity = self.entities.get(key)
            if entity is None:
                continue
            _, tree, _ = self.module(entity.file_path)
            nodes = [
                n
                for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                and n.lineno == entity.start_line
                and n.name == entity.name
            ]
            if len(nodes) == 1:
                queue.append((entity.file_path, nodes[0], 0))
                seen.add((entity.file_path, nodes[0].lineno))
        while queue:
            path, node, depth = queue.popleft()
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if isinstance(node, ast.ClassDef):
                    issue(
                        node.name,
                        "class scope; map specific methods to expand dependencies",
                    )
                continue
            if id(node) in self.enclosed:
                issue(
                    f"{path}:{node.lineno}",
                    "enclosing function scope; closure dependencies not resolved",
                )
                continue
            # Nested scopes are not part of this function's dependency walk.
            children: list[ast.AST] = []

            def visit(child: ast.AST) -> None:
                children.append(child)
                if isinstance(
                    child,
                    (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda),
                ):
                    return
                for descendant in ast.iter_child_nodes(child):
                    visit(descendant)

            for statement in node.body:
                visit(statement)
            for default in [*node.args.defaults, *node.args.kw_defaults]:
                if default is not None:
                    visit(default)
            locals_ = {
                a.arg
                for a in node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            }
            locals_.update(a.arg for a in (node.args.vararg, node.args.kwarg) if a)
            locals_.update(
                n.id
                for n in children
                if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))
            )
            locals_.update(
                n.name
                for n in children
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            )
            locals_.update(
                a.asname or a.name.split(".")[0]
                for n in children
                if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names
            )
            locals_.update(
                n.name for n in children if isinstance(n, ast.ExceptHandler) and n.name
            )
            locals_.update(
                n.name
                for n in children
                if isinstance(n, (ast.MatchAs, ast.MatchStar)) and n.name
            )
            references: set[str] = {ast.unparse(d) for d in node.decorator_list}
            for item in children:
                child = item
                if isinstance(child, ast.Call):
                    references.add(ast.unparse(child.func))
                elif (
                    isinstance(child, ast.Attribute)
                    and isinstance(child.value, ast.Name)
                    and child.value.id in self.module(path)[2]
                ):
                    references.add(ast.unparse(child))
                elif (
                    isinstance(child, ast.Name)
                    and isinstance(child.ctx, ast.Load)
                    and child.id not in locals_
                ):
                    if child.id in self.module(path)[2]:
                        references.add(child.id)
            for reference in sorted(references):
                if reference.split(".")[0] in locals_:
                    issue(reference, "local binding or dynamic dispatch; not resolved")
                    continue
                found = self.resolve(path, reference)
                if not found:
                    issue(
                        reference,
                        "external, ambiguous, conditional or unavailable dependency",
                    )
                    continue
                target, definition = found
                start = getattr(definition, "lineno", 0)
                if (target, start) in seen:
                    continue
                if depth >= max_depth:
                    issue(reference, "dependency depth limit")
                    continue
                snippet_start = min(
                    [
                        start,
                        *[d.lineno for d in getattr(definition, "decorator_list", [])],
                    ]
                )
                text = "".join(
                    self.module(target)[0].splitlines(keepends=True)[
                        snippet_start - 1 : getattr(definition, "end_lineno", start)
                    ]
                )
                matches = [
                    e
                    for e in self.entities.values()
                    if e.file_path == target and e.start_line == start
                ]
                key = (
                    matches[0].id if len(matches) == 1 else f"{target}:@binding:{start}"
                )
                entry: dict[str, object] = {
                    "id": f"{side}:{key}",
                    "revision": revision,
                    "path": target,
                    "start_line": snippet_start,
                    "end_line": getattr(definition, "end_lineno", start),
                    "text": text,
                    "sha256": digest(text.encode()),
                    "reason": f"static reference {reference} from {path}:{node.lineno}",
                }
                cost = len(json.dumps(entry, ensure_ascii=False))
                if len(additions) >= max_items or size + cost > max_chars:
                    issue(reference, "dependency context budget")
                    continue
                size += cost
                seen.add((target, start))
                additions.append(entry)
                queue.append((target, definition, depth + 1))
        return additions, issues
