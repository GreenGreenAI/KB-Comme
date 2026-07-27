import ast
import unittest
from pathlib import Path


SOURCE_ROOT = Path(__file__).resolve().parents[2] / "src" / "tradeflow"

FORBIDDEN_DEPENDENCIES = {
    "domain": {"contracts", "knowledge", "tools", "runtime", "integration"},
    "contracts": {"knowledge", "tools", "runtime", "integration"},
    "knowledge": {"tools", "runtime", "integration"},
    "tools": {"contracts", "knowledge", "runtime", "integration"},
    "runtime": {"integration", "agent", "web"},
    "agent": {"integration", "web"},
    "web": {"integration"},
    "integration": {"knowledge", "tools", "runtime", "agent", "web"},
}

# `integration` performs network I/O and must stay reachable only through the
# snapshot files it writes, never by import (ADR-0003).
LEAF_MODULES = {"integration"}


class ModuleBoundaryTests(unittest.TestCase):
    def test_integration_is_a_leaf_no_module_imports(self) -> None:
        violations: list[str] = []
        for path in SOURCE_ROOT.rglob("*.py"):
            owner = path.relative_to(SOURCE_ROOT).parts[0]
            if owner in LEAF_MODULES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                imported = _imported_tradeflow_module(node)
                if imported and imported[0] in LEAF_MODULES:
                    violations.append(
                        f"{path.relative_to(SOURCE_ROOT)} imports "
                        f"tradeflow.{'.'.join(imported)}"
                    )
        self.assertEqual([], violations, "\n".join(violations))

    def test_owned_modules_do_not_import_forbidden_layers(self) -> None:
        violations: list[str] = []
        for owner, forbidden in FORBIDDEN_DEPENDENCIES.items():
            for path in (SOURCE_ROOT / owner).rglob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
                for node in ast.walk(tree):
                    imported = _imported_tradeflow_module(node)
                    if imported and imported[0] in forbidden:
                        violations.append(
                            f"{path.relative_to(SOURCE_ROOT)} imports "
                            f"tradeflow.{'.'.join(imported)}"
                        )
        self.assertEqual([], violations, "\n".join(violations))


def _imported_tradeflow_module(node: ast.AST) -> tuple[str, ...] | None:
    if isinstance(node, ast.ImportFrom) and node.module:
        parts = node.module.split(".")
        if parts[0] == "tradeflow" and len(parts) > 1:
            return tuple(parts[1:])
    if isinstance(node, ast.Import):
        for alias in node.names:
            parts = alias.name.split(".")
            if parts[0] == "tradeflow" and len(parts) > 1:
                return tuple(parts[1:])
    return None


if __name__ == "__main__":
    unittest.main()

