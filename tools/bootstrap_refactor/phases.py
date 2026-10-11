"""Pass 13: cut bootstrap() into phase modules that share a boot context.

Usage (from ``pigeonSystem``)::

    python3 phases.py pigeon_0_12.py PLAN.json            # analyse only
    python3 phases.py pigeon_0_12.py PLAN.json --write    # rewrite

``PLAN.json`` is a list of ``{"module": "p01_state", "start": 0, "doc": "..."}``;
``start`` is the index of the phase's first top-level statement in
``bootstrap()``, and each phase runs to the next one's start.

Each phase becomes ``pigeon/core/boot/<module>.py`` with ``run(ctx)``:

- a prologue ``x = ctx.x`` for every name the phase reads that an earlier
  phase (or ``main()`` / the module, via the seed) bound;
- the phase's statements, verbatim;
- an epilogue ``ctx.y = y`` for every name it binds that a later phase reads.

``bootstrap()`` becomes ``ctx = _BootContext(<seed>)`` plus one
``_boot_<module>.run(ctx)`` call per phase. The seed holds the ``main()``
locals and non-import module globals the phases read; plain unconditional
module imports are imported by the phase module itself.

Why this is behaviour-preserving -- checked, or the tool refuses:

- no ``return`` / ``yield`` / ``nonlocal`` / ``global`` / ``del`` / walrus at
  bootstrap level, no ``locals()``;
- every prologue name is definitely bound when its phase starts (so the read
  cannot raise where the original would not have); every epilogue name is
  definitely bound when its phase ends;
- *deferred* code (lambdas, generator expressions) keeps reading live values:
  a name a deferred scope reads must not be rebound by any later phase. The
  exception is a name bound exactly once, by a simple top-level statement of
  a later phase, and read here only from deferred code (e.g. the pass-7
  ``_late(lambda: X, "X")`` form, or ``command=lambda: X()``): those reads
  become ``ctx.X`` and ``ctx.X = X`` is published right after X's binding, so
  the lookup still happens at call time and still raises ``NameError`` before
  X exists (``BootContext`` raises ``NameError`` for a missing name);
- ``except E as e`` names are local to their handler (Python unbinds them);
- ``main()`` locals are stable while bootstrap() runs (it runs from the Tk
  event loop, after main()'s last binding); module globals read by the phases
  are never rebound with ``global``.

Proof printed: each phase's ``run`` body, minus prologue / epilogue / publish
lines and with the ``ctx.X`` rewrite undone, has the same AST as the original
statements.
"""
import ast
import builtins
import collections
import copy
import io
import json
import os
import sys
import symtable
import tokenize

SRC, PLAN = sys.argv[1], sys.argv[2]
WRITE = "--write" in sys.argv
src = open(SRC, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
boot = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "bootstrap")
st = symtable.symtable(src, SRC, "exec")
mt = next(c for c in st.get_children() if c.get_name() == "main")
# ``--scope=main`` (pass 16): phase main()'s statements *before* ``def bootstrap``
# instead; the rest of main() (and bootstrap()) read the results back.
SCOPE = "main" if "--scope=main" in sys.argv else "bootstrap"
if SCOPE == "main":
    host = main
    K = main.body.index(boot)
    B = list(main.body[:K])
    TAIL = list(main.body[K:])
    HIND = 4
else:
    host = boot
    B = list(boot.body)
    TAIL = []
    HIND = 8
has_doc = bool(B) and isinstance(B[0], ast.Expr) and isinstance(getattr(B[0], "value", None), ast.Constant) and isinstance(B[0].value.value, str)
plan = json.load(open(PLAN))
assert plan[0]["start"] == (1 if has_doc else 0), f"first phase must start at {host.name}()'s first statement"
bounds = [p["start"] for p in plan] + [len(B)]
assert bounds == sorted(set(bounds)), "phase starts must increase"
errors = []

