"""
Durable storage for the letter drafts — JSA.LETTER.DRAFTS in Snowflake.

WHY THIS EXISTS. A draft used to live in exactly one place: `out/`, on the
machine the page happened to be running on. `out/` is gitignored and a
Streamlit Cloud reboot rebuilds the container from a fresh clone, so every
reboot destroyed every unsent draft, and the page said nothing about it. On
2026-09-25 that lost a nearly finished Friday letter. Nothing in the app had
ever written a draft anywhere a reboot could not reach.

THE TABLE IS APPEND-ONLY. Every save INSERTs; the current draft is the newest
row for its (issue_date, kind). There is no UPDATE and no DELETE, so no save
can overwrite an earlier version and `history()` can always hand one back.
That is the actual insurance — durability alone would still have let a bad
paste destroy an hour's writing.

IT WRITES BOTH PLACES, EVERY TIME. Snowflake survives the reboot; the file
keeps `python -m letter.build` working when Snowflake is unreachable. Either
one alone has a failure mode the other covers, and a draft is not the place to
be clever about it.

NEWEST WINS ON READ, and that is deliberate rather than "Snowflake is the
source of truth". Hand-editing `out/commentary_<kind>_<date>.md` in an editor
and re-running the build is a supported workflow -- commentary.py's docstring
promises it -- and a rule of "the database always wins" would silently discard
those edits, which is the same class of quiet loss this module exists to stop.
So `restore()` compares the file's mtime against SAVED_AT and keeps whichever
is newer, in UTC on both sides.

A SNOWFLAKE OUTAGE MUST NEVER STOP THE LETTER GOING OUT. Every call here
returns a status string instead of raising, and every Snowflake failure leaves
the on-disk path working exactly as it did before this module existed.

IT IS NOT ONLY THE COMMENTARY. store/backup/restore are generic over
(path, issue, kind) -- they move a text file, and never look inside it. The
prior-Friday settles ride the same table under KIND = "weekbase", because they
are the same kind of loss: typed by hand, kept only in out/, and gone on the
next reboot. Anything else hand-entered that lands in out/ can join them
without a schema change; see WEEK_BASE_KIND for the one rule about KIND.

IT NEVER READS SNOWFLAKE_SCHEMA. CLAUDE.md records that NINE bundled modules
each default that variable to the schema they own, so setting it for one
silently empties the other eight. This module takes no part in that: every
statement names JSA.LETTER.DRAFTS in full, so the session's schema is
irrelevant to it.

(This said "five" until 2026-10-07 and CLAUDE.md said "six"; the real count was
nine. Three numbers for one fact is what happens when a count is copied into a
docstring -- prefer pointing at the section over restating its arithmetic.)
"""
from __future__ import annotations

import importlib.util
import os
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
APPS = REPO / "apps"

TABLE = "JSA.LETTER.DRAFTS"

# KIND shares one namespace with the commentary slugs -- "am", "tuesday",
# "recap", "friday" (config.FORMAT_FOR_DAY). A new kind must not collide with
# one, or two unrelated things overwrite each other's newest row.
#
# Its ISSUE_DATE is the PRIOR FRIDAY, not the letter's date, exactly as
# weekbase_<friday>.json is named: that Friday's settle is a property of the
# week, so Monday's letter and Thursday's letter are the same row and the six
# numbers are typed once.
WEEK_BASE_KIND = "weekbase"

# The settle log, one row per SETTLE DATE rather than one row for the whole
# log. That is not tidiness: the desktop and the deployed container each build
# letters and each record what they fetched, so a single whole-file row would
# mean whichever saved last silently discarded the other's days. Per-date rows
# merge instead of clobbering, and `settle_log.sync()` folds them.
SETTLE_LOG_KIND = "settlelog"

