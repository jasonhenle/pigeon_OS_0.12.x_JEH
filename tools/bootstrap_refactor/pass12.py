"""Pass 12: lift functions defined inside ``main()``'s top-level ``if`` blocks.

Usage (from ``pigeonSystem``)::

    python3 pass12.py pigeon_0_12.py p12.json

Covers ``def``s that are direct statements of an ``if`` body at ``main()``'s
top level (the ``if _PIGEON_EXT:`` splash block, ``_bootstrap_after_splash``).
The ``def`` is replaced *in place* by its ``_bind_deps(...)`` binding, so the
name is still bound only on the path where it was before.

Same rules as ``pass10.py``, with "bound before" meaning *dominating*: each
closed-over name is bound exactly once in ``main()``, never ``nonlocal``, by a
simple statement that is either

- a direct statement of ``main()`` before the ``if``, or
- a direct statement of the same ``if`` body before the ``def``.

A name bound *several* times is still a plain dependency when it is
"settled": every binding sits in those same preceding statements (at any
depth -- e.g. an ``if / elif / else`` that computes ``splash_total_frames``),
none comes later, and those statements definitely bind it on every path. Its
value at the ``def`` is then the value every later call would have read.

Functions bound once by a ``def`` / ``_bind_deps(...)`` in those same places
(later ones, or the helper itself) are late-bound with ``_late`` if they are
only called / passed as arguments (pass-7 rule). A forward reference to a *value* bound once by a direct statement later in the
same ``if`` body is allowed by moving the binding down to just after that
statement, provided the helper's name is not read anywhere in main() before
the new bind point (so nothing -- no call, no thread started earlier, no
function defined earlier -- can reach it while unbound). Any other forward
reference blocks the helper.
"""
import ast
import builtins
import collections
import json
import symtable
import sys

SRC, OUT = sys.argv[1:3]
src = open(SRC).read()
tree = ast.parse(src)
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
st = symtable.symtable(src, SRC, "exec")
mt = next(c for c in st.get_children() if c.get_name() == "main")
BUILTINS = set(dir(builtins))
SIMPLE = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.FunctionDef, ast.ClassDef,
          ast.Import, ast.ImportFrom)

# every binding of every name anywhere in main() (not inside nested function bodies)
all_binds = collections.defaultdict(list)  # name -> [stmt]


class B(ast.NodeVisitor):
    def __init__(s):
        s.stmt = None

    def generic_visit(s, n):
        if isinstance(n, ast.stmt):
            prev, s.stmt = s.stmt, n
            super().generic_visit(n)
            s.stmt = prev
        else:
            super().generic_visit(n)

    def visit_FunctionDef(s, n):
        all_binds[n.name].append(n)
        for d in n.decorator_list + n.args.defaults + [d for d in n.args.kw_defaults if d]:
            s.visit(d)

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(s, n):
        all_binds[n.name].append(n)

    def visit_Lambda(s, n):
        pass

    def visit_ListComp(s, n):
        pass

    visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp

    def visit_Name(s, n):
        if isinstance(n.ctx, (ast.Store, ast.Del)):
            all_binds[n.id].append(s.stmt)

    def visit_NamedExpr(s, n):
        all_binds[n.target.id].append(s.stmt)
        s.visit(n.value)

    def visit_AugAssign(s, n):
        if isinstance(n.target, ast.Name):
            all_binds[n.target.id] += [n, n]
        s.generic_visit(n)

    def visit_Import(s, n):
        for a in n.names:
            all_binds[(a.asname or a.name).split(".")[0]].append(n)

    visit_ImportFrom = visit_Import

    def visit_ExceptHandler(s, n):
        if n.name:
            all_binds[n.name].append(n)
        s.generic_visit(n)


v = B()
for a in main.args.args + main.args.kwonlyargs:
    all_binds[a.arg].append(main)
for stmt in main.body:
    v.stmt = stmt
    v.visit(stmt)

nl_main = collections.Counter(nm for n in ast.walk(main) if isinstance(n, ast.Nonlocal) for nm in n.names)
gl_names = {nm for n in ast.walk(tree) if isinstance(n, ast.Global) for nm in n.names}
plain_imports = {}
for s in tree.body:
    if isinstance(s, ast.Import):
        for a in s.names:
            if a.asname or "." not in a.name:
                plain_imports[a.asname or a.name] = True


def stmt_ids(stmts):
    out = set()
    for s in stmts:
        for n in ast.walk(s):
            if isinstance(n, (ast.stmt, ast.ExceptHandler)):
                out.add(id(n))
    return out


def binds_here(s, name):
    return any(b is s for b in all_binds.get(name, []))


def definitely_binds(stmts, name):
    """Executing ``stmts`` (without an exception) always binds ``name``."""
    for s in stmts:
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if s.name == name:
                return True
            continue
        if isinstance(s, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Import, ast.ImportFrom, ast.Expr)):
            if binds_here(s, name) and not (isinstance(s, ast.AnnAssign) and s.value is None):
                return True
            continue
        if isinstance(s, ast.If):
            if s.orelse and definitely_binds(s.body, name) and definitely_binds(s.orelse, name):
                return True
            continue
        if isinstance(s, ast.Try):
            if definitely_binds(s.finalbody, name):
                return True
            if definitely_binds(s.body + s.orelse, name) and all(definitely_binds(h.body, name) for h in s.handlers):
                return True
            continue
        if isinstance(s, ast.With):
            if definitely_binds(s.body, name):
                return True
            continue
    return False


