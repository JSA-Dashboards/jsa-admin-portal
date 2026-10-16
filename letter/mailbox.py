"""
Beef market headlines read out of Ross's own inbox.

Four subscription digests: Meatingplace, eMeat, Global AgriTrends and
Sterling. Adding a fifth is one line in DIGESTS.

WHY THE MAILBOX AND NOT THE SITE. These are paid subscriptions. Fetching their
web pages with a script is the thing their terms are most likely to prohibit,
and it needs a stored password. The digest email does not: it was sent TO Ross
because he subscribed, it is sitting in his mailbox, and reading it is the same
act as opening it. No request ever reaches their servers.

NO PASSWORD PASSES THROUGH THIS CODE. MSAL's device-code flow prints a short
code, Ross signs in through a normal browser, and Graph returns a token that
lives in a local cache file. Same flow basis-tracker/email_client.py already
uses for the ADM and Mendota bid emails.

WHAT IT DOES WITH THEM. Nothing but offer them. The digests feed the candidate
panel on the authoring page, which is a pick list; the letter still prints only
what Ross typed. Reprinting a trade publication's headline text in a PDF sent to
paying clients is a different act from reading it, and this module deliberately
cannot do the second one.
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import draft_store

GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Mail.Read"]

# Cached beside the code, not in out/ -- that directory gets cleared, and losing
# the token means signing in again for no reason. Gitignored with letter/data/.
TOKEN_CACHE = Path(__file__).resolve().parent / "data" / "graph_token.json"

# Add a digest by adding a line. `match` is passed to Graph's $search, which
# looks at sender, subject and body, so a publication name is enough.
# THREE WAYS TO FIND A DIGEST, in descending order of precision:
#
#   sender      exact From address. Best at proving it is really them, and on
#               its own NOT the tightest option -- a publisher sends several
#               products from one address. Pair it with sender_name.
#   sender_name From display name, matched with startswith, for publishers
#               whose address is not visible in the mail client. Prefix rather
#               than equals because these names vary: eMeat sends as both "The
#               EMEAT Daily Bulletin" and "The EMEAT Daily Bulletin - 3 Price
#               Alerts". Still body-free.
#   subject  Graph KQL "subject:..." -- searches the SUBJECT LINE ONLY, never
#            the body. Right when the address is unknown but the subject is
#            distinctive.
#   match    bare $search, which reads sender, subject AND body. A word like
#            "sterling" then also matches a client email about sterling silver,
#            and that message's text surfaces in the panel. Fallback only.
#
# Each entry should GAIN the fields above it as its first real digest arrives
# and the From address becomes visible -- gain, not move. Meatingplace and
# eMeat were switched from name to address on 2026-09-28 and it had to be
# reverted the same hour: both addresses also carry a second product the name
# filter was deliberately excluding. See from_clause().
DIGESTS = [
    # Two a day, Morning Update and Afternoon Update, and the SUBJECT is the
    # lead headline rather than a title for a list of them.
    {"label": "Meatingplace", "sender": "newsletters@newsletter.meatingplace.com",
     "sender_name": "Meatingplace Editorial"},
    # The Bulletin only. "The EMEAT Team" is the same publisher's marketing --
    # weekly newsletters and "50% off" promotions -- and does not belong in a
    # market headline panel.
    {"label": "eMeat", "sender": "marketing@emeat.io",
     "sender_name": "The EMEAT Daily Bulletin"},
    # agritrends.com, NOT globalagritrends.com. It was the latter from the day
    # this was written until 2026-09-25, and matched nothing the whole time --
    # an exact sender filter that is wrong returns zero messages, which is
    # exactly what a publisher who did not write today also returns. It only
    # surfaced because the source had been quiet two days running and that
    # looked worth checking. See _never_matched below.
    #
    # no-reply ONLY. bstuart@agritrends.com is a person at the same firm who
    # replies about price moves, and that correspondence is not a digest.
    {"label": "Global AgriTrends", "sender": "no-reply@agritrends.com"},
    # John Nalivka at Sterling Marketing. The address is exact where "sterling"
    # as a word search was not; it also catches every flavour he sends -- Profit
    # Tracker, Monthly, Red Meat Trade, Pork Industry -- which a subject match
    # on one of them would not. The Profit Tracker carries the packer margin the
    # evening letter quotes by hand.
    {"label": "Sterling", "sender": "jnalivka@fmtc.com"},
]

# Boilerplate that appears as a link in every marketing email. Extended
# 2026-09-24, the first day this saw real messages -- the four below are all
# things it actually offered Ross as cattle headlines.
_CHROME = re.compile(
    r"unsubscribe|privacy polic|terms of|contact us|advertise|"
    r"forward to a friend|update profile|follow us|subscribe|log ?in|sign ?in|"
    r"click here|read more|"
    # "View this email in your browser" -- the optional noun in the middle is
    # why the original "view (this |it )?in browser" missed it.
    r"view (this |it )?(e-?mail |message )?in (your )?browser|"
    # "manage/update/change [your] [email|subscription] preferences"
    r"(manage|update|change|edit) (your )?(e-?mail |subscription |contact )?preferences|"
    # "Customize your Daily Bulletin"
    r"customi[sz]e your|update your|"
    r"^\W*$", re.I)

# A link whose text IS the address it points at -- "newsletters@newsletter.
# meatingplace.com", "https://emeat.io/dashboard/tables". Long enough to clear
# the length check and made of letters, so nothing else here catches them, and
# they are never a headline. One token with an @ or a scheme in it.
_BARE_LINK = re.compile(r"^\S+$") 


def configured() -> bool:
    return bool(os.environ.get("GRAPH_CLIENT_ID") and os.environ.get("GRAPH_TENANT_ID"))


def _app():
    import msal
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.exists():
        cache.deserialize(TOKEN_CACHE.read_text(encoding="utf-8"))
    app = msal.PublicClientApplication(
        client_id=os.environ["GRAPH_CLIENT_ID"],
        authority=f"https://login.microsoftonline.com/{os.environ['GRAPH_TENANT_ID']}",
        token_cache=cache,
    )
    return app, cache


_TOKEN_SYNCED = False


def sync_token(force: bool = False) -> str:
    """
    Reconcile the cached sign-in with Snowflake. Newest wins.

    WHY THIS EXISTS. TOKEN_CACHE lives under letter/data/, which is gitignored
    and which a Streamlit Cloud reboot rebuilds empty -- so the deployed
    headline panel lost the mailbox on every restart and showed "Connect
    mailbox" until someone did the device-code flow again. The addresses were
    never the problem; the session was.

    ONCE PER PROCESS unless the file is missing. A container that has just
    started has no cache and must pull; after that the local copy is the live
    one, MSAL rewrites it on every refresh, and a SELECT per headline fetch
    would be waste. `force` is there for a caller that knows better.
    """
    global _TOKEN_SYNCED
    if not draft_store.enabled():
        return ""
    if _TOKEN_SYNCED and not force and TOKEN_CACHE.exists():
        return ""
    _TOKEN_SYNCED = True
    try:
        return draft_store.restore(TOKEN_CACHE, draft_store.SINGLETON_DATE,
                                   draft_store.GRAPH_TOKEN_KIND,
                                   label="Mailbox sign-in")
    except Exception:
        return ""          # a token that will not sync is not a broken letter


def _save(cache) -> None:
    if cache.has_state_changed:
        TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
        TOKEN_CACHE.write_text(cache.serialize(), encoding="utf-8")
        # UP AS WELL AS DOWN, or a sign-in done on the deployed app is lost at
        # the next reboot exactly as before. Swallowed: the file write has
        # already succeeded, and an unreachable Snowflake must never be the
        # reason a headline panel stops working.
        try:
            draft_store.backup(TOKEN_CACHE, draft_store.SINGLETON_DATE,
                               draft_store.GRAPH_TOKEN_KIND, "mailbox")
        except Exception:
            pass


def token(interactive: bool = False):
    """
    A Graph token, or (None, device_flow) when sign-in is needed.

    Silent whenever a cached account exists, so the daily build never blocks.
    `interactive=True` starts the device-code flow and returns the flow dict for
    the caller to show -- this module never prints a code or waits on a human of
    its own accord.
    """
    if not configured():
        return None, {"error": "GRAPH_CLIENT_ID / GRAPH_TENANT_ID not set"}
    # BEFORE _app() READS THE FILE. On a fresh container there is nothing on
    # disk, and this is the step that puts the sign-in back.
    sync_token()
    app, cache = _app()
    accounts = app.get_accounts()
    if accounts:
        result = app.acquire_token_silent(SCOPES, account=accounts[0])
        if result and "access_token" in result:
            _save(cache)
            return result["access_token"], None
    if not interactive:
        return None, {"error": "not signed in"}
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        return None, {"error": f"device flow failed: {flow.get('error_description', flow)}"}
    return None, flow


def complete_sign_in(flow: dict):
    """Block until the user finishes the device-code flow. Caller's choice."""
    app, cache = _app()
    result = app.acquire_token_by_device_flow(flow)
    _save(cache)
    return result.get("access_token")


