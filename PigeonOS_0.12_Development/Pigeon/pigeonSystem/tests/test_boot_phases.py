"""The ``bootstrap()`` phases in ``pigeon.core.boot`` must stay wired correctly.

Each phase reads its inputs as ``x = ctx.x`` at the top of ``run`` and writes
back what later phases need as ``ctx.y = y``. These checks catch the edits
that would break that silently: reading a name nobody wrote yet, or a name
that is neither local, imported nor a builtin.
"""

import ast
import builtins
import glob
import os
import symtable
import unittest

_SYS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BOOT = os.path.join(_SYS, "pigeon", "core", "boot")


def _phase_paths(prefix="p"):
    """``p*`` = bootstrap() phases, ``m*`` = main() setup phases."""
    return sorted(glob.glob(os.path.join(_BOOT, f"{prefix}[0-9][0-9]_*.py")))


def _all_phase_paths():
    return _phase_paths("m") + _phase_paths("p")


def _run_fn(tree):
    return next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "run")


def _is_ctx_attr(node, store):
    return (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
            and node.value.id == "ctx" and isinstance(node.ctx, ast.Store if store else ast.Load))


def _prologue_reads(fn):
    """Names read by the leading ``x = ctx.x`` lines (plain or ``try``-guarded)."""
    out = []
    for stmt in fn.body:
        inner = stmt
        if isinstance(stmt, ast.Try) and len(stmt.body) == 1 and len(stmt.handlers) == 1:
            inner = stmt.body[0]
        if isinstance(inner, ast.Assign) and _is_ctx_attr(inner.value, store=False):
            out.append(inner.value.attr)
        else:
            break
    return out


def _seed_names(var):
    """Keyword names of the ``<var> = _BootContext(...)`` seed in pigeon_0_12.py."""
    src = open(os.path.join(_SYS, "pigeon_0_12.py"), encoding="utf-8").read()
    for n in ast.walk(ast.parse(src)):
        if (isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name) and n.targets[0].id == var
                and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "_BootContext"):
            return {k.arg for k in n.value.keywords}
    raise AssertionError(f"no {var} = _BootContext(...) in pigeon_0_12.py")


class BootPhaseWiringTests(unittest.TestCase):
    def test_phase_order_matches_callers(self):
        src = open(os.path.join(_SYS, "pigeon_0_12.py"), encoding="utf-8").read()
        for prefix, arg in (("m", "_main_ctx"), ("p", "ctx")):
            mods = [os.path.basename(p)[:-3] for p in _phase_paths(prefix)]
            calls = [ln.strip() for ln in src.splitlines()
                     if ln.strip().startswith(f"_boot_{prefix}") and ln.strip().endswith(f".run({arg})")]
            self.assertEqual(calls, [f"_boot_{m}.run({arg})" for m in mods])

    def test_prologue_reads_only_names_already_written(self):
        for prefix, var in (("m", "_main_ctx"), ("p", "ctx")):
            written = _seed_names(var)
            for path in _phase_paths(prefix):
                fn = _run_fn(ast.parse(open(path, encoding="utf-8").read()))
                for name in _prologue_reads(fn):
                    self.assertIn(name, written, f"{os.path.basename(path)} reads ctx.{name} before any phase wrote it")
                for node in ast.walk(fn):
                    if isinstance(node, ast.Assign):
                        for t in node.targets:
                            if _is_ctx_attr(t, store=True):
                                written.add(t.attr)

    def test_phases_only_read_bound_names(self):
        for path in _all_phase_paths():
            src = open(path, encoding="utf-8").read()
            tree = ast.parse(src)
            known = set(dir(builtins))
            for stmt in tree.body:
                if isinstance(stmt, (ast.Import, ast.ImportFrom)):
                    known |= {(a.asname or a.name).split(".")[0] for a in stmt.names}
                elif isinstance(stmt, ast.FunctionDef):
                    known.add(stmt.name)
            table = symtable.symtable(src, path, "exec")

            def walk(t):
                yield t
                for c in t.get_children():
                    yield from walk(c)

            for t in walk(table):
                for sym in t.get_symbols():
                    if sym.is_global() and sym.is_referenced():
                        self.assertIn(sym.get_name(), known, f"{os.path.basename(path)}: {sym.get_name()}")

    def test_context_supports_copy_and_pickle(self):
        import copy
        import pickle

        from pigeon.core.boot.context import BootContext

        ctx = BootContext(a=[1])
        self.assertEqual(copy.copy(ctx).a, [1])
        self.assertEqual(copy.deepcopy(ctx).a, [1])
        self.assertEqual(pickle.loads(pickle.dumps(ctx)).a, [1])
        self.assertIn("a", vars(ctx))
        self.assertNotIn("b", vars(ctx))

    def test_missing_name_raises_name_error(self):
        from pigeon.core.boot.context import BootContext

        ctx = BootContext(a=1)
        self.assertEqual(ctx.a, 1)
        with self.assertRaises(NameError):
            ctx.not_bound_yet



