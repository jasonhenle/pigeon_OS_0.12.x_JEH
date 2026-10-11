"""Pass 3: helpers blocked only by forward references.

Such a helper can still be lifted if its bind_deps() call moves down to just
after the last name it depends on is bound -- provided nothing that can run
in between can call it while its name is unbound. Checked conservatively on a
scope-aware call graph (each nested ``def`` is its own node; names resolve
lexically; a lifted helper may call any of its deps; ``x = <expr>`` in a scope
points at every function named in <expr>):

- nothing called (transitively) from the statements in the gap reaches it,
  and nothing executed in the gap even reads its name;
- a function that reaches it is only *referenced* in the gap as a deferred Tk
  registration (after/bind/command=/...) or a _bind_deps() dep;
- if the gap can pump Tk events (update, wait_window, messageboxes, ...), no
  function that reaches it may be referenced anywhere outside a call;
- no thread already started (main() before mainloop, or bootstrap() up to the
  new bind point, directly or via calls) reaches it.

Usage: python3 pass3.py pigeon_0_12.py pass2.json out.json
"""
import ast, glob, json, os, sys, collections

SRC, P2, OUT = sys.argv[1:4]
src = open(SRC).read()
tree = ast.parse(src)
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
boot = next(n for n in main.body if isinstance(n, ast.FunctionDef) and n.name == "bootstrap")
rows = json.load(open(P2))

PUMP = {"update", "update_idletasks", "wait_window", "wait_variable", "wait_visibility", "mainloop",
        "showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askstring", "askquestion",
        "askretrycancel", "askinteger", "askfloat", "askyesnocancel", "askopenfilename",
        "asksaveasfilename", "askdirectory"}
DEFERRED_ATTR = {"after", "after_idle", "bind", "bind_all", "bind_class", "protocol", "configure", "config",
                 "trace_add", "trace", "add_command", "add_checkbutton", "add_radiobutton", "tag_bind"}
FUNC = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)

parent = {}
for p in ast.walk(tree):
    for c in ast.iter_child_nodes(p):
        parent[c] = p

def enclosing(n):
    p = parent.get(n)
    while p is not None and not isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Module)):
        p = parent.get(p)
    return p

def own_nodes(scope):
    """Nodes executed in ``scope`` itself (nested def/lambda bodies excluded)."""
    body = scope.body if isinstance(scope, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef)) else [scope.body]
    stack = list(body) if isinstance(body, list) else body
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(n.decorator_list + n.args.defaults + [d for d in n.args.kw_defaults if d])
            continue
        if isinstance(n, ast.Lambda):
            continue  # lambda bodies are their own scope (node)
        stack.extend(ast.iter_child_nodes(n))

# scope -> name -> list of targets (def nodes, or ("expr", scope, value) for assignments)
bindings = collections.defaultdict(lambda: collections.defaultdict(list))
for scope in [tree] + [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
    for n in own_nodes(scope):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n is not scope:
            bindings[scope][n.name].append(n)
        elif isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None:
            tg = n.targets if isinstance(n, ast.Assign) else [n.target]
            for t in tg:
                if isinstance(t, ast.Name):
                    bindings[scope][t.id].append(("expr", scope, n.value))

def resolve(name, scope):
    s = scope
    while s is not None:
        if name in bindings.get(s, {}):
            return bindings[s][name]
        if isinstance(s, ast.Module): break
        s = enclosing(s)
    return []

def deferred(n):
    node = n
    while node in parent:
        p = parent[node]
        if isinstance(p, ast.keyword) and p.arg == "command":
            return True
        if isinstance(p, ast.Call) and node is not p.func:
            f = p.func
            if isinstance(f, ast.Attribute) and f.attr in DEFERRED_ATTR: return True
            if isinstance(f, ast.Name) and f.id == "_bind_deps": return True
            return False
        if isinstance(p, (ast.stmt, ast.Lambda)): return False
        node = p
    return False

def scan(nodes, scope):
    """Executing ``nodes`` in ``scope``: -> called targets, escaped [(target, deferred)], pump, thread targets."""
    called, escaped, pump, threads = [], [], False, []
    for n in nodes:
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr in PUMP: pump = True
            if (getattr(f, "id", None) or getattr(f, "attr", None)) == "Thread":
                for k in n.keywords:
                    if k.arg == "target":
                        for x in ast.walk(k.value):
                            if isinstance(x, ast.Name): threads += resolve(x.id, scope)
                            if isinstance(x, ast.Lambda): threads.append(x)
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
            p = parent.get(n)
            tg = resolve(n.id, scope)
            if isinstance(p, ast.Call) and p.func is n: called += tg
            else: escaped += [(t, deferred(n)) for t in tg]
        if isinstance(n, ast.Lambda):
            escaped.append((n, deferred(n)))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Lambda):
            called.append(n.func)
    return called, escaped, pump, threads

