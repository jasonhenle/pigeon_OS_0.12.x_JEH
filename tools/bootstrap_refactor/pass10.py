"""Pass 10: lift the helpers defined directly in ``main()``.

Same rules as ``pass2.py`` / ``pass7.py``, one scope up: the helper's parent
is ``main()`` and its grandparent is the module.

Usage (from ``pigeonSystem``)::

    python3 pass10.py pigeon_0_12.py p10.json

A top-level ``def`` in ``main()`` (other than ``bootstrap``) is liftable when:

- no ``nonlocal`` / ``global``, decorators, ``async``, ``**kwargs``, class
  defs, or non-constant defaults;
- every ``main()`` name it closes over is bound exactly once, unconditionally,
  at ``main()``'s top level *before* the helper's ``def``, and is never the
  target of a ``nonlocal`` anywhere in ``main()`` (``bootstrap()`` included);
- the exceptions are *functions*: the helper itself (recursion) or a helper
  bound later by a ``def`` / ``_bind_deps(...)``; those are late-bound with
  ``_late(lambda: X, "X")`` exactly as in pass 7, if the helper only calls
  them or passes them as arguments;
- every module global it reads is never rebound with ``global``;
- the helper is never stored as an attribute of anything except the Tk root
  (``root.report_callback_exception = f`` is fine). Storing it on a class
  (``tk.Widget.pack = f``) would break: a ``functools.partial`` is not a
  descriptor, so it would not receive ``self``.

Pass 11 options:

- ``--method NAME``: ``NAME`` may be stored on a class. The row is marked
  ``method`` and ``transform.py`` binds it with ``bind_method_deps`` (a real
  function, so it becomes a bound method). Every dependency name must start
  with ``_`` and no ``.pack(`` / ``.grid(`` / ``.place(`` call in the app
  passes such a keyword (Tk option names never start with ``_``).
- ``**kwargs`` is accepted when every call of the helper in ``pigeon_0_12.py``
  and ``pigeon/core/`` passes explicit keywords only (no ``**`` splat) and none
  of them is a dependency name; the dependencies are then keyword-only
  parameters placed before ``**kwargs``, so ``kwargs`` sees exactly the same
  keys as before.
"""
import ast
import builtins
import collections
import json
import symtable
import sys

import glob
import os

METHODS = set()
_argv = sys.argv[1:]
while "--method" in _argv:
    k = _argv.index("--method")
    METHODS.add(_argv[k + 1])
    del _argv[k:k + 2]
SRC, OUT = _argv[:2]
CALL_FILES = [SRC] + sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(SRC)), "pigeon", "core", "*.py")))
src = open(SRC).read()
tree = ast.parse(src)
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
st = symtable.symtable(src, SRC, "exec")
mt = next(c for c in st.get_children() if c.get_name() == "main")
BUILTINS = set(dir(builtins))

SIMPLE = (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.FunctionDef, ast.AsyncFunctionDef,
          ast.ClassDef, ast.Import, ast.ImportFrom, ast.Return, ast.Pass, ast.Delete, ast.Raise, ast.Assert)


def scope_binds(fn):
    """name -> [(lineno, top_index | None)]; None = bound inside a compound statement."""
    binds = collections.defaultdict(list)

    class B(ast.NodeVisitor):
        top = None
        depth = 0

        def add(s, name, node):
            binds[name].append((node.lineno, s.top if s.depth == 0 else None))

        def visit_FunctionDef(s, n):
            for d in n.decorator_list + n.args.defaults + [d for d in n.args.kw_defaults if d]:
                s.visit(d)
            s.add(n.name, n)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(s, n):
            s.add(n.name, n)

        def visit_Lambda(s, n):
            pass

        def visit_ListComp(s, n):
            pass

        visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp

        def visit_Name(s, n):
            if isinstance(n.ctx, (ast.Store, ast.Del)):
                s.add(n.id, n)

        def visit_NamedExpr(s, n):
            s.add(n.target.id, n)
            s.visit(n.value)

        def visit_AugAssign(s, n):
            if isinstance(n.target, ast.Name):
                s.add(n.target.id, n)
                s.add(n.target.id, n)
            else:
                s.visit(n.target)
            s.visit(n.value)

        def visit_Import(s, n):
            for a in n.names:
                s.add((a.asname or a.name).split(".")[0], n)

        visit_ImportFrom = visit_Import

        def visit_ExceptHandler(s, n):
            if n.name:
                s.add(n.name, n)
            s.generic_visit(n)

    for a in fn.args.args + fn.args.kwonlyargs + fn.args.posonlyargs + [x for x in (fn.args.vararg, fn.args.kwarg) if x]:
        binds[a.arg].append((fn.lineno, -1))
    v = B()
    for i, stmt in enumerate(fn.body):
        v.top = i
        v.depth = 0 if isinstance(stmt, SIMPLE) else 1
        v.visit(stmt)
    return binds


mb = scope_binds(main)
nl_main = collections.Counter(nm for n in ast.walk(main) if isinstance(n, ast.Nonlocal) for nm in n.names)
gl_names = {nm for n in ast.walk(tree) if isinstance(n, ast.Global) for nm in n.names}
plain_imports = {}
for s in tree.body:
    if isinstance(s, ast.Import):
        for a in s.names:
            if a.asname or "." not in a.name:
                plain_imports[a.asname or a.name] = True


def stable_before(name, i):
    b = mb.get(name, [])
    return len(b) == 1 and b[0][1] is not None and 0 <= b[0][1] < i and nl_main[name] == 0


