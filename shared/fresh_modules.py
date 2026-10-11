"""Reload bundled-app modules whose file changed on disk.

Streamlit re-runs a page's script after a redeploy but keeps every module that
script imported in sys.modules, so a changed sibling module (daily_slaughter.py,
snowflake_db.py ...) keeps serving its old code until the whole process
restarts. Home.py runs first on every rerun, so calling this there drops any
changed app module from sys.modules and the page's own `import` loads the new
file.
"""
import os
import sys

_APPS = os.path.normcase(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "apps"))
_seen: dict[str, float] = {}


def drop_changed_modules() -> None:
    for name, mod in list(sys.modules.items()):
        f = getattr(mod, "__file__", None)
        if not f:
            continue
        f = os.path.normcase(os.path.abspath(f))
        if not f.startswith(_APPS):
            continue
        try:
            mtime = os.stat(f).st_mtime
        except OSError:
            continue
        before = _seen.get(f)
        _seen[f] = mtime
        if before is not None and mtime != before:
            sys.modules.pop(name, None)