# ---------------------------------------------------------------- scopes
INNER = (ast.Lambda, ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
DEFERRED = (ast.Lambda, ast.GeneratorExp)


def inner_locals(n):
    if isinstance(n, ast.Lambda):
        a = n.args
        return {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs + [y for y in (a.vararg, a.kwarg) if y]}
    out = set()
    for g in n.generators:
        out |= {x.id for x in ast.walk(g.target) if isinstance(x, ast.Name)}
    return out


def _tables_under(t):
    yield t
    for c in t.get_children():
        yield from _tables_under(c)


def scan(stmt, strict=True):
    """(stores, loads, deferred_loads) for one bootstrap-level statement.

    Scope-aware: names local to a lambda / comprehension are not bootstrap
    names. Local-variable annotations are skipped (never evaluated)."""
    stores, loads, dloads, eloads, deferred_nodes = set(), set(), set(), set(), []

    def visit(n, hidden, deferred):
        if isinstance(n, ast.ClassDef) and n is stmt and SCOPE == "main":
            # A class statement at main() level (the null-object classes): the class
            # name is bound here; every outer name its body / methods use is a load,
            # treated as deferred (methods run later).
            stores.add(n.name)
            for d in n.decorator_list + n.bases + [k.value for k in n.keywords]:
                visit(d, hidden, deferred)
            ct = next(c for c in mt.get_children() if c.get_name() == n.name and c.get_lineno() == n.lineno)
            for tb in _tables_under(ct):
                for sym in tb.get_symbols():
                    if sym.is_referenced() and (sym.is_free() or (sym.is_global() and not sym.is_declared_global())):
                        loads.add(sym.get_name())
                        dloads.add(sym.get_name())
            return
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if strict:
                errors.append(f"line {n.lineno}: nested def/class in {host.name}()")
            return
        if strict and isinstance(n, (ast.Return, ast.Yield, ast.YieldFrom, ast.Nonlocal, ast.Global, ast.Delete, ast.Await)):
            errors.append(f"line {n.lineno}: {type(n).__name__} at {host.name}() level")
        if strict and isinstance(n, ast.NamedExpr):
            errors.append(f"line {n.lineno}: walrus")
        if strict and isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ("locals", "vars", "eval", "exec"):
            errors.append(f"line {n.lineno}: {n.func.id}()")
        if isinstance(n, INNER):
            h = hidden | inner_locals(n)
            d = deferred or isinstance(n, DEFERRED)
            if isinstance(n, ast.Lambda):
                for x in n.args.defaults + [k for k in n.args.kw_defaults if k]:
                    visit(x, hidden, deferred)
                visit(n.body, h, d)
            else:
                # the first iterable is evaluated in the enclosing scope, eagerly
                for k, g in enumerate(n.generators):
                    visit(g.iter, hidden if k == 0 else h, deferred if k == 0 else d)
                    for c in g.ifs:
                        visit(c, h, d)
                for part in ("elt", "key", "value"):
                    if getattr(n, part, None) is not None:
                        visit(getattr(n, part), h, d)
            return
        if isinstance(n, ast.AnnAssign):
            visit(n.target, hidden, deferred)
            if n.value is not None:
                visit(n.value, hidden, deferred)
            return
        if isinstance(n, ast.Name):
            if n.id in hidden:
                return
            if isinstance(n.ctx, ast.Store):
                if not deferred and not hidden:
                    stores.add(n.id)
            else:
                loads.add(n.id)
                if deferred:
                    dloads.add(n.id)
                    deferred_nodes.append(n)
                else:
                    eloads.add(n.id)
            return
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                stores.add((a.asname or a.name).split(".")[0])
        if isinstance(n, ast.ExceptHandler) and n.name:
            # ``except E as e`` unbinds ``e`` when the handler ends: local to the handler
            if n.type is not None:
                visit(n.type, hidden, deferred)
            for c in n.body:
                visit(c, hidden | {n.name}, deferred)
            return
        for c in ast.iter_child_nodes(n):
            visit(c, hidden, deferred)

    visit(stmt, set(), False)
    return stores, loads, dloads, deferred_nodes, eloads


SC = [scan(s) for s in B]
STORES = [x[0] for x in SC]
LOADS = [x[1] for x in SC]
DLOADS = [x[2] for x in SC]
DNODES = [x[3] for x in SC]
ELOADS = [x[4] for x in SC]
BOOT = set().union(*STORES)
bind_count = collections.Counter()
for s in STORES:
    bind_count.update(s)


def binds_here(s, name):
    return name in scan(s)[0]


def definitely_binds(stmts, name):
    for s in stmts:
        if isinstance(s, (ast.Assign, ast.AugAssign, ast.Import, ast.ImportFrom, ast.Expr)):
            if binds_here(s, name):
                return True
        elif isinstance(s, ast.AnnAssign):
            if s.value is not None and binds_here(s, name):
                return True
        elif isinstance(s, ast.If):
            if s.orelse and definitely_binds(s.body, name) and definitely_binds(s.orelse, name):
                return True
        elif isinstance(s, ast.Try):
            if definitely_binds(s.finalbody, name):
                return True
            if definitely_binds(s.body + s.orelse, name) and all(definitely_binds(h.body, name) for h in s.handlers):
                return True
        elif isinstance(s, ast.With):
            if definitely_binds(s.body, name):
                return True
    return False


# ---------------------------------------------------------------- outer scopes
main_locals = {s.get_name() for s in mt.get_symbols() if s.is_local()} if SCOPE == "bootstrap" else set()

# what the rest of the host function reads / (re)binds after the phased statements
TAIL_LOADS, TAIL_STORES = set(), set()
for s_ in TAIL:
    if s_ is boot:
        bt = next(c for c in mt.get_children() if c.get_name() == "bootstrap")
        TAIL_LOADS |= set(bt.get_frees())
        TAIL_STORES.add("bootstrap")
    else:
        st_, ld_, _d, _n, _e = scan(s_, strict=False)
        TAIL_LOADS |= ld_
        TAIL_STORES |= st_
BUILTINS = set(dir(builtins))
mod_binds = collections.Counter()
direct = {}  # name -> import line
for s in tree.body:
    for n in ast.walk(s) if not isinstance(s, (ast.FunctionDef, ast.ClassDef)) else [s]:
        if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            mod_binds[n.name] += 1
        elif isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            mod_binds[n.id] += 1
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                mod_binds[(a.asname or a.name).split(".")[0]] += 1
for s in tree.body:
    if isinstance(s, ast.Import):
        for a in s.names:
            if a.asname or "." not in a.name:
                direct[a.asname or a.name] = f"import {a.name}" + (f" as {a.asname}" if a.asname else "")
    elif isinstance(s, ast.ImportFrom) and s.level == 0 and s.module != "__future__":
        for a in s.names:
            direct[a.asname or a.name] = f"from {s.module} import {a.name}" + (f" as {a.asname}" if a.asname else "")
direct = {k: v for k, v in direct.items() if mod_binds[k] == 1}
gl_names = {nm for n in ast.walk(tree) if isinstance(n, ast.Global) for nm in n.names}


# ---------------------------------------------------------------- the _late(lambda: X, "X") form
def late_calls(stmt):
    out = []
    for n in ast.walk(stmt):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_late" and len(n.args) == 2
                and isinstance(n.args[0], ast.Lambda) and isinstance(n.args[0].body, ast.Name)
                and not n.args[0].args.args and isinstance(n.args[1], ast.Constant) and n.args[1].value == n.args[0].body.id):
            out.append(n)
    return out


