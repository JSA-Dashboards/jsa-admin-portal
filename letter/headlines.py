"""
Candidate headlines for the morning brief's Headlines section.

NOTHING HERE REACHES THE LETTER. These are suggestions shown beside the
Headlines box on the authoring page, for Ross to pick from and rewrite. Every
other figure in the brief is a USDA or CME number that is either right or
marked [[?]]; a headline is editorial, and there is no [[?]] for "a feed
surfaced something misleading and it went out over JSA's name". So the split is
deliberate: fetched here, written by hand there.

It also keeps the copyright question simple. Facts are not copyrightable and can
be restated freely; someone else's headline text is theirs. Showing a title on a
private, passphrase-gated page as a pointer to go read the story is a different
act from reprinting it in a PDF sent to paying clients.

Four kinds of source:

  RSS        Beef Magazine responds to an ordinary request. Drovers and AgWeb
             both return 403 to anything that is not a browser, Meatingplace is
             subscriber-only, and Reuters' agriculture feed is dead -- so the
             list is deliberately short rather than padded with feeds that fail
             silently.

             THAT 403 IS NO LONGER THE END OF THE STORY: see Trade below. A
             publisher who refuses a script is still indexed, so their reporting
             is reachable without a request ever touching their server.

  USDA prose The narratives already fetched for the numbers. AMS writes a
             paragraph on every daily cash report describing how the trade went,
             and the border reports carry USDA's own commentary. Authoritative,
             free, cattle-specific, and no third party's copy.

  Packers    A Google News search for the four beef packers and for plant
             disruption generally, over RSS. ADDED 2026-09-23 BECAUSE OF A MISS:
             an ICE operation in Kansas had meatpacking plants delaying shifts,
             it ran on KMUW and across the Kansas public stations, and this
             panel never saw it.

             The lesson is about the SHAPE of the source, not the length of the
             feed list. What stops a plant for a shift gets reported where the
             plant is -- a local newsroom -- and no fixed list of trade feeds
             subscribed to those newsrooms or ever will. Only a query finds a
             story like that.

             Being a query is also its weakness, and it is a different weakness
             from the rest of this module: a feed either answers or it 404s,
             while a search that returns nothing looks exactly like a quiet news
             day. Read it as recall, never as coverage.

  Trade and  Two more searches, scoped by site:. Drovers and Beef Magazine, who
  newsrooms  write about nothing else; and Reuters, Politico, the WSJ and the
             NYT, who write about cattle only when something has happened.

             They are filtered DIFFERENTLY and that is the point. The general
             newsrooms get _NEWSROOM, which is strict because they produce
             "squash beef" and "clean tech exports". The trade press gets the
             ordinary _RELEVANT, because a cattle publication does not need
             disambiguating -- run Drovers through the strict filter and "Fall
             Calf Run Begins as Prices Ease" is discarded, since that filter has
             no word for "calf" and never needed one.
"""
from __future__ import annotations

import html
import re
from datetime import date, datetime, timezone
from email.utils import parsedate_to_datetime

from . import mailbox, sources

# Feeds that actually answer. Verified 2026-09-23; the ones that do not are
# named in the module docstring so nobody re-adds them hopefully.
RSS_FEEDS = [
    ("Beef Magazine", "https://www.beefmagazine.com/rss.xml"),
]

# A browser-ish agent: several ag publishers reject the requests default.
_UA = {"User-Agent": "Mozilla/5.0 (compatible; JSA-letter/1.0)"}

