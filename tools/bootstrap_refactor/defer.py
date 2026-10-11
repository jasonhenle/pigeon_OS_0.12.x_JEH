"""Pass 9: create a holder up front, fill it where the object used to be created.

Usage (from ``pigeonSystem``)::

    python3 defer.py pigeon_0_12.py HOLDER [HOLDER ...]

For each ``HOLDER`` bound once at bootstrap()'s top level as
``HOLDER = [expr]`` (or ``HOLDER: list[T] = [expr]``), this rewrites that
statement in place to ``HOLDER[0] = expr`` -- so ``expr`` (a widget
constructor, a settings read, ...) still runs at exactly the same moment --
and adds ``HOLDER = [None]`` (keeping any annotation, widened to ``| None``)
to the hoisted-state block at the top of bootstrap().

Only difference: code that runs *before* the fill point now sees ``None`` in
the holder instead of hitting a ``NameError``. ``verify_order.py`` already
guarantees bootstrap()'s own top level never reads it early.
"""
import ast
import sys

MARK = "        # State created up front (hoisted; side-effect-free initialisers).\n"

path, names = sys.argv[1], sys.argv[2:]
src = open(path, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
boot = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "bootstrap")
if MARK not in lines:
    sys.exit("defer: run hoist.py first (no hoisted-state block)")

decls = []
edits = []
for name in names:
    stmt = None
    for s in boot.body:
        tgt = s.targets[0] if isinstance(s, ast.Assign) and len(s.targets) == 1 else (
            s.target if isinstance(s, ast.AnnAssign) else None)
        if isinstance(tgt, ast.Name) and tgt.id == name:
            if stmt is not None:
                sys.exit(f"defer: {name} bound twice at bootstrap() top level")
            stmt = s
    if stmt is None or not (isinstance(stmt.value, ast.List) and len(stmt.value.elts) == 1):
        sys.exit(f"defer: {name} is not bound as a one-element holder at bootstrap() top level")
    ann = ""
    if isinstance(stmt, ast.AnnAssign):
        a = ast.get_source_segment(src, stmt.annotation)
        inner = a[len("list["):-1] if a.startswith("list[") and a.endswith("]") else None
        ann = f": list[{inner} | None]" if inner and "None" not in inner else f": {a}"
    decls.append(f"        {name}{ann} = [None]\n")
    # rewrite the whole statement `NAME(: T)? = [expr]` -> `NAME[0] = expr`, keeping expr's text
    elt = stmt.value.elts[0]

    def off(lineno, col):
        return sum(len(l) for l in lines[:lineno - 1]) + len(lines[lineno - 1].encode()[:col].decode())

    start, end = off(stmt.lineno, stmt.col_offset), off(stmt.end_lineno, stmt.end_col_offset)
    expr_text = src[off(elt.lineno, elt.col_offset):off(elt.end_lineno, elt.end_col_offset)]
    if "\n" in expr_text and not isinstance(elt, (ast.Call, ast.List, ast.Dict, ast.Tuple, ast.Set)):
        body = "\n".join(l if i == 0 else "    " + l for i, l in enumerate(expr_text.splitlines()))
        expr_text = "(\n" + " " * 12 + body.strip() + "\n" + " " * 8 + ")"
        # re-indent continuation lines consistently under the opening paren
        first, *rest = expr_text.split("\n")
        expr_text = "\n".join([first] + [(" " * 12 + r.strip()) if r.strip() and r.strip() != ")" else r for r in rest[:-1]] + [rest[-1]])
    edits.append((start, end, f"{name}[0] = {expr_text}"))

out = src
for s, e, t in sorted(edits, reverse=True):
    out = out[:s] + t + out[e:]
i = out.index(MARK) + len(MARK)
out = out[:i] + "".join(decls) + out[i:]
ast.parse(out)
open(path, "w", encoding="utf-8").write(out)
print("deferred:", ", ".join(names))
