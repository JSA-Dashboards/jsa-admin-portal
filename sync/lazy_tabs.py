"""Make a Streamlit app's tabs lazy: only the open tab's body runs.

By default st.tabs() builds EVERY tab on every run, so a dashboard with 13 tabs pays for
all 13 on its first load and on every click. With ``st.tabs(..., on_change="rerun")`` each
tab object has an ``.open`` flag; this tool rewrites

    with tab_x:
        <body>

into

    with tab_x:
        if tab_x.open:
            <body>

(the body re-indented, multi-line strings left untouched) and adds ``on_change="rerun"`` to
the ``st.tabs(...)`` call. Nothing else changes.

    python sync/lazy_tabs.py check <app.py>   # what would change; names that tabs share
    python sync/lazy_tabs.py apply <app.py>   # rewrite in place (idempotent)

A body that SETS a module-level name another tab (or code outside any tab) READS would
raise NameError once that body is skipped, so ``check`` reports every such name and
``apply`` refuses until there are none (or they are listed in --allow).
"""
from __future__ import annotations

import ast
import codecs
import io
import sys
import tokenize


# -- reading ----------------------------------------------------------------
def read(path):
    raw = open(path, "rb").read()
    bom = raw.startswith(codecs.BOM_UTF8)
    text = raw.decode("utf-8-sig")
    crlf = "\r\n" in text
    return text.replace("\r\n", "\n"), bom, crlf


def write(path, text, bom, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    open(path, "wb").write((codecs.BOM_UTF8 if bom else b"") + text.encode("utf-8"))


# -- finding the tabs ---------------------------------------------------------
def tab_variables(tree: ast.Module) -> tuple[set[str], list[ast.Call]]:
    """Names bound to a tab container, and the st.tabs(...) calls that make them.

    Handles `a, b = st.tabs([...])`, `tabs = st.tabs(...)` followed by `x = tabs[i]` /
    `x = d[...]` / `x = d.get(...)` where d is built from the tabs.
    """
    calls, roots = [], set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "tabs" \
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "st":
            calls.append(n)
    parents = {}
    for n in ast.walk(tree):
        for c in ast.iter_child_nodes(n):
            parents[c] = n
    for call in calls:
        p = parents.get(call)
        if isinstance(p, ast.Assign):
            for t in p.targets:
                for nm in ast.walk(t):
                    if isinstance(nm, ast.Name):
                        roots.add(nm.id)
    # propagate: anything derived from a root by subscript, .get(), zip/dict comprehension
    names = set(roots)
    changed = True
    while changed:
        changed = False
        for n in ast.walk(tree):
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name):
                used = {x.id for x in ast.walk(n.value) if isinstance(x, ast.Name)}
                if used & names and n.targets[0].id not in names:
                    names.add(n.targets[0].id)
                    changed = True
    for n in ast.walk(tree):                       # for tab, x in zip(tabs[1:3], ...): with tab:
        if isinstance(n, ast.For):
            used = {x.id for x in ast.walk(n.iter) if isinstance(x, ast.Name)}
            if used & names:
                for nm in ast.walk(n.target):
                    if isinstance(nm, ast.Name):
                        names.add(nm.id)
    return names, calls


def tab_key(expr) -> str:
    return ast.unparse(expr)


def tab_blocks(stmts0, names: set[str]) -> list[ast.With]:
    """Module-level `with tab_x:` / `with tabs[i]:` blocks, including ones nested in module-level
    if/for/try."""
    out = []

    def visit(stmts):
        for s in stmts:
            ce = s.items[0].context_expr if isinstance(s, ast.With) and len(s.items) == 1 else None
            if ce is not None and s.items[0].optional_vars is None and (
                    (isinstance(ce, ast.Name) and ce.id in names)
                    or (isinstance(ce, ast.Subscript) and isinstance(ce.value, ast.Name) and ce.value.id in names)):
                out.append(s)
            elif isinstance(s, (ast.If, ast.For, ast.While, ast.Try)):
                for f in ("body", "orelse", "finalbody"):
                    visit(getattr(s, f, []) or [])
                for h in getattr(s, "handlers", []) or []:
                    visit(h.body)
    visit(stmts0)
    return out


# -- sharing between tabs ----------------------------------------------------
def stored_names(stmts) -> set[str]:
    """Names a block binds in the enclosing (module) scope: not those inside def/lambda/class
    bodies or comprehensions."""
    out = set()

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, n):
            out.add(n.name)            # the def itself binds a name
        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_ClassDef(self, n):
            out.add(n.name)

        def visit_Lambda(self, n):
            pass

        def visit_ListComp(self, n):
            pass
        visit_SetComp = visit_DictComp = visit_GeneratorExp = visit_ListComp

        def visit_Name(self, n):
            if isinstance(n.ctx, (ast.Store, ast.Del)):
                out.add(n.id)

        def visit_Import(self, n):
            for a in n.names:
                out.add((a.asname or a.name).split(".")[0])

        def visit_ImportFrom(self, n):
            for a in n.names:
                out.add(a.asname or a.name)

        def visit_ExceptHandler(self, n):
            if n.name:
                out.add(n.name)
            self.generic_visit(n)
    for s in stmts:
        V().visit(s)
    return out