# Cattle words. The feeds are general-agriculture, so without this the list
# fills with corn agronomy and the panel stops being worth reading.
#
# THE PACKER AND PLANT WORDS ARE LOAD-BEARING, and were missing until
# 2026-09-23. "ICE agents in Kansas cause schools to warn families and
# meatpacking plants to delay shifts" contains not one word of the original
# list: not "packer" -- the word is "meatpacking" -- and no company name. So the
# headline was thrown out as agronomy before anyone asked which feed carried it.
# A story about the packers not killing cattle is a cattle story.
#
# The plant words are PHRASES on purpose, and each one carries a MEAT
# qualifier. A bare "plant" matches planting intentions, plant disease and every
# agronomy item in a general-ag feed. A bare "processing plant" is worse, and it
# was tried: the first run of the packer search returned a post office in Sioux
# Falls, a Norwegian salmon plant and a warehouse fire in Calgary, all of them
# genuine "processing plant" stories and none of them cattle.
#
# "beef plant" and "slaughter plant" need no entry of their own -- "beef" and
# "slaughter" already stand alone above.
_RELEVANT = re.compile(
    r"\b(cattle|beef|feeder|fed|packers?|cow|heifer|steer|calf|calves|slaughter|"
    r"carcass|cutout|boxed|herd|feedlot|feedyard|cme|usda|export|import|tariff|"
    r"mexico|canada|screwworm|foot.and.mouth|drought|"
    r"tyson|jbs|cargill|national beef|greater omaha|"
    r"meat.?packing|packing\s+(?:plants?|facilit(?:y|ies))|"
    r"meat\s+(?:processing|plants?|facilit(?:y|ies)))\b", re.I)


def _clean(text: str) -> str:
    text = re.sub(r"<!\[CDATA\[|\]\]>", "", text or "")
    text = re.sub(r"<[^>]+>", "", text)
    # AFTER the tags come out, not before: an escaped &lt;b&gt; should survive as
    # visible text rather than become a tag and get stripped. Without this the
    # panel shows "Tyson&#39;s" and a picked headline carries that into the
    # Headlines box and then into the letter.
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# A morning brief wants this morning's news. Beyond two days an item is not a
# headline, it is background -- "CSU names livestock complex" and "July/August
# edition available" are both real feed items from this week.
MAX_AGE_HOURS = 48


def fetch_rss(name: str, url: str, limit: int = 12, max_age_h: int = MAX_AGE_HOURS) -> list:
    """Recent items from one feed, filtered to cattle-relevant titles."""
    out = []
    try:
        r = sources._session().get(url, timeout=15, headers=_UA)
        if r.status_code != 200:
            return [{"source": name, "error": f"HTTP {r.status_code}"}]
        body = r.text
    except Exception as e:
        return [{"source": name, "error": f"{type(e).__name__}"}]

    for block in re.findall(r"<item[^>]*>(.*?)</item>", body, re.S | re.I)[:60]:
        title = _clean((re.search(r"<title[^>]*>(.*?)</title>", block, re.S) or [None, ""])[1])
        if not title or not _RELEVANT.search(title):
            continue
        link = _clean((re.search(r"<link[^>]*>(.*?)</link>", block, re.S) or [None, ""])[1])
        raw_date = _clean((re.search(r"<pubDate[^>]*>(.*?)</pubDate>", block, re.S) or [None, ""])[1])
        when = None
        if raw_date:
            try:
                when = parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                when = None
        age = (round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)
               if when and when.tzinfo else None)
        # An item with no parseable date is kept: unknown is not the same as old.
        if age is not None and age > max_age_h:
            continue
        out.append({"source": name, "title": title, "link": link,
                    "when": when.isoformat() if when else None, "age_h": age})
        if len(out) >= limit:
            break
    return out


# Google News over RSS: no key, no account, and it indexes the local newsrooms
# that actually cover a plant. The `when:Nd` operator does the recency cut
# server-side; the client-side age check below still runs, because an item with
# no parseable date would otherwise slip the window.
GOOGLE_NEWS = "https://news.google.com/rss/search"