def _strip_html(html: str) -> str:
    html = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html or "", flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", html)


def parse_headlines(body: str, content_type: str = "html", limit: int = 15) -> list:
    """
    Pull headline-ish lines out of a digest.

    HEURISTIC, AND IT WILL NEED TUNING against a real message -- every publisher
    lays these out differently. Anchor text is tried first because a digest is
    almost always a list of linked headlines; failing that, the stripped text is
    read line by line. Both paths drop marketing chrome and anything too short
    to be a headline or long enough to be a paragraph.
    """
    out, seen = [], set()

    if content_type == "html":
        candidates = [re.sub(r"\s+", " ", _strip_html(a)).strip()
                      for a in re.findall(r"<a\b[^>]*>(.*?)</a>", body or "", re.S | re.I)]
    else:
        candidates = []

    if not candidates:
        text = body if content_type != "html" else _strip_html(body)
        candidates = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]

    for line in candidates:
        if not (25 <= len(line) <= 160):
            continue
        if _CHROME.search(line):
            continue
        if _BARE_LINK.match(line) and ("@" in line or "://" in line):
            continue
        if not re.search(r"[A-Za-z]{3}", line):
            continue
        key = line.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(line)
        if len(out) >= limit:
            break
    return out


def from_clause(src: dict) -> str:
    """
    The $filter that identifies a digest's sender, or "" for a $search matcher.

    BOTH WHEN BOTH ARE GIVEN, and that is the whole point of this function.
    An exact address looks like the tightest possible matcher and for these two
    publishers it is the LOOSEST: on 2026-09-28 the mailbox held, from one
    address each, 22 "The EMEAT Team" marketing mails beside the 47 Daily
    Bulletins on marketing@emeat.io, and 36 "Meatingplace Blogs" beside the 87
    "Meatingplace Editorial" digests on newsletters@newsletter.meatingplace.com.
    Moving those two entries from the display name to the address, which is
    what the docstring above told you to do, would have put promotions and blog
    posts into a market headline panel.

    One publisher, one address, several products. The address answers "is this
    really them", the display name answers "is this the product we want", and
    neither question is the other. Requiring both is strictly tighter than
    either alone -- a spoofed display name now fails the address, and the
    marketing still fails the name.

    Graph accepts the conjunction: address eq ... and startswith(name, ...) and
    receivedDateTime ge ... returns 200. Verified before this was written,
    because a $filter on from/emailAddress is exactly the shape that 400s --
    see the $orderby note in fetch_digests.
    """
    bits = []
    if src.get("sender"):
        bits.append(f"from/emailAddress/address eq '{src['sender']}'")
    if src.get("sender_name"):
        bits.append(f"startswith(from/emailAddress/name,'{src['sender_name']}')")
    return " and ".join(bits)


