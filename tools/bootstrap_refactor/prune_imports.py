"""Drop pigeon_0_12.py's unused top-level imports (pyflakes' list).

Usage (from ``pigeonSystem``)::

    python3 -m pyflakes pigeon_0_12.py > /tmp/pf.txt; python3 prune_imports.py pigeon_0_12.py /tmp/pf.txt

Only unconditional top-level ``import`` / ``from ... import`` statements are
edited (optional imports inside ``try`` keep their fallbacks). ``tkinter.*``
submodule imports always stay: importing them is what makes ``tk.messagebox``
and friends available to other modules.
"""
import ast
import re
import sys

path, pf = sys.argv[1], sys.argv[2]
unused = {}
for line in open(pf):
    m = re.match(r".*:(\d+):\d+: '([^']+)' imported but unused", line)
    if m:
        unused.setdefault(int(m.group(1)), set()).add(m.group(2))
src = open(path, encoding="utf-8").read()
L = src.splitlines(keepends=True)
edits = []
for s in ast.parse(src).body:
    if not isinstance(s, (ast.Import, ast.ImportFrom)) or s.lineno not in unused:
        continue
    bad = unused[s.lineno]

    def full(a):
        base = f"{s.module}.{a.name}" if isinstance(s, ast.ImportFrom) else a.name
        return base + (f" as {a.asname}" if a.asname else "")

    drop = [a for a in s.names if full(a) in bad and not full(a).startswith("tkinter")]
    if not drop:
        continue
    keep = [a for a in s.names if a not in drop]
    names = [a.name + (f" as {a.asname}" if a.asname else "") for a in keep]
    if not keep:
        new = ""
    elif isinstance(s, ast.ImportFrom):
        one = f"from {s.module} import " + ", ".join(names) + "\n"
        new = one if len(one) <= 100 else f"from {s.module} import (\n" + "".join(f"    {n},\n" for n in names) + ")\n"
    else:
        new = "import " + ", ".join(names) + "\n"
    edits.append((s.lineno, s.end_lineno, new, [full(a) for a in drop]))
for a, b, new, d in sorted(edits, reverse=True):
    L[a - 1:b] = [new] if new else []
    print("drop", ", ".join(d))
open(path, "w", encoding="utf-8").write("".join(L))