def nodes_in(stmts):
    for st in stmts:
        yield from own_nodes_stmt(st)
def own_nodes_stmt(st):
    stack = [st]
    while stack:
        n = stack.pop()
        yield n
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            stack.extend(n.decorator_list + n.args.defaults + [d for d in n.args.kw_defaults if d]); continue
        if isinstance(n, ast.Lambda): continue
        stack.extend(ast.iter_child_nodes(n))

# graph over targets: def nodes, lambdas, ("expr",...) tuples
core_dir = os.path.join(os.path.dirname(os.path.abspath(SRC)), "pigeon", "core")
core_pump = {}
for p in glob.glob(os.path.join(core_dir, "*.py")):
    mod = os.path.basename(p)[:-3]
    for fn in ast.parse(open(p).read()).body:
        if isinstance(fn, ast.FunctionDef):
            core_pump[(mod, fn.name)] = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                                            and c.func.attr in PUMP for c in ast.walk(fn))
info = {}
def node_info(t):
    k = id(t)
    if k in info: return info[k]
    info[k] = ([], [], False, [])  # recursion guard
    if isinstance(t, tuple):
        _, scope, value = t
        v = value
        call = v if isinstance(v, ast.Call) and getattr(v.func, "id", "") == "_bind_deps" else None
        ref = call.args[0] if call else v
        if isinstance(ref, ast.Attribute) and isinstance(ref.value, ast.Name) and ref.value.id.startswith("_core_"):
            deps = []
            for kw in (call.keywords if call else []):
                if isinstance(kw.value, ast.Name): deps += resolve(kw.value.id, scope)
            res = (deps, [], core_pump.get((ref.value.id[len("_core_"):], ref.attr), False), [])
        else:
            # the value only "is" a function when it names one: f, a or b, x if c else f,
            # lambda: ..., partial(f, ...). Calls inside the value run at assignment time
            # and are scanned with the enclosing statement.
            res = (fn_refs(value, scope), [], False, [])
    elif isinstance(t, ast.Lambda):
        c, e, p, th = scan(list(own_nodes_stmt(t.body)), t_scope(t))
        res = (c, e, p, th)
    else:
        c, e, p, th = scan(list(own_nodes(t)), t)
        res = (c, e, p, th)
    info[k] = res
    return res
def fn_refs(v, scope):
    if isinstance(v, ast.Name): return resolve(v.id, scope)
    if isinstance(v, ast.Lambda): return [v]
    if isinstance(v, ast.IfExp): return fn_refs(v.body, scope) + fn_refs(v.orelse, scope)
    if isinstance(v, ast.BoolOp): return [t for x in v.values for t in fn_refs(x, scope)]
    if isinstance(v, ast.Call) and (getattr(v.func, "id", None) or getattr(v.func, "attr", None)) == "partial":
        return [t for x in list(v.args) + [k.value for k in v.keywords] for t in fn_refs(x, scope)]
    return []

def t_scope(lam):
    return enclosing(lam)

def closure(starts):
    seen, out, todo = set(), [], list(starts)
    while todo:
        t = todo.pop()
        if id(t) in seen: continue
        seen.add(id(t)); out.append(t)
        todo.extend(node_info(t)[0])
    return out

def reaches(t, target_ids):
    return any(id(x) in target_ids for x in closure([t]))

