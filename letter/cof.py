"""
The Friday letter's Cattle on Feed block — present on the one Friday a month
that follows a USDA release, absent on the other three.

Everything here is a thin wrapper over apps/cattle_on_feed/cof_recap.py, which
already parses USDA's released report text and is the same code behind the COF
Recap tab. It imports cleanly (no Streamlit at module scope), so it is used
rather than reimplemented.

DETECTION. cof_recap.latest_report() walks back up to thirteen months and
returns the most recent report that exists, so it almost always returns
SOMETHING -- last month's, if this month has not been released. The block
therefore keys off the release DATE, not the mere existence of a report: it is
included only when the release falls inside the issue's own week. Three Fridays
a month that test is false and the section is omitted.

THE ROUNDING DIFFERENCE, which is deliberate and worth knowing before you send.
cof_recap computes On-Feed and the Year-Ago basis from USDA's head counts:
11,163/11,080 = 100.7 and 11,080/11,198 = 98.9. The old Excel sheet the letter
was built from read 100.8 and 99. Placed and Marketed agree to the decimal, so
only those two cells ever differed.

SETTLED TWICE. CLAUDE.md records the computed figure as the one to show
(2026-09-22), and Ross reaffirmed it on 2026-09-23 after seeing both versions
side by side in a rendered letter. So this module prints 100.7 / 98.9, the build
warns each time that those two cells differ from what went out last month, and
the letter agrees with the COF Recap tab rather than with the retired sheet.
Do not "fix" this back.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import date, timedelta
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
_MODULE = REPO / "apps" / "cattle_on_feed" / "cof_recap.py"


def _load():
    """
    Load cof_recap under a private name.

    Same reasoning as sources._load_fci_db: Python caches modules by NAME, and
    the Streamlit process may already hold its own "cof_recap". Naming this copy
    privately keeps the letter and the dashboard from ever handing each other
    the wrong module.
    """
    if "_letter_cof_recap" in sys.modules:
        return sys.modules["_letter_cof_recap"]
    spec = importlib.util.spec_from_file_location("_letter_cof_recap", _MODULE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_letter_cof_recap"] = mod
    spec.loader.exec_module(mod)
    return mod


def released_this_week(release: date, issue: date) -> bool:
    """True when the release falls in the Monday-Sunday week containing issue."""
    monday = issue - timedelta(days=issue.weekday())
    return monday <= release <= monday + timedelta(days=6)


def fetch(issue: date, guesses: dict = None) -> dict:
    """
    The COF block for this issue, or {"include": False} with a reason.

    `guesses` is the analyst pre-report estimate column, {'on_feed': 101.8,
    'placed': 96.8, 'marketed': 96.1}. USDA does not publish it and nothing can
    derive it -- it is typed in, and the table prints a gap without it.
    """
    recap_mod = _load()

    year, month, text = recap_mod.latest_report(issue)
    if not text:
        return {"include": False, "reason": "no Cattle on Feed report found"}

    prior = recap_mod.fetch_report(year - 1, month)
    recap = recap_mod.build_recap(year, month, text, prior_text=prior)

    release = recap.get("release_date")
    if not release:
        return {"include": False, "reason": "report carried no release date"}
    if not released_this_week(release, issue):
        return {"include": False,
                "reason": f"latest release {release.isoformat()} is not in this week",
                "release_date": release.isoformat()}

    # The letter spells the month out -- "September COF Report". cof_recap's own
    # title abbreviates it ("Sep COF Report") for the dashboard's narrower page,
    # so the name is rebuilt here rather than reused.
    month_name = recap_mod.MONTH_NAMES[month - 1]

    return {
        "include": True,
        "title": f"{month_name} COF Report",
        "short_title": recap.get("title"),
        "release_date": release.isoformat(),
        "placement_month": recap.get("placement_month"),
        "actual": recap.get("actual", {}),
        "year_ago": recap.get("year_ago", {}),
        "guesses": guesses or {},
        "us_head": recap.get("us_head", {}),
    }