def _func_params(fn) -> set[str]:
    a = fn.args
    names = {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs}
    if a.vararg:
        names.add(a.vararg.arg)
    if a.kwarg:
        names.add(a.kwarg.arg)
    return names


def free_names(stmts, params=frozenset()) -> set[str]:
    """Names READ in this scope that it does not bind itself, counting what nested functions
    and lambdas read of the enclosing scope. Those are the names the scope expects to find in
    the module."""
    bound = stored_names(stmts) | set(params)
    loads: set[str] = set()

    class V(ast.NodeVisitor):
        def visit_Name(self, n):
            if isinstance(n.ctx, ast.Load):
                loads.add(n.id)

        def _fn(self, n):
            for d in n.decorator_list:
                self.visit(d)
            for d in n.args.defaults + [d for d in n.args.kw_defaults if d is not None]:
                self.visit(d)
            loads.update(free_names(n.body, _func_params(n)))

        visit_FunctionDef = visit_AsyncFunctionDef = _fn

        def visit_Lambda(self, n):
            for d in n.args.defaults + [d for d in n.args.kw_defaults if d is not None]:
                self.visit(d)
            inner = set(_func_params(n))
            loads.update(free_names([ast.Expr(n.body)], inner))

        def _comp(self, n):
            inner = set()
            for g in n.generators:
                for nm in ast.walk(g.target):
                    if isinstance(nm, ast.Name):
                        inner.add(nm.id)
            sub = ast.Module(body=[ast.Expr(x) for x in ([n.elt] if hasattr(n, "elt") else [n.key, n.value])
                                    + [g.iter for g in n.generators] + [c for g in n.generators for c in g.ifs]],
                             type_ignores=[])
            loads.update(free_names(sub.body, inner))

        visit_ListComp = visit_SetComp = visit_GeneratorExp = visit_DictComp = _comp

        def visit_ClassDef(self, n):
            loads.update(free_names(n.body))
    for s in stmts:
        V().visit(s)
    return loads - bound


def shared_names(stmts, blocks) -> dict[str, set[str]]:
    """{name: who reads it} for names a tab body binds that another tab, or code outside every
    tab, reads without binding itself. Reading a name you also bind (a loop counter, a temp)
    is not sharing."""
    skip = {id(n) for b in blocks for n in ast.walk(b)}
    outside = [s for s in stmts if id(s) not in skip]
    module_other: set[str] = set()
    for s in outside:
        module_other |= stored_names([s])
    out: dict[str, set[str]] = {}
    for b in blocks:
        bound = stored_names(b.body) - module_other
        mine = tab_key(b.items[0].context_expr)    # blocks of the SAME tab open together: sharing is fine
        readers = [(f"tab block at line {o.lineno}", free_names(o.body)) for o in blocks
                   if tab_key(o.items[0].context_expr) != mine]
        readers += [(f"module code at line {s.lineno}", free_names([s])) for s in outside]
        for name in bound:
            for where, free in readers:
                if name in free:
                    out.setdefault(name, set()).add(f"bound in block line {b.lineno}, read by {where}")
    return out


def _is_state(node) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "session_state"
            and isinstance(node.value, ast.Name) and node.value.id == "st")


def state_keys(node) -> tuple[set[str], set[str]]:
    """(keys written, keys read) in st.session_state with literal names. A widget's `key="x"`
    counts as a write: that value only exists while the widget is on the page."""
    written, read = set(), set()
    for n in ast.walk(node):
        if isinstance(n, ast.Subscript) and _is_state(n.value) and isinstance(n.slice, ast.Constant) \
                and isinstance(n.slice.value, str):
            (written if isinstance(n.ctx, ast.Store) else read).add(n.slice.value)
        elif isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute) and _is_state(f.value) and n.args \
                    and isinstance(n.args[0], ast.Constant) and isinstance(n.args[0].value, str):
                (read if f.attr in ("get", "pop") else written).add(n.args[0].value)
            for k in n.keywords:
                if k.arg == "key" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str):
                    written.add(k.value.value)
        elif isinstance(n, ast.Compare) and any(_is_state(c) for c in n.comparators) \
                and isinstance(n.left, ast.Constant) and isinstance(n.left.value, str):
            read.add(n.left.value)
    return written, read


def state_crosstalk(stmts, blocks) -> list[str]:
    """Literal session_state keys that one tab sets (or makes with a widget) and another tab, or
    code outside every tab, reads. Not fatal (the reader may default it) but worth a look."""
    skip = {id(n) for b in blocks for n in ast.walk(b)}
    outside = [s for s in stmts if id(s) not in skip]
    out = []
    for b in blocks:
        mine = tab_key(b.items[0].context_expr)
        wrote, _ = state_keys(b)
        for o in blocks:
            if tab_key(o.items[0].context_expr) == mine:
                continue
            _, rd = state_keys(o)
            for k in sorted(wrote & rd):
                out.append(f"STATE {k!r}: set in block line {b.lineno}, read in tab block line {o.lineno}")
        for s in outside:
            _, rd = state_keys(s)
            for k in sorted(wrote & rd):
                out.append(f"STATE {k!r}: set in block line {b.lineno}, read by module code line {s.lineno}")
    return out


