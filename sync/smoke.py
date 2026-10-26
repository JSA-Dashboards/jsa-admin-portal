"""Load every bundled page once, in ONE process (like the portal), and report
code-level failures: ImportError / NameError / SyntaxError / FileNotFoundError ...
Network, Snowflake and secrets errors are reported as WARN (this machine lacks
the deployed secrets), not failures.

    python sync/smoke.py            # all pages
    python sync/smoke.py eia_energy # some pages
"""
import os
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

import socket  # noqa: E402

socket.setdefaulttimeout(float(os.environ.get("SMOKE_SOCKET_TIMEOUT", "4")))  # a blocked network call fails fast

from streamlit.testing.v1 import AppTest  # noqa: E402

HARD = re.compile(r"(ModuleNotFoundError|ImportError|NameError|SyntaxError|FileNotFoundError|"
                  r"IndentationError|UnboundLocalError|AttributeError: module|"
                  r"StreamlitAPIException|DuplicateWidget|StreamlitDuplicate)")


IMPORT_ERRORS = {"ModuleNotFoundError", "ImportError"}


def described(e) -> str:
    """AppTest's exception element holds only the bare message ("No module named 'x'"), so an import that cannot
    resolve never matched HARD above: a page importing a module the portal doesn't ship passed as a warning.
    Put the class name back for those (other messages stay as they were, e.g. a data file fetched at runtime)."""
    kind = getattr(getattr(e, "proto", None), "type", "")
    return f"{kind}: {e.value}" if kind in IMPORT_ERRORS else e.value


def pages(names):
    apps = ROOT / "apps"
    allp = sorted(p.name for p in apps.iterdir() if (p / "app.py").exists())
    return names or allp


def main():
    names = pages(sys.argv[1:])
    bad = 0
    for n in names:
        f = ROOT / "apps" / n / "app.py"
        t0 = time.time()
        try:
            at = AppTest.from_file(str(f), default_timeout=int(os.environ.get("SMOKE_TIMEOUT", "25"))).run()
            excs = [described(e) for e in at.exception]
            errs = [e.value for e in at.error]
        except Exception as e:  # the script blew up before AppTest could capture it
            excs, errs = [f"{type(e).__name__}: {e}"], []
            if os.environ.get("SMOKE_TRACE"):
                traceback.print_exc()
        hard = [x for x in excs + errs if HARD.search(str(x))]
        soft = [x for x in excs + errs if x not in hard]
        status = "FAIL" if hard else ("warn" if soft else "ok  ")
        bad += bool(hard)
        print(f"{status}  {n:22} {time.time() - t0:5.1f}s")
        for x in hard:
            print("       !!", str(x).strip().splitlines()[0][:150])
        for x in soft[:2]:
            print("       ..", str(x).strip().splitlines()[0][:150])
    print("smoke:", "FAILED" if bad else "ok", f"({bad} page(s) with code-level errors)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