# THE MAILBOX SIGN-IN, AND IT IS THE ONE ROW HERE THAT IS A CREDENTIAL.
#
# letter/mailbox.py caches an MSAL token at letter/data/graph_token.json, and
# letter/data/ is gitignored -- so on Streamlit Cloud every reboot destroys the
# sign-in and the headline panel loses all four digests until someone runs the
# device-code flow again. Seven reboots in two days made that untenable.
#
# WHAT IS ACTUALLY STORED is a serialised MSAL cache containing a delegated
# Mail.Read refresh token for Ross's mailbox. That is a real credential in a
# database row, accepted deliberately on 2026-09-30 as the price of a headline
# panel that survives a restart. Two things follow:
#
#   * This table is append-only BY DESIGN, so refreshed tokens accumulate --
#     every row is a credential that was valid when written. There is no DELETE
#     here and adding one for this would undermine the property the drafts rely
#     on.
#   * The remedy is therefore REVOCATION AT THE IDENTITY PROVIDER, not deletion
#     from the table. Revoking the app's sessions in Entra invalidates every
#     copy at once, wherever it sits. If this ever needs undoing, do it there.
#
# A singleton, so it has no meaningful ISSUE_DATE. 1900-01-01 is a slot, not a
# date, and is deliberately absurd so nobody reads it as one.
GRAPH_TOKEN_KIND = "graphtoken"
SINGLETON_DATE = "1900-01-01"

# Schema, created 2026-09-25 and owned by SYSADMIN rather than living in
# JSA.CME_FEEDER_CATTLE, on purpose: ACCOUNTADMIN owns that schema and SYSADMIN
# was never granted MODIFY on its tables, so a table put there could never be
# altered without an admin. Owning the schema means a column can be added.
DDL = [
    "CREATE SCHEMA IF NOT EXISTS JSA.LETTER",
    f"""CREATE TABLE IF NOT EXISTS {TABLE} (
            ISSUE_DATE DATE          NOT NULL,
            KIND       VARCHAR(32)   NOT NULL,
            BODY       VARCHAR       NOT NULL,
            SAVED_AT   TIMESTAMP_NTZ NOT NULL,
            SAVED_BY   VARCHAR(128)
        )""",
]


def enabled() -> bool:
    """Snowflake is configured. Same flag the rest of the portal uses."""
    return os.getenv("USE_SNOWFLAKE", "").strip().lower() in ("1", "true", "yes", "on")