# -- rewriting ---------------------------------------------------------------
def string_continuation_lines(text: str) -> set[int]:
    """1-based line numbers that are inside a multi-line string token (not its first line)."""
    inside = set()
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == tokenize.STRING or (tok.type == getattr(tokenize, "FSTRING_MIDDLE", -1)):
            (sr, _), (er, _) = tok.start, tok.end
            if er > sr:
                inside.update(range(sr + 1, er + 1))
    # f-strings (3.12+) are split into FSTRING_START/MIDDLE/END: cover the whole span
    start = None
    for tok in tokenize.generate_tokens(io.StringIO(text).readline):
        if tok.type == getattr(tokenize, "FSTRING_START", -1):
            start = tok.start[0] if start is None else start
            depth_start = tok.start[0]
        if tok.type == getattr(tokenize, "FSTRING_END", -1):
            if tok.end[0] > depth_start:
                inside.update(range(depth_start + 1, tok.end[0] + 1))
    return inside


def scopes(tree):
    """Statement lists to look for tab blocks in: the module and every function body."""
    out = [tree.body]
    for n in ast.walk(tree):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(n.body)
    return out


def rewrite(text: str, allow: set[str]) -> tuple[str, list[str]]:
    tree = ast.parse(text)
    names, calls = tab_variables(tree)
    blocks, notes, clashes = [], [], {}
    for stmts in scopes(tree):
        bl = tab_blocks(stmts, names)
        if not bl:
            continue
        blocks += bl
        notes += state_crosstalk(stmts, bl)             # warnings only
        for k, v in shared_names(stmts, bl).items():
            if k not in allow:
                clashes.setdefault(k, set()).update(v)
    notes.insert(0, f"{len(calls)} st.tabs call(s), {len(blocks)} tab block(s)")
    if clashes:
        for k, v in sorted(clashes.items()):
            notes.append(f"SHARED {k}: " + "; ".join(sorted(v))[:200])
        return text, notes
    lines = text.split("\n")
    skip = string_continuation_lines(text)
    # bottom-up so earlier line numbers stay valid
    for b in sorted(blocks, key=lambda x: -x.lineno):
        tab = tab_key(b.items[0].context_expr)
        first = b.body[0].lineno
        # a docstring-like first line or comment lines between `with` and the body: keep them above
        body_start = b.body[0].lineno
        body_end = b.end_lineno
        if len(b.body) == 1 and isinstance(b.body[0], ast.If) and isinstance(b.body[0].test, ast.Attribute) \
                and ast.unparse(b.body[0].test.value) == tab and b.body[0].test.attr == "open":
            continue                                   # already lazy
        indent = " " * b.body[0].col_offset
        for ln in range(body_start, body_end + 1):
            if ln in skip or not lines[ln - 1].strip():
                continue
            lines[ln - 1] = "    " + lines[ln - 1]
        lines.insert(body_start - 1, f"{indent}if {tab}.open:")
    text2 = "\n".join(lines)
    # on_change="rerun" on each st.tabs(...) call
    tree2 = ast.parse(text2)
    names2, calls2 = tab_variables(tree2)
    lines = text2.split("\n")
    assigned = {id(n.value) for n in ast.walk(tree2) if isinstance(n, ast.Assign)}
    for c in sorted(calls2, key=lambda x: (-x.end_lineno, -x.end_col_offset)):
        if any(k.arg == "on_change" for k in c.keywords):
            continue
        if id(c) not in assigned:      # e.g. zip(st.tabs(..), ..): its tabs are not gated, so no rerun on click
            continue
        ln = c.end_lineno - 1
        col = len(lines[ln].encode("utf-8")[:c.end_col_offset - 1].decode("utf-8"))   # the closing paren (offsets are bytes)
        assert lines[ln][col] == ")", (c.lineno, lines[ln][col])
        lines[ln] = lines[ln][:col] + (', on_change="rerun"' if c.args or c.keywords else 'on_change="rerun"') + lines[ln][col:]
    return "\n".join(lines), notes


def main(argv):
    if len(argv) < 3 or argv[1] not in ("check", "apply"):
        print(__doc__)
        return 2
    cmd, path = argv[1], argv[2]
    allow = set(a.split("=", 1)[1].split(",") for a in argv[3:] if a.startswith("--allow=")) and \
        {x for a in argv[3:] if a.startswith("--allow=") for x in a.split("=", 1)[1].split(",")}
    text, bom, crlf = read(path)
    new, notes = rewrite(text, allow or set())
    for n in notes:
        print(n)
    if new == text:
        print("no change" if not any(n.startswith("SHARED") for n in notes) else "refusing: tabs share names")
        return 1 if any(n.startswith("SHARED") for n in notes) else 0
    ast.parse(new)
    print(f"{new.count(chr(10)) - text.count(chr(10))} lines added; syntax ok")
    if cmd == "apply":
        write(path, new, bom, crlf)
        print("written")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
