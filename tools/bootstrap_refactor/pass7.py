"""Pass 7: lift helpers blocked only by forward references to *functions* (or by recursion).

Usage (from ``pigeonSystem``)::

    python3 pass7.py pigeon_0_12.py p2.json p7.json

A helper qualifies when every blocker in its pass-2 row is ``forward:X`` or
``recursive`` and each such X (and the helper itself, when recursive):

- is bound exactly once at bootstrap()'s top level, by a ``def`` or by
  ``X = _bind_deps(...)`` / ``X = _core_<mod>.X`` (an already-lifted helper);
- is only *called*, *passed as a call argument*, or placed in a dict / list /
  tuple display (a callback table) inside the helper -- never compared,
  assigned, returned or used as an attribute base -- so a forwarding callable
  behaves identically.

A ``nonlocal`` inside the helper is accepted when every such name is bound
inside the helper (by the helper itself or an inner function) (an inner closure updating the helper's own variable);
that moves with the helper unchanged.

Such names are bound at the helper's original ``def`` site as
``X=_late(lambda: X, "X")`` (see ``pigeon.core.binding.late``), which looks
the function up at call time, exactly like the closure did. Nothing moves.
"""
import ast
import json
import sys

src_path, p2_path, out_path = sys.argv[1:4]
tree = ast.parse(open(src_path).read())
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
boot = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "bootstrap")

callable_bound = {}
counts = {}
for s in boot.body:
    for n in ast.walk(s) if not isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) else [s]:
        pass
    if isinstance(s, ast.FunctionDef):
        counts[s.name] = counts.get(s.name, 0) + 1
        callable_bound[s.name] = True
    elif isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
        nm = s.targets[0].id
        v = s.value
        ok = (isinstance(v, ast.Call) and isinstance(v.func, ast.Name) and v.func.id == "_bind_deps") or (
            isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) and v.value.id.startswith("_core_"))
        counts[nm] = counts.get(nm, 0) + 1
        callable_bound[nm] = callable_bound.get(nm, True) and ok
# any other binding of the same name anywhere at bootstrap top level disqualifies it
for s in boot.body:
    if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        continue
    if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Name):
        continue
    for n in ast.walk(s):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store) and n.id in callable_bound:
            callable_bound[n.id] = False
defs = {s.name: s for s in boot.body if isinstance(s, ast.FunctionDef)}


def uses_ok(fn, name):
    """``name`` is only called or passed as an argument inside ``fn``."""
    parents = {}
    for p in ast.walk(fn):
        for c in ast.iter_child_nodes(p):
            parents[c] = p
    for n in ast.walk(fn):
        if isinstance(n, ast.Name) and n.id == name and isinstance(n.ctx, ast.Load):
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
        if isinstance(n, ast.Name) and n.id == name and not isinstance(n.ctx, ast.Load):
            return False
    return True


import symtable
_st = symtable.symtable(open(src_path).read(), src_path, "exec")
_mt = next(c for c in _st.get_children() if c.get_name() == "main")
_bt = next(c for c in _mt.get_children() if c.get_name() == "bootstrap")
_helper_tables = {c.get_name(): c for c in _bt.get_children()}


def internal_nonlocal_only(fn):
    """Every ``nonlocal`` in ``fn`` refers to a local of ``fn`` itself."""
    t = _helper_tables.get(fn.name)
    if t is None:
        return False
    for n in ast.walk(fn):
        if isinstance(n, (ast.Nonlocal, ast.Global)):
            if isinstance(n, ast.Global):
                return False
            for nm in n.names:
                # Bound inside the helper (itself or an inner function) iff it is
                # not one of the helper's free variables.
                if nm in t.get_frees():
                    return False
    return True


rows = json.load(open(p2_path))
out = []
for r in rows:
    if r["safe"] or not r["reasons"]:
        continue
    late = []
    ok = True
    for reason in r["reasons"]:
        kind, _, x = reason.partition(":")
        if kind == "forward":
            late.append(x)
        elif kind == "recursive":
            late.append(r["name"])
        elif kind == "nonlocal" and internal_nonlocal_only(defs[r["name"]]):
            pass
        else:
            ok = False
    if not ok:
        continue
    fn = defs[r["name"]]
    if not all(counts.get(x) == 1 and callable_bound.get(x) and uses_ok(fn, x) for x in late):
        continue
    r = dict(r, safe=True, late=sorted(set(late)), bdeps=sorted(set(r["bdeps"]) | set(late)), reasons=[])
    out.append(r)
json.dump(out, open(out_path, "w"), indent=1)
print(len(out), "helpers liftable with late binding")