def _deferred_reads(fn):
    """Plain names read inside lambdas / generator expressions of ``fn`` (their own params excluded)."""
    out = set()

    def visit(n, hidden, deferred):
        if isinstance(n, ast.Lambda):
            a = n.args
            h = hidden | {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs + [y for y in (a.vararg, a.kwarg) if y]}
            for d in a.defaults + [k for k in a.kw_defaults if k]:
                visit(d, hidden, deferred)
            visit(n.body, h, True)
            return
        if isinstance(n, (ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            h = hidden | {x.id for g in n.generators for x in ast.walk(g.target) if isinstance(x, ast.Name)}
            d = deferred or isinstance(n, ast.GeneratorExp)
            for c in ast.iter_child_nodes(n):
                visit(c, h, d)
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and deferred and n.id not in hidden:
            out.add(n.id)
            return
        for c in ast.iter_child_nodes(n):
            visit(c, hidden, deferred)

    for stmt in fn.body:
        visit(stmt, set(), False)
    return out


def _local_stores(fn):
    """Names ``run`` binds in its own scope (not inside lambdas / comprehensions)."""
    out = set()

    def visit(n):
        if isinstance(n, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp)):
            return
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
            out.add(n.id)
        elif isinstance(n, (ast.Import, ast.ImportFrom)):
            out.update((a.asname or a.name).split(".")[0] for a in n.names)
        elif isinstance(n, (ast.FunctionDef, ast.ClassDef)):
            out.add(n.name)
            return
        for c in ast.iter_child_nodes(n):
            visit(c)

    for stmt in fn.body:
        inner = stmt.body[0] if isinstance(stmt, ast.Try) and len(stmt.body) == 1 else stmt
        if isinstance(inner, ast.Assign) and _is_ctx_attr(inner.value, store=False) \
                and isinstance(inner.targets[0], ast.Name) and inner.targets[0].id == inner.value.attr:
            continue  # ``x = ctx.x``: the same object, not a new binding
        visit(stmt)
    return out


def _ctx_attrs(fn, store):
    return {n.attr for n in ast.walk(fn) if _is_ctx_attr(n, store)}


def _guarded_names(fn):
    """Names whose prologue read / epilogue write is wrapped in ``try: ... except NameError``."""
    out = set()
    for stmt in fn.body:
        if (isinstance(stmt, ast.Try) and len(stmt.body) == 1 and len(stmt.handlers) == 1
                and isinstance(stmt.handlers[0].type, ast.Name) and stmt.handlers[0].type.id == "NameError"
                and isinstance(stmt.body[0], ast.Assign)):
            a = stmt.body[0]
            if _is_ctx_attr(a.value, store=False):
                out.add(a.value.attr)
            elif _is_ctx_attr(a.targets[0], store=True):
                out.add(a.targets[0].attr)
    return out


class BootPhaseInvariantTests(unittest.TestCase):
    """Invariants the phase split relies on; a hand edit that breaks one would
    change behaviour silently (a stale value, a lookup that can never succeed)."""

    def _group(self, prefix):
        return [(os.path.basename(p)[:-3], _run_fn(ast.parse(open(p, encoding="utf-8").read())))
                for p in _phase_paths(prefix)]

    def test_deferred_reads_never_see_a_later_rebinding(self):
        # A lambda in phase k closes over phase k's local. If a later phase binds
        # the same name, the original single-scope code would have seen the new
        # value; the split one would not. Such reads must go through ctx.X.
        for prefix in ("m", "p"):
            group = self._group(prefix)
            for k, (mod, fn) in enumerate(group):
                later = set().union(*[_local_stores(f) for _m, f in group[k + 1:]]) if k + 1 < len(group) else set()
                stale = sorted(_deferred_reads(fn) & later - {"ctx"})
                self.assertEqual(stale, [], f"{mod}: deferred code reads names a later phase rebinds")

    def test_every_ctx_read_has_a_writer(self):
        for prefix, var in (("m", "_main_ctx"), ("p", "ctx")):
            group = self._group(prefix)
            written = _seed_names(var).union(*[_ctx_attrs(f, store=True) for _m, f in group])
            for mod, fn in group:
                missing = sorted(_ctx_attrs(fn, store=False) - written)
                self.assertEqual(missing, [], f"{mod} reads ctx names nothing ever writes")

    def test_ctx_is_only_the_phase_parameter(self):
        for prefix in ("m", "p"):
            for mod, fn in self._group(prefix):
                self.assertEqual([a.arg for a in fn.args.args], ["ctx"], mod)
                self.assertNotIn("ctx", _local_stores(fn), f"{mod} rebinds ctx")

    def test_seeded_module_globals_are_never_rebound(self):
        # The seeds copy pigeon_0_12 globals when main() / bootstrap() start. A
        # global rebound later (``global X; X = ...``) would not reach the phases.
        src = open(os.path.join(_SYS, "pigeon_0_12.py"), encoding="utf-8").read()
        rebound = {nm for n in ast.walk(ast.parse(src)) if isinstance(n, ast.Global) for nm in n.names}
        for var in ("_main_ctx", "ctx"):
            self.assertEqual(sorted(_seed_names(var) & rebound), [], var)

    def test_only_expected_names_are_path_dependent(self):
        # ``try: x = ctx.x / ctx.x = x except NameError`` marks a name bound only
        # on one path. Today that is splash_tick (only with _PIGEON_EXT). A new
        # one is fine but should be a conscious decision: add it here.
        found = set()
        for prefix in ("m", "p"):
            for _mod, fn in self._group(prefix):
                found |= _guarded_names(fn)
        self.assertEqual(found, {"splash_tick"})


if __name__ == "__main__":
    unittest.main()