def is_fn_binding(s):
    if isinstance(s, ast.FunctionDef):
        return True
    if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
        v_ = s.value
        return (isinstance(v_, ast.Call) and isinstance(v_.func, ast.Name) and v_.func.id == "_bind_deps") or (
            isinstance(v_, ast.Attribute) and isinstance(v_.value, ast.Name) and v_.value.id.startswith("_core_"))
    return False


def uses_ok(fn, name):
    parents = {c: p for p in ast.walk(fn) for c in ast.iter_child_nodes(p)}
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id == name:
            if not isinstance(n.ctx, ast.Load):
                return False
            p = parents.get(n)
            if isinstance(p, ast.Call) and (p.func is n or n in p.args):
                continue
            if isinstance(p, ast.keyword) and p.value is n:
                continue
            if isinstance(p, (ast.List, ast.Tuple)) and n in p.elts:
                continue
            if isinstance(p, ast.Dict) and any(x is n for x in p.values):
                continue
            return False
    return True


def const_default(d):
    try:
        ast.literal_eval(d)
        return True
    except Exception:
        return False


def tables_under(t):
    yield t
    for c in t.get_children():
        yield from tables_under(c)


def attr_stores(name):
    return [t for n in ast.walk(tree) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id == name
            for t in n.targets if isinstance(t, ast.Attribute)]


kids = collections.defaultdict(list)
for c in mt.get_children():
    kids[c.get_name()].append(c)

rows = []
for i, top in enumerate(main.body):
    if not isinstance(top, ast.If):
        continue
    blk = top.body
    for j, f in enumerate(blk):
        if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        t = next(c for c in kids[f.name] if c.get_lineno() == f.lineno)
        r = []
        if f.decorator_list: r.append("decorated")
        if isinstance(f, ast.AsyncFunctionDef): r.append("async")
        if f.args.kwarg: r.append("**kwargs")
        if not all(const_default(d) for d in f.args.defaults + [d for d in f.args.kw_defaults if d]): r.append("nonconst-default")
        if any(isinstance(n, (ast.Nonlocal, ast.Global)) for n in ast.walk(f)): r.append("nonlocal")
        if any(isinstance(n, ast.ClassDef) for n in ast.walk(f)): r.append("classdef")
        if len(all_binds[f.name]) != 1: r.append("rebound-self")
        for a in attr_stores(f.name):
            r.append("stored-on:" + ast.unparse(a))
        dom = set(id(s) for s in main.body[:i] if isinstance(s, SIMPLE)) | set(id(s) for s in blk[:j] if isinstance(s, SIMPLE))
        prefix = main.body[:i] + blk[:j]
        prefix_ids = stmt_ids(prefix)
        later_fn = set(id(s) for s in main.body + blk if is_fn_binding(s))
        deps, late, gdeps, imps, fwd = [], [], set(), set(), []
        for n in sorted(t.get_frees()):
            b = all_binds.get(n, [])
            if not mt.lookup(n).is_local():
                r.append("??:" + n)
            elif len(b) == 1 and nl_main[n] == 0 and (b[0] is main or id(b[0]) in dom):
                deps.append(n)
            elif len(b) > 1 and nl_main[n] == 0 and all(id(x) in prefix_ids for x in b) and definitely_binds(prefix, n):
                deps.append(n)  # settled: rebound only before the def, bound on every path
            elif len(b) == 1 and nl_main[n] == 0 and id(b[0]) in later_fn and uses_ok(f, n):
                late.append(n)
            elif len(b) == 1 and nl_main[n] == 0 and any(x is b[0] for x in blk[j + 1:]) and isinstance(b[0], SIMPLE):
                fwd.append((blk.index(b[0]), n))
            else:
                r.append(("forward:" if len(b) == 1 else "rebound:") + n)
        for tb in tables_under(t):
            for sym in tb.get_symbols():
                if sym.is_global() and sym.is_referenced() and not sym.is_declared_global():
                    n = sym.get_name()
                    if n in ("__file__", "__name__", "__spec__", "__doc__"): r.append("dunder")
                    elif n in gl_names: r.append("global-rebound:" + n)
                    elif n in plain_imports: imps.add(n)
                    elif n in BUILTINS: pass
                    else: gdeps.add(n)
        bind_after_line = None
        if fwd:
            k = max(x for x, _ in fwd)
            upto = blk[k].end_lineno
            readers = [x for x in ast.walk(main) if isinstance(x, ast.Name) and x.id == f.name
                       and isinstance(x.ctx, ast.Load) and x.lineno <= upto]
            if readers:
                r.append("forward-read-early:" + ",".join(str(x.lineno) for x in readers))
            else:
                deps += [n for _, n in fwd]
                bind_after_line = upto
        rows.append(dict(name=f.name, line=f.lineno, end=f.end_lineno, idx=i, bind_after_line=bind_after_line,
                         bdeps=sorted(set(deps) | set(late)),
                         mdeps=[], gdeps=sorted(gdeps), imps=sorted(imps), late=sorted(late), reasons=r, safe=not r))
json.dump(rows, open(OUT, "w"), indent=1)
for x in rows:
    print("SAFE   " if x["safe"] else "blocked", x["name"], "" if x["safe"] else x["reasons"], ("late=" + ",".join(x["late"])) if x["late"] else "")
print(sum(x["safe"] for x in rows), "of", len(rows), "helpers in main()'s if-blocks liftable")
