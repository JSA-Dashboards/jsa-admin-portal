"""Keep apps/<name>/ in step with the standalone repo that owns each dashboard.

The standalone repo is the source of truth. apps/<name>/ is a generated mirror:
this tool copies the repo's files and applies a small, idempotent patch set so
the same code runs as a page inside the portal's one shared process.

    python sync/sync_apps.py status                 # drift for every app
    python sync/sync_apps.py plan eia_energy        # what apply would change
    python sync/sync_apps.py diff eia_energy        # the actual diff
    python sync/sync_apps.py apply eia_energy ...   # write it (omit names = all)
    python sync/sync_apps.py check                  # collision + path lint, no network

Patches (see PATCHES below) never touch upstream logic: they remove
st.set_page_config (Home.py makes the one call allowed per run) and add a
sys.path shim so sibling imports resolve to the app's own folder.
"""
from __future__ import annotations

import argparse
import ast
import codecs
import difflib
import fnmatch
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APPS = ROOT / "apps"
CACHE = ROOT / "sync" / ".cache"
CONFIG = json.loads((ROOT / "sync" / "apps.json").read_text(encoding="utf-8"))
MANIFEST = ".sync.json"
MARK = "portal-sync"


# ── fetching ────────────────────────────────────────────────────────────────
def _git(*args, cwd=None):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args[:3])}: {r.stderr.strip()[:300]}")
    return r.stdout.strip()


def _url(repo: str) -> str:
    tok = os.environ.get("SYNC_TOKEN")
    return (f"https://x-access-token:{tok}@github.com/{repo}.git" if tok
            else f"https://github.com/{repo}.git")


def fetch(spec: dict) -> tuple[Path, str]:
    """Shallow-clone (or refresh) the source repo; return (checkout, commit)."""
    dest = CACHE / spec["repo"].replace("/", "__")
    branch = spec["branch"]
    if (dest / ".git").exists():
        _git("fetch", "--depth", "1", "origin", branch, cwd=dest)
        _git("checkout", "-q", "--force", "FETCH_HEAD", cwd=dest)
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        _git("clone", "-q", "--depth", "1", "--branch", branch, _url(spec["repo"]), str(dest))
    return dest, _git("rev-parse", "HEAD", cwd=dest)


# ── patches ─────────────────────────────────────────────────────────────────
def patch_set_page_config(src: str) -> str:
    """Replace each st.set_page_config(...) statement with `pass`."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    lines = src.splitlines(keepends=True)
    spans = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call):
            f = n.value.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
            if name == "set_page_config":
                spans.append((n.lineno, n.end_lineno, n.col_offset))
    for a, b, col in sorted(spans, reverse=True):
        eol = "\r\n" if lines[a - 1].endswith("\r\n") else "\n"
        lines[a - 1:b] = [" " * col + f"pass  # {MARK}: st.set_page_config removed "
                          f"(Home.py makes the one call allowed per run){eol}"]
    return "".join(lines)


def patch_sys_path(src: str) -> str:
    """Make `import sibling_module` resolve to this app's own folder."""
    head = "\n".join(src.splitlines()[:80])
    if "sys.path.insert(0" in head and "__file__" in head:
        return src
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    after = 0
    for i, n in enumerate(tree.body):
        is_doc = (i == 0 and isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant)
                  and isinstance(n.value.value, str))
        is_future = isinstance(n, ast.ImportFrom) and n.module == "__future__"
        if is_doc or is_future:
            after = n.end_lineno
        else:
            break
    eol = "\r\n" if "\r\n" in src else "\n"
    shim = (f"import sys as _sys  # {MARK}: sibling imports resolve to this folder{eol}"
            f"from pathlib import Path as _Path  # {MARK}{eol}"
            f"_sys.path.insert(0, str(_Path(__file__).parent))  # {MARK}{eol}")
    lines = src.splitlines(keepends=True)
    lines[after:after] = [shim]
    return "".join(lines)


FILE_READERS = {"open", "read_csv", "read_excel", "read_parquet", "read_json", "read_feather",
                "read_pickle", "read_table", "load_workbook", "ExcelFile", "connect"}


def relative_literal(node) -> bool:
    """A call's first argument is a bare relative file name like "data/x.csv"."""
    if not (isinstance(node, ast.Call) and node.args and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)):
        return False
    f = node.func
    name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
    v = node.args[0].value
    return (name in FILE_READERS and "." in os.path.basename(v) and ":" not in v and "{" not in v
            and not v.startswith(("/", "~", chr(92))))


