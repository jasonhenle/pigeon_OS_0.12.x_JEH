"""Pass 4: turn nonlocal-rebound bootstrap() variables into one-element holders.

Usage (from ``pigeonSystem``)::

    python3 holderize.py pigeon_0_12.py NAME [NAME ...]
    python3 holderize.py --main pigeon_0_12.py NAME [NAME ...]
    python3 holderize.py pigeon_0_12.py NAME:NEW_NAME ...   # holder gets a new name

With ``NAME:NEW_NAME`` every rewritten reference becomes ``NEW_NAME[0]`` and the
initial binding binds ``NEW_NAME`` (e.g. ``main_settings_widget:main_settings_widget_holder``),
so readers can tell a holder from the object it holds.

For each NAME bound in ``bootstrap()`` (or, with ``--main``, in ``main()``
itself) this rewrites, in place:

- the first top-level binding ``NAME = expr`` / ``NAME: T = expr`` into
  ``NAME = [expr]`` / ``NAME: list[T] = [expr]`` (it must be unconditional,
  at bootstrap()'s top level, and come before every other binding in
  bootstrap()'s own body);
- every other reference that resolves to bootstrap()'s NAME (loads, stores,
  ``+=``, in bootstrap() itself or any nested function / lambda /
  comprehension that does not shadow it) into ``NAME[0]``;
- ``nonlocal NAME`` declarations: NAME is dropped (the statement is removed
  when nothing is left).

Refuses (exit 2) on shapes it cannot rewrite faithfully: ``del NAME``, NAME
as a ``for`` / ``with`` / ``except`` / walrus / import / def target, a
``global NAME`` anywhere, or NAME already used in main() outside bootstrap().
Text is edited at exact AST offsets, so formatting and comments are kept.
"""
from __future__ import annotations

import ast
import sys

SCOPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ListComp,
          ast.SetComp, ast.DictComp, ast.GeneratorExp, ast.ClassDef)


def die(msg: str) -> None:
    print("holderize: " + msg, file=sys.stderr)
    sys.exit(2)


def own_nodes(scope):
    """Yield nodes belonging to ``scope`` itself (not to nested scopes)."""
    stack = list(ast.iter_child_nodes(scope))
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, SCOPES):
            # decorators / defaults / first comprehension iterable belong to the
            # enclosing scope; bodies do not.
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                stack.extend(n.decorator_list + n.args.defaults
                             + [d for d in n.args.kw_defaults if d])
            elif isinstance(n, ast.Lambda):
                stack.extend(n.args.defaults + [d for d in n.args.kw_defaults if d])
            elif isinstance(n, ast.ClassDef):
                stack.extend(n.decorator_list + n.bases)
            else:
                stack.append(n.generators[0].iter)
            continue
        stack.extend(ast.iter_child_nodes(n))


def child_scopes(scope):
    for n in own_nodes(scope):
        if isinstance(n, SCOPES):
            yield n


def params(scope):
    if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
        a = scope.args
        return {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs
                + [v for v in (a.vararg, a.kwarg) if v]}
    return set()


def shadows(scope, name):
    """True when ``name`` is local to ``scope`` (so it hides bootstrap's)."""
    if name in params(scope):
        return True
    if isinstance(scope, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
        for g in scope.generators:
            for n in ast.walk(g.target):
                if isinstance(n, ast.Name) and n.id == name:
                    return True
        return False
    declared = False
    binds = False
    for n in own_nodes(scope):
        if isinstance(n, ast.Nonlocal) and name in n.names:
            declared = True
        elif isinstance(n, ast.Global) and name in n.names:
            die(f"global {name} in {getattr(scope, 'name', '?')}")
        elif isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Store):
            binds = True
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name:
            binds = True
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            if any((a.asname or a.name).split(".")[0] == name for a in n.names):
                binds = True
        elif isinstance(n, ast.ExceptHandler) and n.name == name:
            binds = True
    return binds and not declared