def single_simple_binding(name):
    idx = [i for i, st_ in enumerate(STORES) if name in st_]
    if len(idx) != 1 or bind_count[name] != 1:
        return None
    s_ = B[idx[0]]
    if isinstance(s_, (ast.Assign, ast.AnnAssign)) and not any(
            isinstance(x, ast.Name) and x.id == name and isinstance(x.ctx, ast.Store)
            for x in ast.walk(s_.value if s_.value is not None else ast.Constant(0))):
        tg = s_.targets if isinstance(s_, ast.Assign) else [s_.target]
        if any(isinstance(t, ast.Name) and t.id == name for t in tg):
            return idx[0]
    return None


# ---------------------------------------------------------------- per phase
phases = []
seed = set()
publish = {}  # name -> statement index after which ``ctx.name = name`` goes
for k, p in enumerate(plan):
    a, b = bounds[k], bounds[k + 1]
    stmts = B[a:b]
    stores_p = set().union(*STORES[a:b])
    loads_p = set().union(*LOADS[a:b])
    dloads_p = set().union(*DLOADS[a:b])
    before = set().union(*STORES[:a]) if a else set()
    after_stores = (set().union(*STORES[b:]) if b < len(B) else set()) | TAIL_STORES
    after_loads = (set().union(*LOADS[b:]) if b < len(B) else set()) | TAIL_LOADS
    inputs, imports, seeds, rewrites = [], set(), set(), set()
    maybe_in, maybe_out = set(), set()
    for n in sorted(loads_p):
        if n in BOOT:
            if n in before:
                if not definitely_binds(B[:a], n):
                    if SCOPE == "main":
                        maybe_in.add(n)  # guarded read: stays unbound here too
                    else:
                        errors.append(f"{p['module']}: reads {n}, which may be unbound when the phase starts")
                inputs.append(n)
            elif n not in stores_p:
                if n not in dloads_p:
                    errors.append(f"{p['module']}: reads {n} before bootstrap() binds it")
        elif n in main_locals:
            inputs.append(n)
            seeds.add(n)
        elif mod_binds[n]:
            if n in direct:
                imports.add(direct[n])
            else:
                if n in gl_names:
                    errors.append(f"{p['module']}: module global {n} is rebound with `global`")
                inputs.append(n)
                seeds.add(n)
        elif n in ("__file__", "__name__", "__spec__"):
            inputs.append(n)  # the host module's value, not the phase module's
            seeds.add(n)
        elif n in BUILTINS:
            pass
        else:
            errors.append(f"{p['module']}: unresolved name {n}")
    # Deferred reads must not see a later rebinding. Exception: a name bound
    # exactly once, by a simple top-level statement of a later phase, and read
    # only from deferred code here -- read it as ``ctx.X`` (published right
    # after its binding), which looks it up at call time like the closure did.
    eloads_p = set().union(*ELOADS[a:b])
    for n in sorted(dloads_p & after_stores):
        fi = single_simple_binding(n)
        if fi is not None and fi >= b and n not in eloads_p and n not in stores_p and n not in before:
            rewrites.add(n)
            publish[n] = fi
        else:
            errors.append(f"{p['module']}: deferred code reads {n}, which a later phase (re)binds")
    # names used only in local-variable annotations: import them if we can (lint only)
    for s_ in stmts:
        for x in ast.walk(s_):
            if isinstance(x, ast.AnnAssign):
                for y in ast.walk(x.annotation):
                    if isinstance(y, ast.Name) and y.id in direct:
                        imports.add(direct[y.id])
    # rewritten names are read through ctx only: no prologue for them
    inputs = [n for n in inputs if n not in rewrites]
    outputs = sorted(n for n in stores_p if n in after_loads)
    for n in outputs:
        if (n not in inputs or n in maybe_in) and not definitely_binds(stmts, n):
            if SCOPE == "main":
                maybe_out.add(n)  # guarded write: only when this path bound it
            else:
                errors.append(f"{p['module']}: {n} is read later but not bound on every path through the phase")
    seed |= seeds
    phases.append(dict(p, a=a, b=b, inputs=inputs, outputs=outputs, imports=sorted(imports), rewrites=sorted(rewrites),
                       maybe_in=sorted(maybe_in), maybe_out=sorted(maybe_out)))

