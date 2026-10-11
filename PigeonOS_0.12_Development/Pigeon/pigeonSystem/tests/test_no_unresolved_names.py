"""Every name read inside main() / bootstrap() must exist in some enclosing scope.

Guards against a bug class that hid for a long time: helpers defined directly in
``main()`` read objects that only existed inside ``bootstrap()``. Python looked
them up as module globals, raised ``NameError``, and ``except NameError: pass``
swallowed it -- so the zone-3 volume hold and parts of the clock-saver volume
logic silently never ran.
"""

import ast
import builtins
import symtable
import unittest
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "pigeon_0_12.py"


def _module_names(tree: ast.Module) -> set[str]:
    names = set(dir(builtins)) | {"__file__", "__name__", "__spec__", "__doc__"}
    for stmt in tree.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(stmt.name)
            continue
        for node in ast.walk(stmt):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                names.add(node.id)
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    names.add((alias.asname or alias.name).split(".")[0])
            elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                names.add(node.name)
    return names


class NoUnresolvedNamesTests(unittest.TestCase):
    def test_main_and_bootstrap_only_read_names_that_exist(self) -> None:
        src = SRC.read_text(encoding="utf-8")
        known = _module_names(ast.parse(src))
        table = symtable.symtable(src, str(SRC), "exec")
        main = next(c for c in table.get_children() if c.get_name() == "main")
        missing: list[str] = []

        def walk(t: symtable.SymbolTable, path: str) -> None:
            for sym in t.get_symbols():
                if sym.is_global() and sym.is_referenced() and not sym.is_declared_global():
                    if sym.get_name() not in known:
                        missing.append(f"{path}: {sym.get_name()}")
            for child in t.get_children():
                walk(child, f"{path}.{child.get_name()}")

        walk(main, "main")
        self.assertEqual(missing, [], "names read but never defined in any enclosing scope")


if __name__ == "__main__":
    unittest.main()
