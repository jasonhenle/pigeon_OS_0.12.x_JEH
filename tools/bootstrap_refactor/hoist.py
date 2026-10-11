"""Pass 8: move side-effect-free state initialisers to the top of bootstrap().

Usage (from ``pigeonSystem``)::

    python3 hoist.py pigeon_0_12.py NAME [NAME ...]

Helpers defined early in ``bootstrap()`` often read holders / dicts that are
created further down (``dev_phase = [DevPhase.OFF]``). Creating those objects
earlier changes nothing observable, and lets pass 2 treat them as stable
dependencies. For each NAME this requires that:

- NAME is bound exactly once in bootstrap() (one top-level ``NAME = expr`` /
  ``NAME: T = expr``, never ``nonlocal``-rebound, no other binding anywhere);
- ``expr`` is built only from literals, containers, attribute access on and
  names of *module-level* globals / builtins, and calls to a small allow-list
  of pure constructors (``dict``, ``list``, ``set``, ``tuple``, ``float``,
  ``int``, ``str``, ``bool``) -- nothing that reads bootstrap()/main() state or
  does I/O.

The statement, with the comment lines directly above it, moves to the top of
bootstrap() (after its docstring), keeping the relative order of hoisted names.
"""
import ast
import builtins
import sys

PURE_CALLS = {"dict", "list", "set", "tuple", "float", "int", "str", "bool"}


def die(msg):
    print("hoist: " + msg, file=sys.stderr)
    sys.exit(2)


path, names = sys.argv[1], sys.argv[2:]
src = open(path, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)
module_names = set(dir(builtins))
for s in tree.body:
    for n in ast.walk(s) if not isinstance(s, (ast.FunctionDef, ast.ClassDef)) else [s]:
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            module_names.add(n.id)
    if isinstance(s, (ast.FunctionDef, ast.ClassDef)):
        module_names.add(s.name)
    if isinstance(s, (ast.Import, ast.ImportFrom)):
        for a in s.names:
            module_names.add((a.asname or a.name).split(".")[0])
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
boot = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "bootstrap")
main_locals = {n.id for n in ast.walk(main) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)}
main_locals |= {n.name for n in ast.walk(main) if isinstance(n, (ast.FunctionDef, ast.ClassDef))}


def pure(expr):
    for n in ast.walk(expr):
        if isinstance(n, ast.Name):
            if n.id not in module_names or n.id in main_locals:
                return f"uses non-global name {n.id!r}"
        elif isinstance(n, ast.Call):
            if not (isinstance(n.func, ast.Name) and n.func.id in PURE_CALLS):
                return "calls " + ast.unparse(n.func)
        elif isinstance(n, (ast.Lambda, ast.NamedExpr, ast.Await, ast.Yield, ast.YieldFrom,
                            ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.Subscript)):
            return "contains " + type(n).__name__
    return None


body_start = 1 if (boot.body and isinstance(boot.body[0], ast.Expr)
                   and isinstance(getattr(boot.body[0], "value", None), ast.Constant)) else 0
anchor = boot.body[body_start]
moves = []
for name in names:
    stores = [n for n in ast.walk(boot) if isinstance(n, ast.Name) and n.id == name
              and isinstance(n.ctx, (ast.Store, ast.Del))]
    nonlocal_hits = [n for n in ast.walk(main) if isinstance(n, ast.Nonlocal) and name in n.names]
    if len(stores) != 1 or nonlocal_hits:
        die(f"{name}: bound {len(stores)}x / nonlocal {len(nonlocal_hits)}x; must be bound exactly once")
    stmt = next((s for s in boot.body if isinstance(s, (ast.Assign, ast.AnnAssign))
                 and stores[0] in list(ast.walk(s))), None)
    if stmt is None:
        die(f"{name}: its binding is not a bootstrap() top-level assignment")
    why = pure(stmt.value)
    if why:
        die(f"{name}: initialiser is not side-effect free ({why})")
    start = stmt.lineno
    while start > 1 and lines[start - 2].strip().startswith("#") and lines[start - 2].startswith(" " * 8) \
            and not lines[start - 2].startswith(" " * 9):
        start -= 1
    moves.append((start, stmt.end_lineno, name))

moves.sort()
block = []
drop = set()
for s, e, name in moves:
    if s <= anchor.lineno:
        die(f"{name} is already at the top")
    block.append("".join(lines[s - 1:e]))
    drop.update(range(s, e + 1))
out = []
for i, l in enumerate(lines, 1):
    if i == anchor.lineno:
        out.append("        # State created up front (hoisted; side-effect-free initialisers).\n")
        out.extend(block)
        out.append("\n")
    if i in drop:
        continue
    out.append(l)
new = "".join(out)
ast.parse(new)
open(path, "w", encoding="utf-8").write(new)
print("hoisted:", ", ".join(n for _s, _e, n in moves))
