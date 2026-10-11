"""Pass 15: prune what the boot phases no longer use, to a fixpoint.

Usage (from ``pigeonSystem``)::

    python3 prune.py pigeon_0_12.py

Repeats until nothing changes:

1. In each phase's ``run``, drop a top-level ``name = <expr>`` whose name is
   never read again in that phase and not written to ``ctx`` -- only when
   ``<expr>`` is side-effect free: a literal, a name, ``ctx.x``, a
   ``_core_*`` attribute, ``time.monotonic()``, a lambda, or
   ``_bind_deps`` / ``_bind_method_deps`` / ``_late`` over those.
2. Drop ``ctx.x = x`` writes, and ``x=x`` seeds in ``bootstrap()``, for names
   no phase reads (no ``ctx.x`` load anywhere under ``pigeon/core/boot``).

A phase statement that binds a name *and* does something else (a call, a
widget) is never touched.
"""
import ast
import glob
import os
import re
import sys

SRC = sys.argv[1]
ROOT = os.path.dirname(os.path.abspath(SRC))
PHASES = sorted(glob.glob(os.path.join(ROOT, "pigeon", "core", "boot", "p[0-9][0-9]_*.py")))


def pure(v):
    if v is None or isinstance(v, (ast.Constant, ast.Name, ast.Lambda)):
        return True
    if isinstance(v, ast.Attribute):
        return isinstance(v.value, ast.Name) and (v.value.id == "ctx" or v.value.id.startswith("_core_"))
    if isinstance(v, (ast.Tuple, ast.List)):
        return all(pure(e) for e in v.elts)
    if isinstance(v, ast.Call):
        f = ast.unparse(v.func)
        if f == "time.monotonic":
            return not v.args and not v.keywords
        if f in ("_bind_deps", "_bind_method_deps", "_late"):
            return all(pure(a) for a in v.args) and all(pure(k.value) for k in v.keywords)
    return False


def drop_lines(path, spans):
    L = open(path, encoding="utf-8").read().splitlines(keepends=True)
    gone = set()
    for a, b in spans:
        gone |= set(range(a, b + 1))
    s = "".join(l for i, l in enumerate(L, 1) if i not in gone)
    s = re.sub(r"\n{3,}(    \S)", r"\n\n\1", s)
    open(path, "w", encoding="utf-8").write(s)


def ctx_reads():
    out = set()
    for p in PHASES:
        for n in ast.walk(ast.parse(open(p, encoding="utf-8").read())):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "ctx" and isinstance(n.ctx, ast.Load):
                out.add(n.attr)
    return out


removed = []
changed = True
while changed:
    changed = False
    # 1. dead local bindings in each phase
    for p in PHASES:
        t = ast.parse(open(p, encoding="utf-8").read())
        run = next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == "run")
        L = open(p, encoding="utf-8").read().splitlines()
        loads = {}
        for n in ast.walk(run):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                loads[n.id] = loads.get(n.id, 0) + 1
        spans = []
        for s in run.body:
            if not isinstance(s, (ast.Assign, ast.AnnAssign)):
                continue
            tg = s.targets if isinstance(s, ast.Assign) else [s.target]
            if len(tg) != 1 or not isinstance(tg[0], ast.Name):
                continue
            nm = tg[0].id
            if loads.get(nm) or not pure(s.value):
                continue
            a = s.lineno
            while a > 2 and L[a - 2].strip().startswith("#"):
                a -= 1
            spans.append((a, s.end_lineno))
            removed.append(f"{os.path.basename(p)[:-3]}: {nm}")
        if spans:
            drop_lines(p, spans)
            changed = True
    # 2. ctx writes / seeds nobody reads
    reads = ctx_reads()
    for p in PHASES:
        t = ast.parse(open(p, encoding="utf-8").read())
        run = next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == "run")
        spans = [(s.lineno, s.end_lineno) for s in run.body
                 if isinstance(s, ast.Assign) and len(s.targets) == 1 and isinstance(s.targets[0], ast.Attribute)
                 and isinstance(s.targets[0].value, ast.Name) and s.targets[0].value.id == "ctx"
                 and isinstance(s.value, ast.Name) and s.value.id == s.targets[0].attr and s.targets[0].attr not in reads]
        if spans:
            removed += [f"{os.path.basename(p)[:-3]}: ctx write" for _ in spans]
            drop_lines(p, spans)
            changed = True
    src = open(SRC, encoding="utf-8").read()
    seed = next(n for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "_BootContext")
    spans = [(k.value.lineno, k.value.end_lineno) for k in seed.keywords if k.arg not in reads]
    if spans:
        removed += [f"seed: {k.arg}" for k in seed.keywords if k.arg not in reads]
        drop_lines(SRC, spans)
        changed = True
print(len(removed), "removed")
for r in removed:
    print(" ", r)
