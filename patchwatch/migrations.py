"""Small, syntax-aware migration recipes; ambiguity is an explicit outcome."""

import ast
from dataclasses import dataclass

from patchwatch.errors import PatchwatchError

GUIDES = {
    "pydantic": "https://docs.pydantic.dev/latest/migration/",
    "sqlalchemy": "https://docs.sqlalchemy.org/en/20/changelog/migration_20.html",
    "requests": "https://requests.readthedocs.io/en/latest/community/updates/",
    "pytest": "https://docs.pytest.org/en/stable/changelog.html",
    "fastapi": "https://fastapi.tiangolo.com/release-notes/",
}


@dataclass
class Edit:
    start: int
    end: int
    text: str


class Source:
    def __init__(self, text: str):
        self.text = text
        self.lines = text.splitlines(keepends=True)
        self.edits: list[Edit] = []

    def offset(self, line: int, column: int) -> int:
        return sum(len(x) for x in self.lines[: line - 1]) + len(
            self.lines[line - 1].encode()[:column].decode()
        )

    def replace(self, node: ast.AST, text: str) -> None:
        assert isinstance(node, (ast.stmt, ast.expr, ast.alias))
        assert node.end_lineno is not None and node.end_col_offset is not None
        self.edits.append(
            Edit(
                self.offset(node.lineno, node.col_offset),
                self.offset(node.end_lineno, node.end_col_offset),
                text,
            )
        )

    def result(self) -> str:
        result = self.text
        last_start = len(result) + 1
        for edit in sorted(self.edits, key=lambda e: e.start, reverse=True):
            if edit.end > last_start:
                raise PatchwatchError(
                    "AMBIGUOUS_MIGRATION", "Overlapping transformations require review."
                )
            result = result[: edit.start] + edit.text + result[edit.end :]
            last_start = edit.start
        ast.parse(result)
        return result


def pydantic_v2(text: str) -> str:
    tree = ast.parse(text)
    imports = [
        n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module == "pydantic"
    ]
    if not imports:
        return text
    imported = {alias.name for node in imports for alias in node.names}
    if any(alias.asname for node in imports for alias in node.names):
        raise PatchwatchError(
            "AMBIGUOUS_MIGRATION", "Aliased Pydantic imports require manual review."
        )
    if (
        imported & {"root_validator", "BaseSettings", "GenericModel", "validator"}
        and "BaseModel" not in imported
    ):
        raise PatchwatchError("AMBIGUOUS_MIGRATION", "Unsupported Pydantic model/import pattern.")
    if imported & {"root_validator", "BaseSettings", "GenericModel"}:
        raise PatchwatchError(
            "AMBIGUOUS_MIGRATION",
            "Root validators, settings, and generic models need a dedicated migration.",
        )
    source = Source(text)
    models = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef)
        and any(isinstance(b, ast.Name) and b.id == "BaseModel" for b in n.bases)
    ]
    needs_config = False
    used_validator = False
    for model in models:
        for node in model.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for decorator in node.decorator_list:
                    if not (
                        isinstance(decorator, ast.Call)
                        and isinstance(decorator.func, ast.Name)
                        and decorator.func.id == "validator"
                    ):
                        continue
                    if not decorator.args or not all(
                        isinstance(a, ast.Constant) and isinstance(a.value, str)
                        for a in decorator.args
                    ):
                        raise PatchwatchError(
                            "AMBIGUOUS_MIGRATION", "Dynamic validator fields require review."
                        )
                    if any(
                        k.arg not in {"pre", "allow_reuse"}
                        or not isinstance(k.value, ast.Constant)
                        or not isinstance(k.value.value, bool)
                        for k in decorator.keywords
                    ):
                        raise PatchwatchError(
                            "AMBIGUOUS_MIGRATION",
                            "Validator options such as each_item/always are unsupported.",
                        )
                    args = node.args.posonlyargs + node.args.args
                    if (
                        len(args) != 2
                        or args[0].arg != "cls"
                        or node.args.kwarg
                        or node.args.vararg
                        or node.args.kwonlyargs
                    ):
                        raise PatchwatchError(
                            "AMBIGUOUS_MIGRATION",
                            "Validator with context parameters requires review.",
                        )
                    pre = any(
                        k.arg == "pre"
                        and isinstance(k.value, ast.Constant)
                        and k.value.value is True
                        for k in decorator.keywords
                    )
                    call = (
                        "field_validator("
                        + ", ".join(ast.unparse(a) for a in decorator.args)
                        + (', mode="before"' if pre else "")
                        + ")"
                    )
                    if not any(
                        isinstance(d, ast.Name) and d.id == "classmethod"
                        for d in node.decorator_list
                    ):
                        call += "\n" + " " * node.col_offset + "@classmethod"
                    source.replace(decorator, call)
                    used_validator = True
            if isinstance(node, ast.ClassDef) and node.name == "Config":
                options = []
                mapping = {
                    "orm_mode": "from_attributes",
                    "allow_population_by_field_name": "populate_by_name",
                    "schema_extra": "json_schema_extra",
                    "extra": "extra",
                    "validate_assignment": "validate_assignment",
                    "arbitrary_types_allowed": "arbitrary_types_allowed",
                    "str_strip_whitespace": "str_strip_whitespace",
                }
                if node.bases or node.decorator_list:
                    raise PatchwatchError(
                        "AMBIGUOUS_MIGRATION", "Inherited/decorated Config requires review."
                    )
                for setting in node.body:
                    if (
                        not isinstance(setting, ast.Assign)
                        or len(setting.targets) != 1
                        or not isinstance(setting.targets[0], ast.Name)
                        or setting.targets[0].id not in mapping
                    ):
                        raise PatchwatchError(
                            "AMBIGUOUS_MIGRATION", "Unsupported Pydantic Config option."
                        )
                    try:
                        ast.literal_eval(setting.value)
                    except (ValueError, TypeError) as exc:
                        raise PatchwatchError(
                            "AMBIGUOUS_MIGRATION", "Dynamic Config values require review."
                        ) from exc
                    options.append(f"{mapping[setting.targets[0].id]}={ast.unparse(setting.value)}")
                source.replace(node, "model_config = ConfigDict(" + ", ".join(options) + ")")
                needs_config = True
        # Serialization only on self within a statically identified model method.
        for call_node in ast.walk(model):
            if (
                isinstance(call_node, ast.Call)
                and isinstance(call_node.func, ast.Attribute)
                and isinstance(call_node.func.value, ast.Name)
                and call_node.func.value.id == "self"
                and call_node.func.attr in {"dict", "json", "copy"}
            ):
                if call_node.func.attr == "json" and call_node.keywords:
                    raise PatchwatchError(
                        "AMBIGUOUS_MIGRATION", "JSON serialization options require review."
                    )
                new_name = {"dict": "model_dump", "json": "model_dump_json", "copy": "model_copy"}[
                    call_node.func.attr
                ]
                source.replace(call_node.func, f"self.{new_name}")
    if used_validator or needs_config:
        for i, node in enumerate(imports):
            names = [a.name for a in node.names if a.name != "validator" or not used_validator]
            if i == 0:
                if used_validator:
                    names.append("field_validator")
                if needs_config:
                    names.append("ConfigDict")
            if names:
                source.replace(node, "from pydantic import " + ", ".join(sorted(set(names))))
            else:
                source.replace(node, "")
    return source.result()