all_defs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
# every reference-not-call anywhere (possible registered callbacks)
all_escaped = []
for scope in [tree] + all_defs:
    _c, e, _p, _t = scan(list(own_nodes(scope)), scope)
    all_escaped += [x for x, _ in e]
for lam in [n for n in ast.walk(tree) if isinstance(n, ast.Lambda)]:
    all_escaped += [x for x, _ in node_info(lam)[1]]

top_bind = {}
for i, s in enumerate(boot.body):
    if isinstance(s, (ast.FunctionDef, ast.ClassDef)): top_bind.setdefault(s.name, i)
    elif not isinstance(s, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
        for n in ast.walk(s):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store): top_bind.setdefault(n.id, i)

main_pre = [st for st in main.body if st is not boot]
mc, _me, _mp, mthreads = scan(list(nodes_in(main_pre)), main)

res = []
for r in rows:
    if not r["reasons"] or not all(x.startswith("forward:") for x in r["reasons"]):
        continue
    F = r["name"]
    i = r["idx"]
    Fdef = boot.body[i]
    assert isinstance(Fdef, ast.FunctionDef) and Fdef.name == F
    fid = {id(Fdef)}
    fwd = [x.split(":", 1)[1] for x in r["reasons"]]
    j = max(top_bind[n] for n in fwd)
    called, escaped, pump, threads = scan(list(nodes_in(boot.body[i + 1: j + 1])), boot)
    reached = closure(called)
    why = []
    if any(id(x) in fid for x in reached): why.append("called-in-gap")
    # any lookup of the helper's own name in the gap fails, even a deferred registration
    looked = [x for x, _d in escaped]
    for x in reached: looked += [y for y, _d in node_info(x)[1]]
    if any(id(x) in fid for x in looked): why.append("name-read-in-gap")
    bad = [x for x, d in escaped if not d and reaches(x, fid)]
    if bad: why.append("escapes-in-gap")
    if pump or any(node_info(x)[2] for x in reached):
        if any(reaches(x, fid) for x in all_escaped): why.append("event-loop-in-gap")
    started = list(mthreads)
    for x in closure(mc): started += node_info(x)[3]
    bc, _be, _bp, bth = scan(list(nodes_in(boot.body[: j + 1])), boot)
    started += bth
    for x in closure(bc): started += node_info(x)[3]
    if any(reaches(x, fid) for x in started): why.append("running-thread-reaches")
    # handed to something (thread, listener, holder) before the helper is bound
    _c0, e0, _p0, _t0 = scan(list(nodes_in(main_pre)), main)
    _c1, e1, _p1, _t1 = scan(list(nodes_in(boot.body[: j + 1])), boot)
    esc = [x for x, d in e0 + e1 if not d]
    for x in closure(_c0 + _c1):
        esc += [y for y, d in node_info(x)[1] if not d]
    if any(reaches(x, fid) for x in esc): why.append("handed-off-before-bind")
    res.append(dict(r, fwd=fwd, bind_after=j, safe=not why, why=why,
                    bdeps=sorted(set(r["bdeps"]) | set(fwd)), reasons=[]))
    print(("SAFE   " if not why else "block  ") + f"{F}: idx {i} -> after {j} ({j - i} stmts) {why}")
json.dump(res, open(OUT, "w"), indent=1)
print(sum(x["safe"] for x in res), "of", len(res), "safe")

if os.environ.get("P3_ESCAPES"):
    # report non-deferred escapes of anything that reaches a SAFE helper
    esc_sites = []
    for scope in [tree] + all_defs:
        for n in own_nodes(scope):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load):
                p = parent.get(n)
                if isinstance(p, ast.Call) and p.func is n: continue
                if deferred(n): continue
                for t in resolve(n.id, scope):
                    esc_sites.append((t, n, scope))
    for x in res:
        if not x["safe"]: continue
        Fdef = boot.body[x["idx"]]; fid = {id(Fdef)}
        hits = [(n.id, n.lineno, ast.unparse(parent[n])[:70]) for t, n, s in esc_sites if reaches(t, fid)]
        print(x["name"], len(hits))
        for h in hits[:12]: print("    ", h)
