"""
Our own record of the front-month settles, written every time a letter is built.

WHY THIS EXISTS. The week-over-week change needs one number per contract: the
prior Friday's settle. That normally comes from Massive's /aggs history -- and
that history has had NO BARS AT ALL for 2026-09-14..09-18 for over a week. The
live /snapshot endpoint the Seasonal dashboard uses was fine throughout; only
the historical series has the hole. So the durable fix is not a different API,
it is to stop depending on someone else's history for a number we see every day
anyway.

Every build appends what it just fetched. After one Friday's letter is built,
the following Tuesday's weekly change comes out of this file and never touches
/aggs again.

NOT IN out/. That directory is scratch and gets cleared; losing this file would
silently take the weekly change with it. It lives beside the code, gitignored --
it is market data, not source.

Last write wins for a given (ticker, date), so a letter rebuilt after the close
corrects an intraday value recorded earlier the same day.

AND IT IS MIRRORED TO SNOWFLAKE, as of 2026-09-28. Gitignored beside the code
turned out to be no safer than out/: a Streamlit Cloud reboot rebuilds the
container from a fresh clone, so letter/data/ arrives empty and the deployed
app's log has always been empty. Every Friday there, the weekly change fell
back to Massive's gapped history and printed [[?]] -- the very dependency this
file exists to remove.

THE MERGE IS THE WHOLE DESIGN, and it is why this does not simply reuse
draft_store.restore() the way the commentary and the week base do. Those are
one authored document with one writer at a time, so newest-wins is right. This
is an ACCUMULATING LOG WITH TWO WRITERS: the desktop and the container each
build letters and each record what they fetched. Newest-wins on the whole file
would mean whichever saved last threw away the other's days. So it rides
JSA.LETTER.DRAFTS as one row PER SETTLE DATE under KIND = "settlelog", and
sync() folds those rows oldest-first into a union. Nothing is discarded, and a
repeated (ticker, date) still resolves to the last write, unchanged.

A row is a complete {ticker: settle} for its date, but the fold is per ticker
rather than per row, so a build that recorded only one product cannot drop the
other's price for that day.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from . import draft_store

LOG_PATH = Path(__file__).resolve().parent / "data" / "settle_log.json"


def load(path: Path = None) -> dict:
    """{ticker: {iso_date: settle}}, or {} if nothing has been recorded yet."""
    p = Path(path or LOG_PATH)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _by_date(log: dict) -> dict:
    """{ticker: {date: settle}} -> {date: {ticker: settle}}, the row shape."""
    out = {}
    for ticker, days in (log or {}).items():
        for when, settle in (days or {}).items():
            out.setdefault(when, {})[ticker] = settle
    return out


def _write(p: Path, log: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    # sort_keys so the text is stable: the row body is compared as a string
    # before it is appended, and dict order alone would save a "new version"
    # that differs only in line order. Same lesson as save_week_base.
    p.write_text(json.dumps(log, indent=2, sort_keys=True), encoding="utf-8")


def _push(log: dict, dates, source: str = "app") -> str:
    """Write one row per named date. Returns "" or the first failure."""
    by_date = _by_date(log)
    err = ""
    for when in sorted(set(dates)):
        day = by_date.get(when)
        if not day:
            continue
        body = json.dumps(day, indent=2, sort_keys=True)
        err = draft_store.store(when, draft_store.SETTLE_LOG_KIND, body, source) or err
    return err


def remote_load() -> dict:
    """
    The log as Snowflake has it: every row folded oldest-first into
    {ticker: {date: settle}}.

    Folding rather than taking the newest row per date is deliberate -- see the
    module docstring. Per ticker, the last write wins; per date, nothing is
    dropped because one build happened to record only one product.
    """
    log = {}
    for issue_date, _saved_at, body in draft_store.rows_for_kind(draft_store.SETTLE_LOG_KIND):
        when = str(issue_date)[:10]
        try:
            day = json.loads(body)
        except ValueError:
            continue
        if not isinstance(day, dict):
            continue
        for ticker, settle in day.items():
            try:
                log.setdefault(ticker, {})[when] = float(settle)
            except (TypeError, ValueError):
                continue
    return log


def sync(path: Path = None, source: str = "app") -> str:
    """
    Merge Snowflake's rows into the local file and push anything only local.

    Returns a short line worth printing, or "" when there was nothing to do.
    A failure is reported, never raised: an unreachable Snowflake has to leave
    the letter building exactly as it did before this existed.
    """
    p = Path(path or LOG_PATH)
    if not draft_store.enabled():
        return ""

    local = load(p)
    remote = remote_load()

    # REMOTE WINS A TIE, because this machine's own writes went there too --
    # so anything the two disagree on is either the other machine's newer
    # record or a correction that already reached the table. A local-only
    # entry is one recorded while Snowflake was unreachable, and it is pushed.
    merged = {t: dict(d) for t, d in local.items()}
    gained = 0
    for ticker, days in remote.items():
        for when, settle in days.items():
            if merged.setdefault(ticker, {}).get(when) != settle:
                gained += 1
            merged[ticker][when] = settle

    only_local = {when for t, d in local.items() for when in d
                  if remote.get(t, {}).get(when) != d[when]}

    if merged != local:
        _write(p, merged)

    err = _push(merged, only_local, source) if only_local else ""
    if err:
        return err
    if gained:
        n_days = len({w for d in remote.values() for w in d})
        return f"Settle log: {gained} settle(s) restored from Snowflake, {n_days} day(s) on record."
    if only_local:
        return f"Settle log: {len(only_local)} day(s) pushed to Snowflake."
    return ""


def record(ctx: dict, path: Path = None, source: str = "app") -> int:
    """
    Append the settles this build fetched. Returns how many were written.

    Records against each contract's OWN settle_date, not the issue date -- on a
    Monday holiday, or when the newest bar lags, those differ and filing the
    price under the wrong day is exactly the error this is meant to prevent.

    Writes the file AND the matching Snowflake rows, so the record survives the
    container it was made in. A Snowflake failure is swallowed here rather than
    reported: this is called mid-build, the file write has already succeeded,
    and sync() will push the day on the next run.

    A RECOVERED CLOSE IS NOT RECORDED. When Massive's daily series has a hole,
    sources.fetch_futures fills it from the hourly bars and marks the contract
    settle_source "hourly close" -- a last trade, not a settlement, and on
    2026-09-11 the two differed by as much as 0.30. This file is the authority
    for the prior-Friday base once a value lands in it, so writing a close here
    would make next Friday's week-over-week change a few ticks wrong with
    nothing marking it: precisely the quiet error the whole module exists to
    stop. The snapshot's official settlement IS a settlement and is kept.
    """
    p = Path(path or LOG_PATH)
    log = load(p)

    written = 0
    touched = set()
    for key in ("live_cattle", "feeder_cattle"):
        for c in ctx.get(key) or []:
            ticker, settle = c.get("ticker"), c.get("settle")
            when = str(c.get("settle_date") or "")[:10]
            if not ticker or settle is None or not when:
                continue
            if c.get("settle_source") == "hourly close":
                continue
            log.setdefault(ticker, {})[when] = float(settle)
            touched.add(when)
            written += 1

    if written:
        _write(p, log)
        try:
            _push(log, touched, source)
        except Exception:
            pass
    return written


def bank(values: dict, when, path: Path = None, source: str = "manual") -> int:
    """
    Record settles typed in by hand. Returns how many were written.

    WHY A LETTER NEEDS THIS. On 2026-09-28 Massive had no settlement for
    Friday 09-25 at any resolution and no prospect of one: /trades carries zero
    ticks for the whole of 09-14..09-24, so the hole is in the raw trade table
    and nothing can be aggregated out of it. The brief could recover the
    session from the hourly bars but only as a LAST TRADE -- 335.00 on the Oct
    feeder, which settled 334.925 -- and the letter quotes settlements.

    Where the feed cannot supply a number and no arithmetic can invent one, the
    letter's standing answer is to put a human on it, exactly as it does for
    the prior-Friday week base and for headlines. This is that entry point.

    IT WRITES WHERE fetch_futures ALREADY LOOKS, which is the point of putting
    it here rather than in a file of its own. The settle log is a recovery tier
    ranked above an hourly close, so a banked value is picked up on the next
    fetch with no new plumbing -- and because both ends of the move are then
    settlements rather than a close against a settle, the daily change comes
    back too instead of staying marked.

    IT CANNOT OVERWRITE REAL DATA, and that is deliberate rather than an
    oversight. fetch_futures fills only sessions the settlement history lacks,
    so a banked figure loses to a real bar the moment Massive serves one. That
    is the same rule the week base follows, and for the same reason: inviting a
    typed number to beat a fetched one is the mistake the [[?]] marking exists
    to prevent.

    The source lands in SAVED_BY on the Snowflake row, so a hand-entered settle
    is distinguishable from a fetched one after the fact without changing the
    row format, which is a plain {ticker: settle} for its date.
    """
    p = Path(path or LOG_PATH)
    log = load(p)
    iso = when.isoformat() if hasattr(when, "isoformat") else str(when)[:10]

    written = 0
    for ticker, settle in (values or {}).items():
        if settle is None or not str(ticker).strip():
            continue
        try:
            log.setdefault(str(ticker).strip().upper(), {})[iso] = float(settle)
        except (TypeError, ValueError):
            continue
        written += 1

    if written:
        _write(p, log)
        # Swallowed like record()'s: the file write has already succeeded, and
        # sync() pushes the day on the next run if Snowflake is unreachable.
        try:
            _push(log, [iso], source)
        except Exception:
            pass
    return written


def settles_on(when: date, path: Path = None) -> dict:
    """{ticker: settle} for one date, from whatever has been recorded."""
    iso = when.isoformat()
    return {t: v[iso] for t, v in load(path).items() if iso in v}


def coverage(path: Path = None) -> tuple:
    """(number of tickers, earliest date, latest date) -- for reporting."""
    log = load(path)
    days = sorted({d for v in log.values() for d in v})
    return (len(log), days[0] if days else None, days[-1] if days else None)