for ph in phases:
    ph["publish"] = sorted(n for n, i in publish.items() if ph["a"] <= i < ph["b"])

print(f"{'phase':28} stmts  in  out  late")
for ph in phases:
    print(f"{ph['module']:28} {ph['b'] - ph['a']:5} {len(ph['inputs']):4} {len(ph['outputs']):4} {len(ph['rewrites']):5}")
print("seed:", len(seed), "names")
if errors:
    print("\n".join("ERROR " + e for e in errors[:60]))
    print(len(errors), "errors")
    sys.exit(1)
if not WRITE:
    sys.exit(0)

# ---------------------------------------------------------------- write
ROOT = os.path.dirname(os.path.abspath(SRC))
PKG = os.path.join(ROOT, "pigeon", "core", "boot")
os.makedirs(PKG, exist_ok=True)

string_inner = set()  # physical lines strictly inside a multi-line string: never re-indented
for t in tokenize.generate_tokens(io.StringIO(src).readline):
    if t.type == tokenize.STRING and t.end[0] > t.start[0]:
        string_inner.update(range(t.start[0] + 1, t.end[0] + 1))


def seg_start(i):
    ln = B[i].lineno
    while ln > 1 and lines[ln - 2].strip().startswith("#") and lines[ln - 2].startswith(" " * HIND):
        ln -= 1
    return ln