# TWO QUERIES, NOT FOUR. One per packer would be four requests for one panel and
# would still miss the story that names no company -- which is most of them, the
# Kansas one included. So: one query that names the packers, one that describes
# the event.
#
# EVERY TERM IS QUALIFIED. "Tyson" alone is a boxer and a food company with a
# dozen chicken plants; "packing plant" alone is a cardboard factory. The
# qualifier in each query is what keeps this a cattle panel.
PACKER_QUERIES = [
    ("packers", '(Tyson OR JBS OR Cargill OR "National Beef") (beef OR cattle OR plant)'),
    ("plants", '("beef plant" OR "meatpacking plant" OR "packing plant" OR '
               '"processing plant") '
               '(cattle OR beef OR slaughter OR shift OR closure OR raid OR workers)'),
]


# GENERAL-INTEREST NEWSROOMS, added 2026-09-24 at Ross's request. These four
# do not run a cattle desk, and when they do write about cattle it is because
# something happened that the trade press will cover a day later -- an import
# rule, a tariff, a screwworm ban, a packer's earnings. Worth having; worth
# filtering hard.
GENERAL_NEWS_SITES = ["reuters.com", "politico.com", "wsj.com", "nytimes.com"]

# GOOGLE APPLIES THE TOPIC TERMS LOOSELY WHEN A site: FILTER IS PRESENT. A live
# run of this exact query returned 100 items, of which 95 were NYT Cooking, the
# NYC Marathon and Venezuelan politics. The query narrows the SOURCE; the strict
# filter below is what narrows the subject, and it is doing almost all the work.
GENERAL_NEWS_QUERY = ("(cattle OR beef OR meatpacking OR feedlot OR rancher) ("
                      + " OR ".join(f"site:{s}" for s in GENERAL_NEWS_SITES) + ")")

# A TIGHTER TEST THAN _RELEVANT, because general news breaks that one in ways an
# ag feed never does. Both of these were real results:
#
#   "Seahawks' Mike Macdonald, Broncos' Sean Payton squash beef"  -- bare "beef"
#   "China's clean tech exports avoided more CO2 than the UK"     -- bare "export"
#
# So "beef" only counts next to an industry word, and the trade words that carry
# a cattle story in a farm feed carry nothing on their own here.
_NEWSROOM = re.compile(
    r"\b(cattle|feedlot|feedyard|ranchers?|meat.?packing|screwworm|cow herd|"
    r"packing plant|tyson foods|jbs|cargill|national beef|"
    r"beef\s+(?:price|prices|import|imports|export|exports|industry|producers?|"
    r"supply|market|quota|tariffs?|packers?|plant|herd|cow|cattle))\b", re.I)

# Not stories. A ticker page matches every content test there is -- "Tyson Foods
# Inc. Cl A (TSN) Stock Price Today" is the publisher's quote widget, not
# reporting, and it turns up every single run.
_NOT_A_STORY = re.compile(r"stock price today|\bstock quote\b|share price|price quote", re.I)


# TRADE PRESS, scoped the same way but filtered the LOOSE way. Added at Ross's
# request 2026-09-24.
#
# DROVERS IS THE POINT OF DOING IT LIKE THIS. This module's docstring records
# that Drovers 403s anything that is not a browser, which is why it was never an
# RSS feed -- but Google indexes them, so a site: query reaches their reporting
# without a request ever touching their server.
#
# Beef Magazine is here as well as in RSS_FEEDS on purpose. That feed is the
# only one in the list, so it is a single point of failure; the search is a
# second road to the same publisher, and _dedupe collapses the overlap.
#
# _RELEVANT, NOT _NEWSROOM. The strict filter exists because a general newsroom
# writes "squash beef" and "clean tech exports"; a cattle publication does not.
# Run through it, "Fall Calf Run Begins as Prices Ease" is thrown away -- the
# strict test has no word for "calf", because it never needed one.
TRADE_NEWS_SITES = ["drovers.com", "beefmagazine.com"]

TRADE_NEWS_QUERY = ("(cattle OR beef OR feeder OR calves OR packer OR corn) ("
                    + " OR ".join(f"site:{s}" for s in TRADE_NEWS_SITES) + ")")