# functions bound once at main() top level by a def or _bind_deps / _core_* (pass 7 rule)
fn_bound = {}
for s in main.body:
    if isinstance(s, ast.FunctionDef):
        fn_bound[s.name] = fn_bound.get(s.name, 0) + 1
    elif isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
        v = s.value
        ok = (isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "_bind_deps") or (
            isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id.startswith("_core_"))
        if ok:
            fn_bound[s.targets[0].id] = fn_bound.get(s.targets[0].id, 0) + 1


def late_ok(name):
    return fn_bound.get(name) == 1 and len(mb.get(name, [])) == 1 and nl_main[name] == 0


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
            if isinstance(p, ast.Dict) and any(v is n for v in p.values):
                continue
            if isinstance(p, (ast.List, ast.Tuple)) and n in p.elts:
                continue
            return False
    return True


# names bound in main() to ``tk.Tk()``: storing a callable on these is an instance attribute
tk_roots = set()
for s in main.body:
    if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
        if ast.unparse(s.value) == "tk.Tk()":
            tk_roots.add(s.targets[0].id)


def attr_stores(name):
    """Attribute targets that ``name`` is assigned to anywhere in the module."""
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Assign) and isinstance(n.value, ast.Name) and n.value.id == name:
            for t in n.targets:
                if isinstance(t, ast.Attribute):
                    out.append(t)
    return out


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


def _calls():
    for p in CALL_FILES:
        for n in ast.walk(ast.parse(open(p).read())):
            if isinstance(n, ast.Call):
                yield n


def call_keywords(name):
    """Keyword names at every ``name(...)`` call (``None`` for a ``**`` splat)."""
    return [k.arg for n in _calls() if isinstance(n.func, ast.Name) and n.func.id == name for k in n.keywords]


def method_call_keywords(attr):
    return [k.arg for n in _calls() if isinstance(n.func, ast.Attribute) and n.func.attr == attr for k in n.keywords]


kids = collections.defaultdict(list)
for c in mt.get_children():
    kids[c.get_name()].append(c)

rows = []
for i, f in enumerate(main.body):
    if not isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef)) or f.name == "bootstrap":
        continue
    t = next(c for c in kids[f.name] if c.get_lineno() == f.lineno)
    r = []
    if f.decorator_list: r.append("decorated")
    if isinstance(f, ast.AsyncFunctionDef): r.append("async")
    if not all(const_default(d) for d in f.args.defaults + [d for d in f.args.kw_defaults if d]): r.append("nonconst-default")
    if any(isinstance(n, (ast.Nonlocal, ast.Global)) for n in ast.walk(f)): r.append("nonlocal")
    if any(isinstance(n, ast.ClassDef) for n in ast.walk(f)): r.append("classdef")
    if len(mb.get(f.name, [])) != 1: r.append("rebound-self")
    is_method = False
    for a in attr_stores(f.name):
        if isinstance(a.value, ast.Name) and a.value.id in tk_roots:
            continue
        if f.name in METHODS:
            is_method = True
            continue
        r.append("stored-on:" + ast.unparse(a))
    deps, late, gdeps, imps = [], [], set(), set()
    for n in sorted(t.get_frees()):
        if not mt.lookup(n).is_local():
            r.append("??:" + n)
        elif stable_before(n, i):
            deps.append(n)
        elif (n == f.name or late_ok(n)) and uses_ok(f, n):
            late.append(n)
        else:
            b = mb.get(n, [])
            r.append(("forward:" if len(b) == 1 and b[0][1] is not None else "rebound:") + n)
    for tb in tables_under(t):
        for sym in tb.get_symbols():
            if sym.is_global() and sym.is_referenced() and not sym.is_declared_global():
                n = sym.get_name()
                if n in ("__file__", "__name__", "__spec__", "__doc__"): r.append("dunder")
                elif n in gl_names: r.append("global-rebound:" + n)
                elif n in plain_imports: imps.add(n)
                elif n in BUILTINS: pass
                else: gdeps.add(n)
    all_deps = set(deps) | set(late) | gdeps
    if is_method:
        bad = sorted(d for d in all_deps if not d.startswith("_"))
        if bad: r.append("method-dep-not-underscored:" + ",".join(bad))
        attr = ast.unparse(attr_stores(f.name)[0]).rsplit(".", 1)[-1]
        for kw in method_call_keywords(attr):
            if kw is None: continue  # ``**opts`` at a Tk call: Tk option dicts never hold ``_`` keys
            if kw in all_deps: r.append("kw-collision:" + kw)
    elif f.args.kwarg:
        for kw in call_keywords(f.name):
            if kw is None: r.append("**kwargs:splat-call")
            elif kw in all_deps: r.append("**kwargs:collision:" + kw)
    rows.append(dict(name=f.name, method=is_method, line=f.lineno, end=f.end_lineno, idx=i, bdeps=sorted(set(deps) | set(late)),
                     mdeps=[], gdeps=sorted(gdeps), imps=sorted(imps), late=sorted(late), reasons=r, safe=not r))
json.dump(rows, open(OUT, "w"), indent=1)
for x in rows:
    print("SAFE   " if x["safe"] else "blocked", x["name"], "" if x["safe"] else x["reasons"], ("late=" + ",".join(x["late"])) if x["late"] else "")
print(sum(x["safe"] for x in rows), "of", len(rows), "main() helpers liftable")