def seg_lines(a, b):
    s = seg_start(a)
    e = seg_start(b) - 1 if b < len(B) else B[-1].end_lineno
    return s, e


def norm(n):
    n = copy.deepcopy(n)
    for x in ast.walk(n):
        for f in ("lineno", "col_offset", "end_lineno", "end_col_offset"):
            if hasattr(x, f):
                setattr(x, f, 0)
    return ast.dump(n, include_attributes=False)


class Unrewrite(ast.NodeTransformer):
    def __init__(self, names):
        self.names = set(names)

    def visit_Attribute(self, n):
        self.generic_visit(n)
        if isinstance(n.value, ast.Name) and n.value.id == "ctx" and isinstance(n.ctx, ast.Load) and n.attr in self.names:
            return ast.Name(id=n.attr, ctx=ast.Load())
        return n


for ph in phases:
    s, e = seg_lines(ph["a"], ph["b"])
    body = []
    for ln in range(s, e + 1):
        t = lines[ln - 1]
        if ln in string_inner or not t.strip():
            body.append(t if t.strip() else "\n")
        else:
            assert t.startswith(" " * HIND), (ln, t)
            body.append(t[HIND - 4:])
    # read rewritten names as ``ctx.X`` (insert right to left within a line)
    hits = collections.defaultdict(list)
    for i in range(ph["a"], ph["b"]):
        for nd in DNODES[i]:
            if nd.id in ph["rewrites"]:
                assert nd.lineno == nd.end_lineno and nd.lineno not in string_inner, nd.lineno
                hits[nd.lineno].append(nd.col_offset - (HIND - 4))
    for ln, cols in hits.items():
        t = body[ln - s]
        for c in sorted(cols, reverse=True):
            t = t[:c] + "ctx." + t[c:]
        body[ln - s] = t
    # publish ``ctx.X = X`` right after X's binding
    ends = {B[publish_i].end_lineno: n for n, publish_i in publish.items() if ph["a"] <= publish_i < ph["b"]}
    out = []
    for off, t in enumerate(body):
        out.append(t)
        ln = s + off
        if ln in ends:
            out.append(f"    ctx.{ends[ln]} = {ends[ln]}\n")
    text = "".join(out)
    def guarded(stmt):
        # ``NameError`` covers a missing ctx entry and an unbound local alike
        return f"    try:\n        {stmt}\n    except NameError:\n        pass\n"

    pro = "".join(guarded(f"{n} = ctx.{n}") if n in ph["maybe_in"] else f"    {n} = ctx.{n}\n" for n in ph["inputs"])
    epi = "".join(guarded(f"ctx.{n} = {n}") if n in ph["maybe_out"] else f"    ctx.{n} = {n}\n"
                  for n in ph["outputs"] if n not in ph["publish"])
    mod = (
        f'"""{ph["doc"]}\n\n'
        f"Phase {phases.index(ph) + 1} of ``{host.name}()`` in ``pigeon_0_12.py``, moved verbatim. ``run``\n"
        "reads the names it needs from the shared boot context, runs the original\n"
        "statements, and writes back the names later phases read.\n"
        '"""\n\nfrom __future__ import annotations\n\n'
        + "".join(i + "\n" for i in ph["imports"])
        + "\n\ndef run(ctx) -> None:\n"
        + (pro + "\n" if pro else "")
        + text.rstrip("\n") + "\n"
        + ("\n" + epi if epi else "")
    )
    # proof
    fn = next(x for x in ast.parse(mod).body if isinstance(x, ast.FunctionDef) and x.name == "run")
    got = fn.body[len(ph["inputs"]):]
    n_epi = len([n for n in ph["outputs"] if n not in ph["publish"]])
    if n_epi:
        got = got[:-n_epi]
    got = [g for g in got if not (isinstance(g, ast.Assign) and isinstance(g.targets[0], ast.Attribute)
                                  and isinstance(g.targets[0].value, ast.Name) and g.targets[0].value.id == "ctx"
                                  and g.targets[0].attr in ph["publish"])]
    got = [Unrewrite(ph["rewrites"]).visit(copy.deepcopy(g)) for g in got]
    want = B[ph["a"]:ph["b"]]
    assert len(got) == len(want) and all(norm(x) == norm(y) for x, y in zip(got, want)), f"AST mismatch in {ph['module']}"
    open(os.path.join(PKG, ph["module"] + ".py"), "w", encoding="utf-8").write(mod)