def _never_matched(headers: dict, src: dict) -> bool:
    """
    True when this source's matcher finds NOTHING in the whole mailbox.

    THE POINT IS TO TELL TWO IDENTICAL-LOOKING FAILURES APART. "Global
    AgriTrends: nothing in the last 72h" was on screen every day from the day
    this module was written until 2026-09-25, and it was not a quiet publisher
    -- the address was globalagritrends.com where the sender is agritrends.com.
    An exact filter that is wrong returns zero rows, which is the same answer a
    publisher who did not write today gives.

    One extra request, only on the path that already found nothing, and the
    panel gets to say "check the address" instead of shrugging.
    """
    import requests
    clause = from_clause(src)
    if not clause:
        return False          # a $search matcher is broad by nature; no verdict
    q = {"$filter": clause, "$top": 1, "$select": "id"}
    try:
        r = requests.get(f"{GRAPH}/me/messages", headers=headers, timeout=30, params=q)
        return r.status_code == 200 and not r.json().get("value")
    except Exception:
        return False          # a failed check proves nothing


def fetch_digests(max_age_h: int = 72, per_source: int = 10) -> dict:
    """
    {"items": [...], "errors": [...]} from the configured digests.

    THREE DAYS, NOT ONE. These are not all dailies -- Sterling arrives a few
    times a week, and on 2026-09-23 its newest was Monday afternoon, about 45
    hours old. A 30-hour window silently dropped it. Every item carries its age
    so the panel can show how fresh each one is and let Ross judge.

    Never raises and never blocks on sign-in: an unconfigured or signed-out
    mailbox is one line in the panel, not a failed morning.
    """
    import requests

    items, errors = [], []
    access, problem = token(interactive=False)
    if not access:
        return {"items": [], "errors": [f"mailbox: {problem.get('error')}"], "needs_sign_in": True}

    since = (datetime.now(timezone.utc) - timedelta(hours=max_age_h))
    headers = {"Authorization": f"Bearer {access}",
               "ConsistencyLevel": "eventual"}

    for src in DIGESTS:
        # An exact sender filter where we have the address; full-text search
        # only as a fallback. See the note on DIGESTS -- search reads the body,
        # so it can match mail that has nothing to do with the publication.
        fields = "subject,receivedDateTime,body,from"
        # NO $orderby ON A SENDER FILTER, AND A DATE CLAUSE INSTEAD.
        #
        # Graph rejects $filter on from/emailAddress with $orderby
        # receivedDateTime outright -- 400 InefficientFilter, every request,
        # which is how this shipped: the panel said "not signed in" for weeks
        # and the moment it WAS signed in, all four sources returned HTTP 400.
        #
        # Dropping $orderby alone is the trap, and it is a silent one. The
        # default order on /me/messages is OLDEST FIRST, so a bare sender filter
        # with $top 5 returns five mails from 2025 -- every one of them outside
        # the age window, every source reporting "nothing recent", for ever,
        # while the digests arrive daily. Verified: Sterling came back starting
        # 2025-12-16 and Meatingplace 2026-08-26.
        #
        # The date clause does both jobs. It is legal beside the sender filter,
        # it bounds the result to the window the caller asked for, and with a
        # generous $top the newest-picking below has everything it needs. A
        # date-only filter WOULD take $orderby -- same property -- but this
        # mailbox runs ~11 messages an hour, so 72 hours is several hundred
        # messages and hundreds of pages to walk.
        since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
        clause = from_clause(src)
        if clause:
            query = {"$filter": f"{clause} and receivedDateTime ge {since_iso}",
                     "$top": 25, "$select": fields}
        elif src.get("subject"):
            # KQL property restriction: subject line only, body untouched.
            # $search takes no $orderby either -- 400 SearchWithOrderBy -- and
            # no date clause, so it leans on the client-side age check below.
            query = {"$search": f'subject:"{src["subject"]}"', "$top": 25, "$select": fields}
        else:
            query = {"$search": f'"{src["match"]}"', "$top": 25, "$select": fields}
        try:
            r = requests.get(f"{GRAPH}/me/messages", headers=headers,
                             timeout=30, params=query)
            if r.status_code != 200:
                errors.append(f"{src['label']}: HTTP {r.status_code}")
                continue
            messages = r.json().get("value", [])
        except Exception as e:
            errors.append(f"{src['label']}: {type(e).__name__}")
            continue

        newest = None
        for m in messages:
            try:
                when = datetime.fromisoformat(m["receivedDateTime"].replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if when < since:
                continue
            if newest is None or when > newest[0]:
                newest = (when, m)
        if not newest:
            if _never_matched(headers, src):
                who = src.get("sender") or src.get("sender_name")
                errors.append(f"{src['label']}: NO mail from '{who}' in the whole "
                              f"mailbox -- check the address, not the calendar")
            else:
                errors.append(f"{src['label']}: nothing in the last {max_age_h}h")
            continue

        when, msg = newest
        body = (msg.get("body") or {})
        age = round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)

        # THE SUBJECT COUNTS. Meatingplace puts the lead story in the subject
        # line and the words "Morning Update" in the body, so parsing only the
        # body throws away the best headline in the message.
        lines = []
        subject = re.sub(r"\s+", " ", str(msg.get("subject") or "")).strip()
        if subject and not _CHROME.search(subject) and len(subject) >= 12:
            lines.append(subject)
        for line in parse_headlines(body.get("content", ""),
                                    body.get("contentType", "html"), per_source):
            if line.lower() != subject.lower():
                lines.append(line)

        for line in lines:
            items.append({"source": src["label"], "title": line,
                          "when": when.isoformat(), "age_h": age, "link": ""})

    return {"items": items, "errors": errors}