def main() -> None:
    args = sys.argv[1:]
    in_main = args[0] == "--main"
    if in_main:
        args = args[1:]
    path, specs = args[0], args[1:]
    rename = {}
    names = []
    for sp in specs:
        old, _, new = sp.partition(":")
        names.append(old)
        rename[old] = new or old
    src = open(path, encoding="utf-8").read()
    lines = src.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))

    def off(lineno, col):
        # ast col offsets are UTF-8 byte offsets
        line = lines[lineno - 1]
        return starts[lineno - 1] + len(line.encode("utf-8")[:col].decode("utf-8"))

    tree = ast.parse(src)
    main_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    boot = next(n for n in main_fn.body if isinstance(n, ast.FunctionDef) and n.name == "bootstrap")

    owner = main_fn if in_main else boot
    edits: list[tuple[int, int, str]] = []
    for name in names:
        # main() itself must not own the name (unless it is the owner).
        if not in_main:
            for n in own_nodes(main_fn):
                if isinstance(n, ast.Name) and n.id == name:
                    die(f"{name} is referenced in main() outside bootstrap()")

        init = None
        for i, stmt in enumerate(owner.body):
            hit = [n for n in own_nodes_stmt(stmt) if isinstance(n, ast.Name) and n.id == name
                   and isinstance(n.ctx, ast.Store)]
            if not hit:
                continue
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1 and isinstance(stmt.targets[0], ast.Name):
                init = stmt
            elif isinstance(stmt, ast.AnnAssign) and stmt.value is not None and isinstance(stmt.target, ast.Name):
                init = stmt
            else:
                die(f"first bootstrap() binding of {name} (line {stmt.lineno}) is not a plain top-level assignment")
            break
        if init is None:
            die(f"{name} is never bound at bootstrap() top level")

        refs: list[ast.Name] = []
        nonlocals: list[ast.Nonlocal] = []

        def walk(scope, live):
            for n in own_nodes(scope):
                if isinstance(n, ast.Name) and n.id == name and live:
                    refs.append(n)
                elif isinstance(n, ast.Nonlocal) and name in n.names and live:
                    nonlocals.append(n)
                elif isinstance(n, ast.Delete) and live and any(
                        isinstance(t, ast.Name) and t.id == name for t in n.targets):
                    die(f"del {name} at line {n.lineno}")
                elif isinstance(n, (ast.For, ast.AsyncFor)) and live and any(
                        isinstance(t, ast.Name) and t.id == name for t in ast.walk(n.target)):
                    die(f"{name} is a for-loop target at line {n.lineno}")
                elif isinstance(n, ast.withitem) and live and n.optional_vars is not None and any(
                        isinstance(t, ast.Name) and t.id == name for t in ast.walk(n.optional_vars)):
                    die(f"{name} is a with-target")
                elif isinstance(n, ast.NamedExpr) and live and n.target.id == name:
                    die(f"{name} is a walrus target at line {n.lineno}")
            for c in child_scopes(scope):
                walk(c, live and not shadows(c, name))

        if shadows(owner, name) is False:
            die(f"{name} is not local to {owner.name}()")
        walk(owner, True)

        init_target = init.targets[0] if isinstance(init, ast.Assign) else init.target
        for r in refs:
            if r is init_target:
                continue
            edits.append((off(r.lineno, r.col_offset), off(r.end_lineno, r.end_col_offset), f"{rename[name]}[0]"))
        if rename[name] != name:
            s_, e_ = off(init_target.lineno, init_target.col_offset), off(init_target.end_lineno, init_target.end_col_offset)
            edits.append((s_, e_, rename[name]))
        # wrap the initial value
        v = init.value
        vs, ve = off(v.lineno, v.col_offset), off(v.end_lineno, v.end_col_offset)
        edits.append((vs, vs, "["))
        edits.append((ve, ve, "]"))
        if isinstance(init, ast.AnnAssign):
            a = init.annotation
            s, e = off(a.lineno, a.col_offset), off(a.end_lineno, a.end_col_offset)
            edits.append((s, e, f"list[{ast.get_source_segment(src, a)}]"))
        for nl in nonlocals:
            rest = [x for x in nl.names if x != name]
            s, e = off(nl.lineno, nl.col_offset), off(nl.end_lineno, nl.end_col_offset)
            edits.append((s, e, ("nonlocal " + ", ".join(rest)) if rest else "\0DROP"))
        print(f"{name}: init line {init.lineno}, {len(refs) - 1} refs, {len(nonlocals)} nonlocal decls")

    # Nonlocal statements can be edited once per name; merge overlapping ones.
    merged: dict[tuple[int, int], str] = {}
    other = []
    for s, e, t in edits:
        seg = src[s:e]
        if seg.startswith("nonlocal"):
            keep = [x.strip() for x in seg[len("nonlocal"):].split(",")]
            dropped = set(names) & set(keep)
            keep = [x for x in keep if x not in dropped]
            merged[(s, e)] = "nonlocal " + ", ".join(keep) if keep else "\0DROP"
        else:
            other.append((s, e, t))
    edits = other + [(s, e, t) for (s, e), t in merged.items()]
    edits.sort(key=lambda x: (x[0], x[1]))
    for a, b in zip(edits, edits[1:]):
        if a[1] > b[0] and not (a[0] == a[1] or b[0] == b[1]):
            die(f"overlapping edits at {a} / {b}")
    out = src
    for s, e, t in sorted(edits, key=lambda x: (x[0], x[1]), reverse=True):
        if t == "\0DROP":
            ls = out.rfind("\n", 0, s) + 1
            le = out.find("\n", e) + 1
            if out[ls:s].strip() or out[e:le].strip():
                die(f"nonlocal statement shares its line: {out[ls:le]!r}")
            out = out[:ls] + out[le:]
        else:
            out = out[:s] + t + out[e:]
    ast.parse(out)
    open(path, "w", encoding="utf-8").write(out)


def own_nodes_stmt(stmt):
    """Nodes of a bootstrap() top-level statement, excluding nested scope bodies."""
    if isinstance(stmt, SCOPES):
        return []
    return list(own_nodes(ast.Module(body=[stmt], type_ignores=[])))


if __name__ == "__main__":
    main()