if SCOPE == "bootstrap":
    open(os.path.join(PKG, "__init__.py"), "w").write('"""``bootstrap()`` split into phases; see ``context.BootContext``."""\n')
    open(os.path.join(PKG, "context.py"), "w").write('''"""Shared state for the ``bootstrap()`` phases in ``pigeon.core.boot``."""

    from __future__ import annotations


    class BootContext:
        """One attribute per former ``bootstrap()`` local (plus the ``main()`` locals
        and module globals the phases read, seeded up front).

        Phases read their inputs from it when they start and write back what later
        phases need when they end. Reading a name nobody has bound yet raises
        ``NameError`` -- what the original closure lookup raised.
        """

        def __init__(self, **names: object) -> None:
            self.__dict__.update(names)

        def __getattr__(self, name: str) -> object:
            raise NameError(f"name {name!r} is not defined (not bound yet in bootstrap)")
    ''')

# rewrite the host function
bs = seg_start(1 if has_doc else 0)
while bs > host.lineno + 1 and not lines[bs - 2].strip():
    bs -= 1  # drop blank lines between the def (or docstring) and the first phase
be = B[-1].end_lineno
seeds = sorted(seed)
if SCOPE == "bootstrap":
    new = [f"        # Startup runs as {len(phases)} phases in pigeon/core/boot/ (see BootContext). Seed the\n",
           "        # shared context with the main() locals and module globals they read.\n",
           "        ctx = _BootContext(\n"] + [f"            {n}={n},\n" for n in seeds] + ["        )\n"]
    new += [f"        _boot_{ph['module']}.run(ctx)\n" for ph in phases]
else:
    bound = set().union(*STORES)
    pull = sorted(n for n in TAIL_LOADS if n in bound)
    maybe = {n for n in pull if not definitely_binds(B, n)}  # e.g. bound only on the splash path
    new = [f"    # Setup runs as {len(phases)} phases in pigeon/core/boot/ (m*.py, see BootContext);\n",
           "    # the rest of main() and bootstrap() read their results back below.\n",
           "    _main_ctx = _BootContext(\n"] + [f"        {n}={n},\n" for n in seeds] + ["    )\n"]
    new += [f"    _boot_{ph['module']}.run(_main_ctx)\n" for ph in phases]
    new += ["\n"]
    for n in pull:
        if n in maybe:
            new += [f"    try:\n        {n} = _main_ctx.{n}\n    except NameError:\n        pass\n"]
        else:
            new += [f"    {n} = _main_ctx.{n}\n"]
    new += ["\n"]
src2 = "".join(lines[: bs - 1] + new + lines[be:])
anchor = "from pigeon.core.boot.context import BootContext as _BootContext\n"
imps = "".join(f"from pigeon.core.boot import {ph['module']} as _boot_{ph['module']}\n" for ph in phases)
if anchor in src2:
    src2 = src2.replace(anchor, anchor + imps, 1)
else:
    a2 = "from pigeon.core import device_control as _core_device_control\n"
    assert a2 in src2
    src2 = src2.replace(a2, a2 + anchor + imps, 1)
open(SRC, "w", encoding="utf-8").write(src2)
print("wrote", len(phases), "phases into", host.name + "()")
