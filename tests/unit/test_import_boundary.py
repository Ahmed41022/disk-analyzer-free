"""Enforces the native module import boundary."""

import ast
from pathlib import Path


def _imports_native_core(module: ast.Module) -> bool:
    """Return whether a module imports or dynamically loads the native core."""
    for node in ast.walk(module):
        if isinstance(node, ast.Import) and any(
            alias.name == "dafree._core" or alias.name.startswith("dafree._core.")
            for alias in node.names
        ):
            return True

        if isinstance(node, ast.ImportFrom):
            if node.module == "dafree._core":
                return True
            if node.module == "dafree" and any(alias.name == "_core" for alias in node.names):
                return True
            if (
                node.level
                and node.module in {None, "_core"}
                and (node.module == "_core" or any(alias.name == "_core" for alias in node.names))
            ):
                return True

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            if node.func.attr != "import_module" or not node.args:
                continue
            target = node.args[0]
            if isinstance(target, ast.Constant) and target.value == "dafree._core":
                return True

    return False


def test_only_api_imports_core() -> None:
    """Only modules under dafree.api may import the native extension."""
    package_root = Path(__file__).parents[2] / "src" / "dafree"
    api_root = package_root / "api"
    violations = []

    for source_file in package_root.rglob("*.py"):
        if api_root in source_file.parents:
            continue
        tree = ast.parse(source_file.read_text(encoding="utf-8"), filename=str(source_file))
        if _imports_native_core(tree):
            violations.append(source_file.relative_to(package_root).as_posix())

    assert violations == []