def _load_db():
    """
    apps/cme_feeder_cattle/snowflake_db.py, under a PRIVATE module name.

    Exactly the trick sources._load_fci_db() uses, for the same reason:
    snowflake_db.py exists six times across two repos and Python caches modules
    by NAME, so a plain `import snowflake_db` inside the Streamlit process gets
    whichever page imported first. "_letter_draft_db" can never join that
    collision. Reusing the file rather than copying its key-pair logic also
    means there is no seventh copy of that to drift.
    """
    path = APPS / "cme_feeder_cattle" / "snowflake_db.py"
    spec = importlib.util.spec_from_file_location("_letter_draft_db", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_letter_draft_db"] = mod
    spec.loader.exec_module(mod)
    return mod


_CONN = None


def _conn():
    """One connection, reused. A login costs a second or more, and autosave
    fires on every blur -- per-call connections made typing feel broken."""
    global _CONN
    if _CONN is None:
        _CONN = _load_db().get_conn()
    return _CONN


def _drop_conn():
    global _CONN
    try:
        if _CONN is not None:
            _CONN.close()
    except Exception:
        pass
    _CONN = None


def _run(fn):
    """Call fn(cursor), reconnecting once. A cached connection outlives the
    session token it was opened with, so the first call after a long idle is
    expected to fail and expected to succeed on the retry."""
    for attempt in (1, 2):
        try:
            cur = _conn().cursor()
            try:
                return fn(cur)
            finally:
                cur.close()
        except Exception:
            _drop_conn()
            if attempt == 2:
                raise
    return None


def _who(source: str) -> str:
    try:
        host = socket.gethostname()
    except Exception:
        host = "?"
    return f"{source}@{host}"[:128]


def _mtime_utc(path: Path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def ensure_table() -> str:
    """Create the schema and table if they are missing. Safe to call every run."""
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    try:
        def go(cur):
            for stmt in DDL:
                cur.execute(stmt)
            return ""
        _run(go)
        return ""
    except Exception as e:
        return f"Could not reach Snowflake: {e}"


def fetch(issue, kind: str):
    """(body, saved_at_utc) for the newest saved version, or (None, None)."""
    if not enabled():
        return None, None
    try:
        def go(cur):
            cur.execute(
                f"SELECT BODY, SAVED_AT FROM {TABLE} "
                "WHERE ISSUE_DATE = %s AND KIND = %s "
                "ORDER BY SAVED_AT DESC LIMIT 1",
                (str(issue), kind),
            )
            return cur.fetchone()
        row = _run(go)
    except Exception:
        return None, None
    if not row:
        return None, None
    saved_at = row[1]
    if saved_at is not None and saved_at.tzinfo is None:
        # The column is TIMESTAMP_NTZ and store() writes UTC into it, so the
        # naive value that comes back IS UTC. Saying so explicitly is what
        # makes the comparison in restore() mean anything.
        saved_at = saved_at.replace(tzinfo=timezone.utc)
    return row[0], saved_at


def history(issue, kind: str, limit: int = 25) -> list:
    """Every saved version, newest first, as [(saved_at_utc, saved_by, body)]."""
    if not enabled():
        return []
    try:
        def go(cur):
            cur.execute(
                f"SELECT SAVED_AT, SAVED_BY, BODY FROM {TABLE} "
                "WHERE ISSUE_DATE = %s AND KIND = %s "
                "ORDER BY SAVED_AT DESC LIMIT %s",
                (str(issue), kind, int(limit)),
            )
            return cur.fetchall() or []
        rows = _run(go)
    except Exception:
        return []
    out = []
    for saved_at, saved_by, body in rows:
        if saved_at is not None and saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)
        out.append((saved_at, saved_by, body))
    return out


def rows_for_kind(kind: str, limit: int = 5000) -> list:
    """
    Every row of one kind across all dates, OLDEST FIRST, as
    [(issue_date, saved_at_utc, body)].

    Oldest first because the only caller folds them in order to get
    last-write-wins, which is settle_log's own documented rule for a repeated
    (ticker, date) -- a letter rebuilt after the close corrects an intraday
    value recorded that morning. Reverse the order and the correction loses.

    The limit is generous rather than tuned: a build writes one or two rows a
    day, so 5,000 is years of them, and the fold is over a few hundred KB at
    worst. It exists so a runaway cannot pull the whole table into a page
    render, not because the real number is near it.

    IT TAKES THE NEWEST ROWS AND THEN REVERSES THEM, rather than selecting
    ASC directly. Those are the same list only while the table is under the
    limit; past it, ASC would return the OLDEST 5,000 and quietly drop every
    recent settle -- the newest data disappearing first, which is the wrong way
    round for a log whose whole job is to answer "what did this settle at last
    Friday".
    """
    if not enabled():
        return []
    try:
        def go(cur):
            cur.execute(
                f"SELECT ISSUE_DATE, SAVED_AT, BODY FROM {TABLE} "
                "WHERE KIND = %s ORDER BY SAVED_AT DESC LIMIT %s",
                (kind, int(limit)),
            )
            return cur.fetchall() or []
        rows = _run(go)
    except Exception:
        return []
    out = []
    for issue_date, saved_at, body in reversed(rows):
        if saved_at is not None and saved_at.tzinfo is None:
            saved_at = saved_at.replace(tzinfo=timezone.utc)
        out.append((issue_date, saved_at, body))
    return out


def store(issue, kind: str, body: str, source: str = "app") -> str:
    """
    Append this version. Returns "" on success, or a message on failure.

    An unchanged body is skipped rather than inserted: autosave fires on every
    blur, and a history of fifty identical rows is a history of nothing.
    """
    if not enabled():
        return "Snowflake is not configured (USE_SNOWFLAKE is unset)."
    if not (body or "").strip():
        return ""
    try:
        current, _ = fetch(issue, kind)
        if current is not None and current == body:
            return ""

        def go(cur):
            cur.execute(
                f"INSERT INTO {TABLE} (ISSUE_DATE, KIND, BODY, SAVED_AT, SAVED_BY) "
                "VALUES (%s, %s, %s, %s, %s)",
                (str(issue), kind, body,
                 datetime.now(timezone.utc).replace(tzinfo=None), _who(source)),
            )
            return ""
        _run(go)
        return ""
    except Exception as e:
        return f"Could not save to Snowflake: {e}"


def backup(path: Path, issue, kind: str, source: str = "app") -> str:
    """Push what is on disk up to Snowflake."""
    try:
        body = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        return f"Could not read {Path(path).name}: {e}"
    return store(issue, kind, body, source)


def restore(path: Path, issue, kind: str, label: str = "Draft",
            has_content=None) -> str:
    """
    Reconcile disk and Snowflake before the file is read. Newest wins.

    Returns a short line for the page to show, or "" when there was nothing to
    do. The three outcomes it reports are the three a person would want to
    know about: the file came back from Snowflake, the local copy was newer
    and was pushed up, or Snowflake could not be reached at all.

    `label` names the thing in that line. It is not decoration: "Draft
    restored" over the prior-Friday settles would read as the commentary
    coming back and send someone looking for writing that never moved.

    `has_content(body) -> bool` OVERRIDES NEWEST-WINS, and exists because
    newest-wins alone lost real writing on 2026-09-28. This function pushes the
    local file up when Snowflake has no row -- and on the page's second rerun
    that file is the template commentary.write_template() has just created. A
    template pushed at 10:00 is NEWER than a real draft written at 09:00, so
    the next reconcile on the machine holding the real draft replaced it with
    empty headings.

    So a blank never beats a non-blank, in either direction, whatever the
    timestamps say. Timestamps only decide between two bodies that both carry
    writing. Left None -- as the week base and the settle log leave it -- every
    body counts as content and the behaviour is unchanged, which is right for
    those: a JSON file of settles has no "empty but well-formed" state that
    means nothing.
    """
    path = Path(path)
    if not enabled():
        return ""

    def _real(body) -> bool:
        if body is None:
            return False
        if has_content is None:
            return True
        try:
            return bool(has_content(body))
        except Exception:
            return True          # never let the predicate decide to lose data

    remote_body, remote_at = fetch(issue, kind)
    local_at = _mtime_utc(path)

    if remote_body is None:
        # Nothing upstream. Push what is here, unless "what is here" is an
        # untouched template -- that is the case that started all this.
        if local_at is not None:
            try:
                local_body = path.read_text(encoding="utf-8")
            except OSError:
                return ""
            if not _real(local_body):
                return ""
            err = backup(path, issue, kind)
            return err or ""
        return ""

    if local_at is None:
        if not _real(remote_body):
            return ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(remote_body, encoding="utf-8")
        return f"{label} restored from Snowflake (saved {remote_at:%b %d %H:%M} UTC)."

    try:
        local_body = path.read_text(encoding="utf-8")
    except OSError:
        local_body = None

    if local_body == remote_body:
        return ""

    local_real, remote_real = _real(local_body), _real(remote_body)

    # A blank loses to writing regardless of which is newer.
    if local_real and not remote_real:
        err = store(issue, kind, local_body or "", "app")
        return err or ""
    if remote_real and not local_real:
        path.write_text(remote_body, encoding="utf-8")
        return f"{label} restored from Snowflake (saved {remote_at:%b %d %H:%M} UTC)."

    if remote_at is not None and local_at is not None and remote_at > local_at:
        path.write_text(remote_body, encoding="utf-8")
        return f"{label} restored from Snowflake (saved {remote_at:%b %d %H:%M} UTC)."

    if not local_real:
        return ""
    err = store(issue, kind, local_body or "", "app")
    return err or ""
