"""Pass 11: hoist side-effect-free initialisers out of ``if _PIGEON_EXT:`` in main().

Usage (from ``pigeonSystem``)::

    python3 hoist_main.py pigeon_0_12.py BEFORE_DEF NAME [NAME ...]

Each ``NAME`` must be bound exactly once in ``main()``, by a statement that
sits directly in a top-level ``if _PIGEON_EXT:`` block and whose value is a
literal (``{}`` / ``[None]`` / ...). That statement (plus the comment lines
right above it) moves to ``main()``'s top level, just before ``def BEFORE_DEF``.

Effect: the names now exist on every path, a little earlier. On the non-ext
path nothing reads them (their readers are all inside the same ``if`` or
return early on ``not _PIGEON_EXT``); on the ext path, code that ran before
the old binding would have hit ``NameError`` and now sees the empty value.
Proof printed: the module AST is identical once the moved statements are put
back.
"""
import ast
import copy
import sys

path, before, names = sys.argv[1], sys.argv[2], sys.argv[3:]
src = open(path, encoding="utf-8").read()
lines = src.splitlines(keepends=True)
tree = ast.parse(src)
main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
target = next(s for s in main.body if isinstance(s, ast.FunctionDef) and s.name == before)
ext_blocks = [s for s in main.body if isinstance(s, ast.If) and ast.unparse(s.test) == "_PIGEON_EXT"]


def bound_names(n):
    return {x.id for x in ast.walk(n) if isinstance(x, ast.Name) and isinstance(x.ctx, ast.Store)} | (
        {n.name} if isinstance(n, (ast.FunctionDef, ast.ClassDef)) else set())


moves = []  # (if_block, stmt)
for nm in names:
    hits = [x for x in ast.walk(main) if isinstance(x, ast.Name) and x.id == nm and isinstance(x.ctx, ast.Store)]
    assert len(hits) == 1, (nm, "bound", len(hits), "times")
    assert not any(isinstance(x, ast.Nonlocal) and nm in x.names for x in ast.walk(main)), (nm, "nonlocal")
    owner = [(b, s) for b in ext_blocks for s in b.body if isinstance(s, (ast.Assign, ast.AnnAssign)) and nm in bound_names(s)]
    assert len(owner) == 1, (nm, "not a direct statement of an `if _PIGEON_EXT:` block")
    b, s = owner[0]
    tgt = s.target if isinstance(s, ast.AnnAssign) else (s.targets[0] if len(s.targets) == 1 else None)
    assert isinstance(tgt, ast.Name) and tgt.id == nm, (nm, "must be a single-name binding")
    ast.literal_eval(s.value)  # literal initialiser only
    assert target.lineno < s.lineno, (nm, "already bound before", before)
    moves.append((b, s))

# text edit: cut each statement (with the comment lines right above it), paste before the def
cut = set()
moved_text = []
for _b, s in sorted(moves, key=lambda m: m[1].lineno):
    start = s.lineno
    while lines[start - 2].strip().startswith("#"):
        start -= 1
    for k in range(start, s.end_lineno + 1):
        cut.add(k)
        text = lines[k - 1]
        assert text.startswith("        "), text
        moved_text.append(text[4:])
anchor = target.lineno
while lines[anchor - 2].strip().startswith("#"):
    anchor -= 1
block = ["    # Splash caches, bound up front (were inside ``if _PIGEON_EXT:``) so helpers\n",
         "    # defined before that block can take them as dependencies.\n"] + moved_text + ["\n"]
out = []
for k, text in enumerate(lines, 1):
    if k == anchor:
        out.extend(block)
    if k not in cut:
        out.append(text)
new = "".join(out)

# proof: put the statements back and compare ASTs
t2 = ast.parse(new)
m2 = next(n for n in t2.body if isinstance(n, ast.FunctionDef) and n.name == "main")
moved_nodes = [s for s in m2.body if isinstance(s, (ast.Assign, ast.AnnAssign)) and bound_names(s) & set(names)]
assert len(moved_nodes) == len(names)
for s in moved_nodes:
    m2.body.remove(s)
check = copy.deepcopy(tree)
cm = next(n for n in check.body if isinstance(n, ast.FunctionDef) and n.name == "main")
for b in [x for x in cm.body if isinstance(x, ast.If) and ast.unparse(x.test) == "_PIGEON_EXT"]:
    b.body = [s for s in b.body if not (isinstance(s, (ast.Assign, ast.AnnAssign)) and bound_names(s) & set(names))]
assert ast.dump(t2) == ast.dump(check), "hoist changed more than the moved statements"
open(path, "w", encoding="utf-8").write(new)
print("hoisted", ", ".join(names), "before", before, "- AST otherwise identical")