def sqlalchemy_v2(text: str) -> str:
    tree = ast.parse(text)
    source = Source(text)
    imports = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ImportFrom) and n.module and n.module.startswith("sqlalchemy")
    ]
    if not imports:
        return text
    # Resolve types within the nearest function scope, never across same-named variables.
    parents = {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}
    imported_types = {
        alias.name
        for node in imports
        if node.module in {"sqlalchemy.engine", "sqlalchemy.orm"}
        for alias in node.names
        if alias.asname is None and alias.name in {"Connection", "Session"}
    }

    def receiver_type(node: ast.AST, name: str) -> str | None:
        current = parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for argument in (
                    current.args.posonlyargs + current.args.args + current.args.kwonlyargs
                ):
                    if (
                        argument.arg == name
                        and isinstance(argument.annotation, ast.Name)
                        and argument.annotation.id in imported_types
                    ):
                        # Rebinding a parameter invalidates this deliberately narrow inference.
                        for statement in ast.walk(current):
                            if (
                                isinstance(statement, ast.Name)
                                and isinstance(statement.ctx, ast.Store)
                                and statement.id == name
                            ):
                                return None
                        return argument.annotation.id
                return None
            current = parents.get(current)
        return None

    needs_text = False
    for n in ast.walk(tree):
        if (
            isinstance(n, ast.ImportFrom)
            and n.module == "sqlalchemy.ext.declarative"
            and all(a.name == "declarative_base" for a in n.names)
        ):
            source.replace(
                n, "from sqlalchemy.orm import " + ", ".join(ast.unparse(a) for a in n.names)
            )
        if not isinstance(n, ast.Call) or not isinstance(n.func, ast.Attribute):
            continue
        if (
            isinstance(n.func.value, ast.Name)
            and receiver_type(n, n.func.value.id) in {"Connection", "Session"}
            and n.func.attr == "execute"
            and n.args
            and isinstance(n.args[0], ast.Constant)
            and isinstance(n.args[0].value, str)
        ):
            source.replace(n.args[0], "text(" + ast.unparse(n.args[0]) + ")")
            needs_text = True
        inner = n.func.value
        if (
            n.func.attr == "get"
            and isinstance(inner, ast.Call)
            and isinstance(inner.func, ast.Attribute)
            and isinstance(inner.func.value, ast.Name)
            and receiver_type(n, inner.func.value.id) == "Session"
            and inner.func.attr == "query"
            and len(inner.args) == 1
            and not inner.keywords
            and len(n.args) == 1
            and not n.keywords
        ):
            source.replace(
                n,
                f"{inner.func.value.id}.get({ast.unparse(inner.args[0])}, {ast.unparse(n.args[0])})",
            )
    result = source.result()
    if needs_text and not any(
        n.module == "sqlalchemy" and any(a.name == "text" and a.asname is None for a in n.names)
        for n in imports
    ):
        # Insert after module docstring and __future__ imports.
        parsed = ast.parse(result)
        insert_line = 0
        for n in parsed.body:
            if (
                isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Constant)
                and isinstance(n.value.value, str)
                or isinstance(n, ast.ImportFrom)
                and n.module == "__future__"
            ):
                insert_line = n.end_lineno or 0
            else:
                break
        lines = result.splitlines(keepends=True)
        lines.insert(insert_line, "from sqlalchemy import text\n")
        result = "".join(lines)
    return result


def migrate(text: str, dependency: str) -> str:
    try:
        if dependency == "pydantic":
            return pydantic_v2(text)
        if dependency == "sqlalchemy":
            return sqlalchemy_v2(text)
        return text
    except SyntaxError as exc:
        raise PatchwatchError("INVALID_SOURCE", "Cannot safely parse Python source.") from exc