def _google_news(label: str, query: str, relevant, limit: int,
                 max_age_h: int, seen: set) -> list:
    """
    One Google News search. Returns items and error rows, never raises.

    Titles arrive as "Headline - Publisher" with the publisher also in its own
    <source> tag, so the suffix is stripped and the publisher becomes the
    attribution -- which is the part worth reading, since half these outlets are
    ones Ross has never heard of and should judge for himself.

    Links are Google's redirect URLs rather than the publisher's. They open
    fine; they are just ugly, and there is no way to ask this feed for the real
    one without following each redirect.

    `relevant` is passed in because the packer search and the newsroom search
    need different tests -- see _NEWSROOM.
    """
    out = []
    # `when:` takes whole days, and rounding DOWN would cut the window short.
    days = max(1, -(-int(max_age_h) // 24))
    try:
        r = sources._session().get(
            GOOGLE_NEWS, timeout=20, headers=_UA,
            params={"q": f"{query} when:{days}d", "hl": "en-US",
                    "gl": "US", "ceid": "US:en"})
        if r.status_code != 200:
            return [{"source": f"Google News ({label})", "error": f"HTTP {r.status_code}"}]
        body = r.text
    except Exception as e:
        return [{"source": f"Google News ({label})", "error": f"{type(e).__name__}"}]

    # A 200 THAT IS NOT A FEED IS THE FAILURE THAT MATTERS. Google answers a
    # datacenter IP with a consent interstitial or a sorry page -- status 200,
    # no <item> in it -- and the panel would then show one fewer source and say
    # nothing, which is exactly the quiet failure this module's docstring warns
    # about.
    #
    # Zero PARSED items is different and not an error: the queries are narrow,
    # and a morning with no packer news is a real morning.
    blocks = re.findall(r"<item>(.*?)</item>", body, re.S | re.I)
    if not blocks:
        return [{"source": f"Google News ({label})",
                 "error": "answered 200 but sent no feed "
                          "-- blocked, rate-limited or asking for consent"}]

    kept = 0
    for block in blocks[:100]:
        title = _clean((re.search(r"<title[^>]*>(.*?)</title>", block, re.S) or [None, ""])[1])
        pub = _clean((re.search(r"<source[^>]*>(.*?)</source>", block, re.S) or [None, ""])[1])
        # Only strip the suffix when it really is the publisher's name -- plenty
        # of headlines contain " - " of their own.
        if pub and title.endswith(f" - {pub}"):
            title = title[: -(len(pub) + 3)].strip()
        if not title or not relevant.search(title) or _NOT_A_STORY.search(title):
            continue
        key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        if key in seen:
            continue

        raw_date = _clean((re.search(r"<pubDate[^>]*>(.*?)</pubDate>", block, re.S)
                           or [None, ""])[1])
        when = None
        if raw_date:
            try:
                when = parsedate_to_datetime(raw_date)
            except (TypeError, ValueError):
                when = None
        age = (round((datetime.now(timezone.utc) - when).total_seconds() / 3600, 1)
               if when and when.tzinfo else None)
        if age is not None and age > max_age_h:
            continue

        seen.add(key)
        link = _clean((re.search(r"<link[^>]*>(.*?)</link>", block, re.S) or [None, ""])[1])
        out.append({"source": pub or "Google News", "title": title, "link": link,
                    "when": when.isoformat() if when else None, "age_h": age})
        kept += 1
        if kept >= limit:
            break
    return out


def fetch_packer_news(limit: int = 10, max_age_h: int = MAX_AGE_HOURS) -> list:
    """Beef packer and plant news, from the trade and the local newsrooms."""
    out, seen = [], set()
    for label, query in PACKER_QUERIES:
        out.extend(_google_news(label, query, _RELEVANT, limit, max_age_h, seen))
    return out


def fetch_general_news(limit: int = 8, max_age_h: int = MAX_AGE_HOURS) -> list:
    """
    Cattle stories from Reuters, Politico, the WSJ and the NYT.

    ONE REQUEST FOR ALL FOUR, because Google's site: filter takes an OR list and
    four separate searches would be four round trips on a button Ross is waiting
    on. The cost is that the per-source cap is shared; with a filter this strict
    that has never been the binding constraint.
    """
    return _google_news("newsrooms", GENERAL_NEWS_QUERY, _NEWSROOM,
                        limit, max_age_h, set())


def fetch_trade_news(limit: int = 8, max_age_h: int = MAX_AGE_HOURS) -> list:
    """Drovers and Beef Magazine, via the search rather than their servers."""
    return _google_news("trade", TRADE_NEWS_QUERY, _RELEVANT, limit, max_age_h, set())


def fetch_usda_narratives(as_of: date = None) -> list:
    """
    AMS's own written commentary on the cash trade, plus the border narrative.

    The AMS paragraph is the single most useful line in this panel most
    mornings: it is USDA describing the trade in prose, published daily, and not
    anyone's copyrighted reporting.
    """
    out = []

    # National daily negotiated summary (LM_CT115) carries a `trend` paragraph.
    try:
        r = sources._session().get(f"{sources.LMR_BASE}/2662/",
                                   params={"lastReports": 1, "allSections": "true"}, timeout=30)
        r.raise_for_status()
        payload = r.json()
        for sec in (payload if isinstance(payload, list) else [payload]):
            if sec.get("reportSection") != "Summary":
                continue
            for row in sec.get("results", [])[:1]:
                trend = _clean(row.get("trend"))
                if trend:
                    out.append({"source": "USDA AMS cash trade",
                                "title": trend,
                                "when": row.get("published_date"),
                                "pinned": True,
                                "link": ""})
            break
    except Exception as e:
        out.append({"source": "USDA AMS cash trade", "error": f"{type(e).__name__}"})

    # Border commentary, from the same Snowflake table the imports page reads.
    try:
        db = sources._load_fci_db()
        conn = db.get_conn()
        try:
            df = db.read_sql_lower(
                "SELECT report_date, narrative FROM border_reports "
                "WHERE kind = 'commentary' ORDER BY report_date DESC", conn)
        finally:
            conn.close()
        if not df.empty:
            row = df.iloc[0]
            text = _clean(str(row.get("narrative") or ""))
            if text:
                out.append({"source": "USDA border report", "pinned": True,
                            "title": text, "when": str(row.get("report_date")), "link": ""})
    except Exception:
        # Snowflake being unavailable is not worth a panel-wide error; the AMS
        # narrative and the feed still stand on their own.
        pass

    return out


_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def _when_key(item: dict):
    """
    A sortable UTC timestamp for a candidate, for newest-first display.

    THREE FORMATS REACH THIS, because the sources genuinely differ:

        2026-09-24T14:27:40+00:00   RSS, Google News, the mailbox -- ISO, tz-aware
        09/24/2026 11:07:09         AMS, US order, no zone
        2026-09-23                  the border report -- a date, no time at all

    A naive stamp is read as UTC. AMS publishes in Eastern, so its line can sort
    a few hours earlier than it really is; that is a place in a pick list, not a
    wrong number, and guessing a zone per source would be the bigger error. The
    date-only border report lands at midnight, which puts it at the end of its
    day -- right, since nothing says when in that day it came.

    Anything unparseable sorts to the bottom rather than the top: an item whose
    age is unknown must not claim to be the newest thing on the page.
    """
    raw = str(item.get("when") or "").strip()
    if not raw:
        return _EPOCH
    for parse in (
        lambda v: datetime.fromisoformat(v),
        lambda v: datetime.strptime(v, "%m/%d/%Y %H:%M:%S"),
        lambda v: datetime.strptime(v, "%m/%d/%Y"),
        lambda v: datetime.fromisoformat(v[:10]),
    ):
        try:
            got = parse(raw)
        except (TypeError, ValueError):
            continue
        return got if got.tzinfo else got.replace(tzinfo=timezone.utc)
    return _EPOCH


def _dedupe(items: list) -> list:
    """
    One row per story.

    Needed once the packer search is in: a plant closure runs on the wire and
    comes back from both queries, from Beef Magazine, and again from whichever
    digest picked it up. Matching is on the title with punctuation and case
    thrown away, so it collapses the same headline reprinted -- not the same
    story rewritten by two newsrooms, which stays as two rows. That is the right
    side to err on: a duplicate costs a glance, a dropped story is the bug this
    whole change is about.

    First occurrence wins, so source order below is priority order.
    """
    seen, out = set(), []
    for item in items:
        key = re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or "").lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def candidates(as_of: date = None, limit_per_feed: int = 12,
               max_age_h: int = MAX_AGE_HOURS, include_mailbox: bool = True,
               include_packers: bool = True) -> dict:
    """
    {"items": [...], "errors": [...], "needs_sign_in": bool} -- everything to
    offer, plus what failed and why.

    Sources are independent: a dead feed, an unconfigured mailbox, a search that
    answers with nothing and a Snowflake outage each cost their own line and
    nothing else.
    """
    items, errors, needs_sign_in = [], [], False

    for row in fetch_usda_narratives(as_of):
        (errors if row.get("error") else items).append(row)

    for name, url in RSS_FEEDS:
        for row in fetch_rss(name, url, limit_per_feed, max_age_h):
            (errors if row.get("error") else items).append(row)

    # Packer and plant news. Sits above the digests because it is the source
    # most likely to be carrying something nobody else has -- see the module
    # docstring for the miss that put it here.
    if include_packers:
        for row in fetch_packer_news(max_age_h=max_age_h):
            (errors if row.get("error") else items).append(row)
        # Drovers and Beef Magazine, which write about nothing else.
        for row in fetch_trade_news(max_age_h=max_age_h):
            (errors if row.get("error") else items).append(row)
        # Reuters / Politico / WSJ / NYT. Last of the fetched sources because
        # when these four write about cattle it is policy and trade -- context
        # for the letter rather than the day's market news.
        for row in fetch_general_news(max_age_h=max_age_h):
            (errors if row.get("error") else items).append(row)

    # The paid digests, read from Ross's own mailbox -- see letter/mailbox.py
    # for why that is the right door rather than the publishers' websites.
    if include_mailbox:
        got = mailbox.fetch_digests(max_age_h=max(max_age_h, 72))
        items.extend(got.get("items", []))
        errors.extend({"source": "", "error": e} for e in got.get("errors", []))
        needs_sign_in = bool(got.get("needs_sign_in"))

    # USDA FIRST, THEN NEWEST. Sorted after the dedupe, not before: dedupe keeps
    # the FIRST occurrence and the source order above is priority order, so the
    # USDA copy of a story survives over a newsroom's. Ordering is display only
    # and must not decide which duplicate wins.
    #
    # THE PIN EXISTS BECAUSE A PURE TIME SORT BURIED THE BEST LINE. AMS writes a
    # paragraph on the day's cash trade every day -- this module's docstring
    # calls it the single most useful line in the panel most mornings -- and on
    # 2026-09-24 it landed at 22 of 42, with the border report at 41. Not
    # because they were stale: AMS stamps in Eastern with no zone, and the
    # border report carries a date and no time at all, so both read older than
    # they are. They are also not really headlines -- they are USDA's own prose
    # about this market, which is why they get a different rule.
    #
    # Flagged at the source rather than matched on the name here: an outlet
    # called "USDA Reports Weekly" arriving from a news search must not pin
    # itself to the top of Ross's panel.
    #
    # reverse=True reads both parts of the key -- pinned (True sorts first),
    # then the timestamp, newest first within each group. Stable, so the ten
    # headlines out of one digest keep the order they were parsed in.
    ordered = sorted(_dedupe(items),
                     key=lambda i: (bool(i.get("pinned")), _when_key(i)),
                     reverse=True)

    return {"items": ordered,
            "errors": [(f"{e['source']}: {e['error']}" if e.get("source") else e["error"])
                       for e in errors],
            "needs_sign_in": needs_sign_in}