def patch_relative_paths(src: str) -> str:
    """cwd is the portal's repo root, not the app's folder: anchor literal relative
    file names to this file's directory (same result when run standalone)."""
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return src
    lines = src.splitlines(keepends=True)
    edits = []
    for n in ast.walk(tree):
        if relative_literal(n):
            a = n.args[0]
            if a.lineno == a.end_lineno:
                edits.append((a.lineno - 1, a.col_offset, a.end_col_offset, a.value))
    for ln, c0, c1, val in sorted(edits, key=lambda e: (-e[0], -e[1])):  # offsets are UTF-8 bytes
        b = lines[ln].encode("utf-8")
        new = ('__import__("os").path.join(__import__("os").path.dirname(__file__), '
               + repr(val) + ")").encode("utf-8")
        lines[ln] = (b[:c0] + new + b[c1:]).decode("utf-8")
    return "".join(lines)


def apply_patches(rel: str, src: str, entry: str) -> str:
    if not rel.endswith(".py"):
        return src
    src = patch_set_page_config(src)
    src = patch_relative_paths(src)
    if rel == entry:
        src = patch_sys_path(src)
    return src


# ── planning ────────────────────────────────────────────────────────────────
def excluded(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    return any(fnmatch.fnmatch(p, pat) for pat in patterns for p in parts)


def prefix_siblings(tree: dict[str, bytes], prefix: str, entry: str) -> dict[str, bytes]:
    """Rename every top-level sibling module `x.py` to `<prefix>x.py` and rewrite
    the imports that name it, so two apps that ship the same module name (a
    `snowflake_db.py`, a `massive_api.py`) can't hand each other the copy that
    happened to load first in the portal's one shared sys.modules."""
    mods = {k[:-3] for k in tree if k.endswith(".py") and "/" not in k and k != entry}
    if not mods:
        return tree

    def rewrite(text: str) -> str:
        try:
            t = ast.parse(text)
        except SyntaxError:
            return text
        lines = text.splitlines(keepends=True)
        edits = []
        for n in ast.walk(t):
            if isinstance(n, ast.Import) and any(a.name.split(".")[0] in mods for a in n.names):
                for a in n.names:
                    if a.name.split(".")[0] in mods:
                        a.asname = a.asname or a.name
                        a.name = prefix + a.name
                edits.append(n)
            elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module and n.module.split(".")[0] in mods:
                n.module = prefix + n.module
                edits.append(n)
        for n in sorted(edits, key=lambda x: -x.lineno):
            indent = " " * n.col_offset
            eol = "\r\n" if lines[n.lineno - 1].endswith("\r\n") else "\n"
            lines[n.lineno - 1:n.end_lineno] = [indent + ast.unparse(n) + eol]
        return "".join(lines)

    out = {}
    for rel, data in tree.items():
        if rel.endswith(".py"):
            bom = data.startswith(codecs.BOM_UTF8)
            data = rewrite(data.decode("utf-8-sig")).encode("utf-8")
            if bom:
                data = codecs.BOM_UTF8 + data
        out[prefix + rel if rel[:-3] in mods and rel.endswith(".py") and "/" not in rel else rel] = data
    return out


def scan_keys(tree: dict[str, bytes]) -> set[str]:
    """Secret / env names an app reads, e.g. st.secrets.get("X"), os.environ["X"], _secret("X")."""
    keys = set()
    for rel, data in tree.items():
        if not rel.endswith(".py"):
            continue
        try:
            t = ast.parse(data.decode("utf-8-sig", "replace"))
        except SyntaxError:
            continue
        for n in ast.walk(t):
            if isinstance(n, ast.Call) and n.args and isinstance(n.args[0], ast.Constant) \
                    and isinstance(n.args[0].value, str):
                f = n.func
                fn = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", "")
                if fn in ("get", "getenv", "_secret", "_sf_secret", "_get_secret", "secret") \
                        and n.args[0].value.isupper() and len(n.args[0].value) > 4 and "_" in n.args[0].value:
                    keys.add(n.args[0].value)
            elif isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                    and isinstance(n.slice.value, str) and n.slice.value.isupper() and "_" in n.slice.value:
                keys.add(n.slice.value)
    return keys


def desired_tree(name: str, spec: dict) -> tuple[dict[str, bytes], str]:
    src_root, commit = fetch(spec)
    if spec.get("subdir"):
        src_root = src_root / spec["subdir"]
    excl = CONFIG["defaults"]["exclude"] + spec.get("exclude", [])
    entry = spec["entry"]
    out: dict[str, bytes] = {}
    for p in sorted(src_root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src_root).as_posix()
        if excluded(rel, excl):
            continue
        data = p.read_bytes()
        if rel.endswith(".py"):
            bom = data.startswith(codecs.BOM_UTF8)
            text = data.decode("utf-8-sig", errors="replace")
            data = apply_patches(rel, text, entry).encode("utf-8")
            if bom:
                data = codecs.BOM_UTF8 + data
        out[rel] = data
    if entry not in out:
        raise RuntimeError(f"{name}: entry {entry} not found in {spec['repo']}")
    if spec.get("prefix_modules"):
        out = prefix_siblings(out, spec["prefix_modules"], entry)
    return out, commit


def current_tree(name: str) -> dict[str, bytes]:
    d = APPS / name
    out = {}
    if d.exists():
        for p in d.rglob("*"):
            if p.is_file() and "__pycache__" not in p.parts and p.name != MANIFEST:
                out[p.relative_to(d).as_posix()] = p.read_bytes()
    return out


def norm(b: bytes) -> bytes:
    return b.replace(b"\r\n", b"\n")


def compare(want: dict[str, bytes], have: dict[str, bytes]) -> dict[str, list[str]]:
    res = {"added": [], "changed": [], "same": [], "portal_only": []}
    for k, v in want.items():
        if k not in have:
            res["added"].append(k)
        elif norm(have[k]) != norm(v):
            res["changed"].append(k)
        else:
            res["same"].append(k)
    res["portal_only"] = sorted(set(have) - set(want))
    return res


def specs(names: list[str]) -> dict[str, dict]:
    out = {}
    for n in (names or CONFIG["apps"]):
        if n not in CONFIG["apps"]:
            sys.exit(f"unknown app: {n}")
        s = {**CONFIG["defaults"], **CONFIG["apps"][n]}
        if names or s.get("sync", True):
            out[n] = s
    return out


def root_files() -> list[dict]:
    """Shared modules that live at a source repo's root (e.g. livestock-portal's wasde.py)
    and are reached through sys.path[repo root]; in the portal that root is the repo root."""
    return [{"branch": "master", **r} for r in CONFIG.get("root_files", [])]


def sync_root_files(write: bool) -> int:
    failed = 0
    for r in root_files():
        try:
            src, commit = fetch(r)
            data = (src / r["path"]).read_bytes()
        except Exception as e:
            failed += 1
            print(f"FAILED  root file {r['path']}: {str(e)[:120]}")
            continue
        dest = ROOT / r.get("dest", r["path"])
        same = dest.exists() and norm(dest.read_bytes()) == norm(data)
        if write and not same:
            dest.write_bytes(data)
        print(f"{'synced' if write else ('same  ' if same else 'differs')} root file {r['path']} @ {commit[:8]}")
    return failed


# ── commands ────────────────────────────────────────────────────────────────
def cmd_status(names):
    print(f"{'app':22}{'added':>6}{'changed':>9}{'portal-only':>13}  note")
    for n, s in specs(names).items():
        try:
            want, commit = desired_tree(n, s)
        except Exception as e:  # private repo without token, etc.
            print(f"{n:22}{'-':>6}{'-':>9}{'-':>13}  SKIPPED: {str(e)[:70]}")
            continue
        c = compare(want, current_tree(n))
        print(f"{n:22}{len(c['added']):>6}{len(c['changed']):>9}{len(c['portal_only']):>13}  {commit[:8]}")
    for n, s in CONFIG["apps"].items():
        if s.get("sync") is False:
            print(f"{n:22}{'':>28}  not synced: {s['why']}")
    if not names:
        sync_root_files(write=False)


def cmd_plan(names):
    for n, s in specs(names).items():
        want, commit = desired_tree(n, s)
        c = compare(want, current_tree(n))
        print(f"== {n}  ({s['repo']} @ {commit[:8]})")
        for k in ("added", "changed", "portal_only"):
            for f in c[k]:
                print(f"   {k:11} {f}")
        new_keys = scan_keys(want) - scan_keys(current_tree(n))
        if new_keys:
            print(f"   NEW SECRETS/ENV the portal's deployed Secrets must carry: {', '.join(sorted(new_keys))}")
        if not any(c[k] for k in ("added", "changed", "portal_only")):
            print("   up to date")


def cmd_diff(names):
    for n, s in specs(names).items():
        want, _ = desired_tree(n, s)
        have = current_tree(n)
        c = compare(want, have)
        for f in c["changed"]:
            a = norm(have[f]).decode("utf-8", "replace").splitlines()
            b = norm(want[f]).decode("utf-8", "replace").splitlines()
            for line in difflib.unified_diff(a, b, f"portal/{n}/{f}", f"source/{n}/{f}", lineterm="", n=2):
                print(line)
        for f in c["added"]:
            print(f"+++ new file {n}/{f}")


def cmd_apply(names):
    failed = 0
    for n, s in specs(names).items():
        if s.get("private") and not os.environ.get("SYNC_TOKEN") and os.environ.get("CI"):
            print(f"skipped {n}: private repo and no SYNC_TOKEN in CI")
            continue
        try:
            want, commit = desired_tree(n, s)
        except Exception as e:
            failed += 1
            print(f"FAILED  {n}: {str(e)[:160]}")
            continue
        d = APPS / n
        old_manifest = {}
        if (d / MANIFEST).exists():
            old_manifest = json.loads((d / MANIFEST).read_text())["files"]
        d.mkdir(parents=True, exist_ok=True)
        for rel, data in want.items():
            p = d / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            if not p.exists() or norm(p.read_bytes()) != norm(data):
                p.write_bytes(data)
        for rel in set(old_manifest) - set(want):      # deleted upstream since last sync
            (d / rel).unlink(missing_ok=True)
        for rel in set(current_tree(n)) - set(want):   # stray files an earlier hand-copy left behind
            if excluded(rel, CONFIG["defaults"]["exclude"] + s.get("exclude", [])) or rel.endswith(".pyc"):
                (d / rel).unlink(missing_ok=True)
        (d / MANIFEST).write_text(json.dumps({
            "repo": s["repo"], "subdir": s.get("subdir"), "branch": s["branch"], "commit": commit,
            "note": "GENERATED mirror - edit the source repo, then run sync/sync_apps.py apply",
            "files": {k: hashlib.sha256(v).hexdigest() for k, v in want.items()},
        }, indent=1))
        print(f"synced {n} @ {commit[:8]} ({len(want)} files)")
    if not names:
        failed += sync_root_files(write=True)
    return failed


# ── static checks (no network) ──────────────────────────────────────────────
def cmd_check(_names):
    bad = 0
    # 1. sibling modules sharing a name across apps but differing in content
    seen: dict[str, dict[str, str]] = {}
    for d in sorted(p for p in APPS.iterdir() if p.is_dir()):
        for p in d.glob("*.py"):
            if p.name != "app.py":
                seen.setdefault(p.stem, {})[d.name] = hashlib.sha256(norm(p.read_bytes())).hexdigest()
        for p in d.iterdir():
            if p.is_dir() and (p / "__init__.py").exists():
                seen.setdefault(p.name, {})[d.name] = "package"
    for mod, owners in seen.items():
        if len(owners) > 1 and len(set(owners.values())) > 1:
            bad += 1
            print(f"COLLISION  module '{mod}' differs between: {', '.join(owners)}")
    for r in root_files():
        mod = Path(r.get("dest", r["path"])).stem
        if mod in seen:
            bad += 1
            print(f"COLLISION  root module '{mod}' also exists inside apps: {list(seen[mod])}")
    # 2. a sibling module that shadows a portal-level package
    for top in ("shared", "sync"):
        if top in seen:
            bad += 1
            print(f"SHADOW     '{top}' collides with the portal's own package: {list(seen[top])}")
    # 3. cwd-relative file paths (the portal's cwd is the repo root, not the app folder)
    for d in sorted(p for p in APPS.iterdir() if p.is_dir()):
        for p in d.rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8-sig", errors="replace"))
            except SyntaxError as e:
                bad += 1
                print(f"SYNTAX     {p.relative_to(ROOT)}: {e}")
                continue
            for n in ast.walk(tree):
                if relative_literal(n):
                    print(f"RELPATH    {p.relative_to(ROOT)}:{n.lineno}  {n.args[0].value!r} depends on the working directory")
    print("check:", "FAILED" if bad else "ok", f"({bad} blocking issue(s))")
    return bad


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["status", "plan", "diff", "apply", "check"])
    ap.add_argument("apps", nargs="*")
    a = ap.parse_args()
    fn = {"status": cmd_status, "plan": cmd_plan, "diff": cmd_diff, "apply": cmd_apply, "check": cmd_check}[a.cmd]
    sys.exit(1 if fn(a.apps) else 0)


if __name__ == "__main__":
    main()
