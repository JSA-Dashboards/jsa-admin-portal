"""
"On this day" candidates for the letter, as a pick list.

WHAT THIS IS NOT. Nothing here writes itself into a letter. These are
candidates on the authoring page, exactly like the headlines, and for exactly
the same reason: a fact is EDITORIAL, and the rule this generator is built on
is that no fetched editorial text reaches a client under JSA's name without a
human choosing it. Every other figure in the letter is a USDA or CME number
that is either right or marked [[?]]; a fun fact cannot be marked.

WHY A HUMAN IS THE SAFETY, AND NOT THE FILTER. The first version of this
filter offered the 2017 Las Vegas mass shooting as an AGRICULTURE fact --
"Route 91 Harvest festival" matched the farming pattern, and the grim filter
missed it because every stem in it was written \\bmurder\\b, which does not
match "murdered". Khashoggi, Mogadishu and the Amish school shooting came
through the same hole.

Two lessons are baked in below. Stems match as PREFIXES. And a candidate must
earn its place POSITIVELY -- sport, agriculture, or a US first -- rather than
being admitted unless something looks wrong. A denylist over an encyclopaedia
fails open, and failing open here means handing Ross a massacre to pick from.
Even so, the filter will let something tasteless through eventually. That
costs a glance, because he picks. It would cost a letter if it did not.

THE FACTS ARE NOT THE PROSE. history.com's blurbs are copyrighted editorial
writing; the underlying events are facts and are not. So the panel shows the
headline and the year as a PROMPT, links out to the source, and the caption
says to write it in your own words -- the same instruction the headline panel
already carries.

    python -c "from letter import onthisday; print(onthisday.candidates())"
"""
from __future__ import annotations

import json
import re
import urllib.request
from datetime import date

UA = {"User-Agent": "Mozilla/5.0 (compatible; JSA-letter/1.0; +https://www.jpsi.com)"}

HISTORY_URL = "https://www.history.com/this-day-in-history/{month}-{day}"
WIKI_URL = ("https://api.wikimedia.org/feed/v1/wikipedia/en/onthisday/"
            "{kind}/{mm:02d}/{dd:02d}")

_MONTHS = ("january", "february", "march", "april", "may", "june", "july",
           "august", "september", "october", "november", "december")

# PREFIX STEMS, NO TRAILING BOUNDARY. \\bmurder\\b does not match "murdered",
# which is how the first version let four atrocities through. Deliberately
# broad: a false negative is a duller list, a false positive is grotesque.
_GRIM = re.compile(
    r"(kill|death|died|dead|dies|\bdie\b|fatal|massacr|genocid|murder|assassinat|"
    # THE WAR-AS-EVENT STEMS LEFT THIS PATTERN ON 2026-10-13 and became the
    # positive _WAR category below, at Ross's request: "can we just add
    # anything war related to the list of potential headlines". `\bwar\b`
    # alone was what dropped "1943 Italy declares war on Germany".
    #
    # WHAT STAYED IS THE WHOLE POINT. A declaration, a treaty, an armistice
    # or a landing is military history; a massacre is not, and neither is a
    # casualty count. Every atrocity and mass-death stem is still here and
    # still vetoes BEFORE any tag is considered, so the loosening admits
    # "Italy declares war on Germany" without admitting what Italy did.
    # `war crim`, NOT `war crime`. The first version wrote `war crime` and
    # "Nazi war criminals sentenced at Nuremberg" walked straight past it --
    # "crime" does not prefix "criminal", they part at the fourth letter.
    # That is the SAME trailing-stem mistake as \bmurder\b and `slaver`
    # recorded above, made a third time in the same file, and it was the
    # existing pick-list guard that caught it rather than any reasoning.
    r"execut|sentenc|suicide|bomb|shoot|shot|gunman|gunfire|stabb|war crim|"
    r"fires? on|fired on|open(ed|s)? fire|militant|ambush|"
    # EVERY ONE OF THESE WAS FOUND BY SWEEPING, not by thinking. After the
    # war tag went in, 3,202 events across a quarter of the calendar were
    # re-filtered and anything admitted that mentioned mass death in words
    # _GRIM did not know was read by hand. 535 were admitted; these are what
    # the remaining sixteen cost.
    #
    #   explosion     the Froberg mutiny "ended with the explosion of the
    #                 gunpowder magazine"
    #   sack of       the Fourth Crusade sacking Constantinople. `sack of`
    #                 and not `sack`, because a sacked quarterback is sport.
    #   exterminat    "the Imperial Japanese Army begins the systematic
    #                 extermination of perceived hostile elements"
    #   concentration camp
    #                 the Auschwitz death marches. The OTHER Auschwitz item
    #                 was already blocked, by `prison` -- which is exactly
    #                 how a stem list lulls you: one phrasing is caught and
    #                 the next is not.
    r"explosion|explod|sack of|exterminat|annihilat|pogrom|purge|"
    r"concentration camp|death march|"
    r"earthquake|tsunami|hurricane|"
    r"cyclone|flood|famine|plague|epidemic|pandemic|crash|derail|sank|sink|wreck|"
    r"disaster|collapse|destroy|terror|hostage|kidnap|riot|coup|overthrew|"
    r"overthrow|slaver|lynch|abuse|scandal|convict|prison|arrest|wound|injur|"
    r"casualt|victim|mauled|attack|assault|shelling|bombard|uprising|suppress|"
    r"\bcrisis\b|controvers|holocaust|segregat|desegregat|covid|virus|infect|"
    r"illness|disease|hospital|quarantin|outbreak|impeach|indict|resign|"
    # `slaver` matched "slavery" and NOT "slave law" or "enslaved", so
    # "The US enacts first fugitive slave law" passed every filter and
    # reached the February 12 pick list. Same trailing-stem mistake as the
    # original \bmurder\b. Found 2026-10-01 while spot-checking a second day,
    # which is the only reason it was found at all.
    r"slave|enslav|lynch|internment|massacre|atrocit)", re.I)

_SPORT = re.compile(
    r"\b(world series|super bowl|olympic\w*|baseball|football|basketball|hockey|"
    r"golf|tennis|boxing|nascar|kentucky derby|championship|pennant|home run|"
    r"homer|no-hitter|perfect game|nba|nfl|mlb|nhl|pga|u\.s\. open|world record|"
    r"gold medal|triple crown|heisman|heavyweight|pitcher|quarterback|"
    # Widened 2026-10-01. SOCCER IS DELIBERATELY ABSENT -- it was added with
    # these and Ross took it straight back out. This is a US cattle letter and
    # the sports that land are the American ones; Pele's farewell game is the
    # kind of item the omission is meant to drop. "world cup" goes with it.
    r"stanley cup|wimbledon|the masters|indy 500|grand slam|hall of fame|"
    r"batting|touchdown|pitched|ballpark|athlete)\b", re.I)

# MILITARY HISTORY AS ITS OWN REASON TO PRINT. Ross, 2026-10-13, after
# "1943 Italy declares war on Germany" failed to appear: war facts should be
# candidates in their own right, the way agriculture, sport and the
# presidency are, rather than needing to also be a US first.
#
# IT IS A POSITIVE TAG, NOT A HOLE IN THE FILTER. _GRIM still runs first and
# still vetoes everything about casualties, atrocities and mass death, so
# this admits declarations, treaties, armistices, landings, surrenders and
# the ordinary furniture of military history -- and cannot admit a massacre,
# a bombing or a body count, because those are matched before any tag is
# looked at.
#
# Where that line falls is worth stating plainly, because it is a judgement
# and not a fact: "Italy declares war on Germany" is in, "Japan attacks Pearl
# Harbor, killing 2,403" is out. The headline carries the death, so _GRIM
# takes it. Move `attack` or `kill` out of _GRIM if that is the wrong call --
# it is one stem either way, not a redesign.
_WAR = re.compile(
    r"\b(war|warfare|wartime|armistice|ceasefire|truce|treaty|surrender\w*|"
    r"allies|allied|axis|invad\w*|invasion|battle\w*|troops|regiment|"
    r"infantry|cavalry|artillery|garrison|siege|blockade|"
    r"d-day|normandy|vietnam|korea\w*|wehrmacht|luftwaffe|navy|naval|"
    r"army|marines|air force|veterans?|enlist\w*|conscript\w*|"
    r"versailles|yalta|potsdam|nato|confederate|redcoats|militia)\b", re.I)

_AG = re.compile(
    r"\b(farm\w*|ranch\w*|cattle|livestock|beef|corn|wheat|soybean\w*|harvest\w*|"
    r"agricultur\w*|homestead act|dust bowl|tractor|stockyard\w*|usda|"
    r"department of agriculture|grain|irrigation|rural)\b", re.I)

# "first" BUT NOT "first lady". That one matched a COVID diagnosis and offered
# it as a fun fact; the trailing negative lookahead is the whole fix.
#
# IT IS A MILESTONE LIST, NOT LITERALLY "first". Widened 2026-10-01 after the
# Model T being unveiled, Jimmy Carter being born and Johnny Carson's first
# Tonight Show all failed to register as anything. A thing being made, begun
# or born is the shape of a fun fact; "first" was only ever a proxy for it.
_FIRST = re.compile(
    r"\b(first(?! lady| famil| gentleman)|becomes? the first|opened?|opens|"
    r"founded|establish\w*|dedicat\w*|"
    r"patent\w*|inaugurat\w*|invent\w*|debut\w*|premiere\w*|record|"
    r"unveil\w*|\bborn\b|launch\w*|introduc\w*|christen\w*|"
    r"complete[sd]?|broadcast|televis\w*|took office)\b", re.I)

# AMERICAN-NESS IS USUALLY IN A PROPER NOUN, not in the word "American".
# Widened 2026-10-01 for the same three misses: "Ford Motor Company", "Jimmy
# Carter" and "Tonight Show" are each unmistakably American and none of them
# contained a single term this pattern knew.
#
# Presidents are listed by surname, but the ambiguous ones are deliberately
# LEFT OUT -- Grant, Bush, Pierce, Taylor, Arthur, Hayes, Polk and Tyler are
# ordinary English words and would tag half the list as American. The ones
# kept are distinctive enough to mean the person. A US tag is never sufficient
# on its own anyway: it still has to pair with a milestone.
_US = re.compile(
    r"\b(united states|american|u\.s\.|\bus\b|nasa|congress|president|"
    r"washington|new york|california|texas|chicago|wyoming|iowa|kansas|"
    r"nebraska|missouri|oklahoma|colorado|montana|dakota|mississippi|"
    r"boston|philadelphia|detroit|atlanta|seattle|denver|pittsburgh|"
    r"los angeles|san francisco|minnesota|michigan|ohio|indiana|illinois|"
    r"wisconsin|tennessee|kentucky|georgia|virginia|carolina|alabama|"
    r"arkansas|louisiana|arizona|nevada|utah|idaho|oregon|alaska|hawaii|"
    r"massachusetts|connecticut|pennsylvania|maryland|florida|"
    r"ford motor|model t|general motors|chevrolet|coca-cola|disney|"
    r"hollywood|broadway|tonight show|wall street|harvard|yale|smithsonian|"
    r"apollo|boeing|edison|wright brothers|statue of liberty|empire state|"
    r"golden gate|route 66|yellowstone|white house|supreme court|senate|"
    r"ellis island|world's fair|major league|super bowl)\b", re.I)

# EVERY PRESIDENT, AND THE PRESIDENCY ITSELF. Ross's call, 2026-10-01: a fact
# about a US president is worth printing on its own, not only when it also
# happens to be a "first". The surname list used to live inside _US and was
# half-length, because the ambiguous names were dropped to avoid noise.
#
# They are all here now, and the reason that is safe is that the cost of a
# FALSE positive here is tiny. _GRIM still runs first, so the worst a stray
# match can do is admit one more harmless piece of Americana -- which is
# roughly what this panel is for. A false NEGATIVE loses a fact Ross wanted.
#
# The eight surnames that are also ordinary English words -- Grant, Bush,
# Pierce, Taylor, Arthur, Hayes, Polk, Tyler -- still need a given name or
# the title, or "a research grant" and "the bush fire" would tag as
# presidential. Everything distinctive enough to mean the person stands alone.
_PRESIDENT = re.compile(
    r"\b(president\w*|white house|oval office|commander in chief|"
    r"state of the union|electoral college|inaugural address|"
    # distinctive enough on their own
    r"washington|jefferson|madison|monroe|van buren|fillmore|buchanan|"
    r"lincoln|garfield|mckinley|roosevelt|\btaft\b|harding|coolidge|"
    r"hoover|truman|eisenhower|kennedy|\bjfk\b|nixon|carter|reagan|obama|"
    r"biden|trump|clinton|"
    # ordinary words and big American place names: need the given name or the
    # title. Cleveland earned its place here -- "the city of Cleveland opens a
    # new bridge" tagged as presidential on the first run.
    r"grover cleveland|president cleveland|"
    r"woodrow wilson|president wilson|"
    r"ulysses s?\.? ?grant|general grant|"
    r"george w\.? bush|george h\.? ?w\.? bush|"
    r"franklin pierce|zachary taylor|chester a?\.? ?arthur|"
    r"rutherford b?\.? ?hayes|james k?\.? ?polk|john tyler|"
    r"benjamin harrison|william henry harrison|"
    r"andrew johnson|lyndon( b\.?)? johnson|\blbj\b|"
    r"andrew jackson|john( quincy)? adams)\b", re.I)


def _get(url: str, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def fetch_history_com(d: date) -> list:
    """
    (year, headline) from history.com's This Day in History.

    THE CLASS NAMES ARE BUILD-HASHED -- g1fwxflu, _15il2ffe -- and change on
    every deploy of theirs, so matching on them would break silently and
    without warning. The anchor is the year <span> paired with the heading's
    data-sentry-component attribute, which is framework-internal but survives
    a restyle. It WILL break eventually; candidates() says so out loud rather
    than returning an empty list that reads like a quiet day.

    robots.txt allows /this-day-in-history/ (only /private/ and /temp/ are
    disallowed), checked 2026-09-30.
    """
    html = _get(HISTORY_URL.format(month=_MONTHS[d.month - 1], day=d.day))
    pat = re.compile(
        r">(\d{4})\s*</span>.{0,400}?data-sentry-component=\"H3\">([^<]{6,160})</p>",
        re.S)
    out = []
    for year, title in pat.findall(html):
        out.append((int(year), re.sub(r"\s+", " ", title).strip()))
    return out


def fetch_wikipedia(d: date) -> list:
    """
    The same shape from Wikipedia's On This Day -- the fallback.

    Licensed for reuse and served by a real API, so it cannot break on a
    restyle. Rawer and grimmer than history.com, which is why it is second.
    """
    out = []
    for kind in ("selected", "events"):
        try:
            payload = json.loads(_get(WIKI_URL.format(kind=kind, mm=d.month, dd=d.day)))
        except Exception:
            continue
        for e in payload.get(kind) or []:
            text, year = (e.get("text") or "").strip(), e.get("year")
            if text and year:
                out.append((int(year), text))
    return out


def _tags(text: str) -> list:
    tags = []
    if _AG.search(text):
        tags.append("ag")
    if _SPORT.search(text):
        tags.append("sport")
    if _PRESIDENT.search(text):
        tags.append("pres")
    if _WAR.search(text):
        tags.append("war")
    if _US.search(text):
        tags.append("US")
    if _FIRST.search(text):
        tags.append("first")
    return tags


def _keep(text: str, tags: list) -> bool:
    if _GRIM.search(text):
        return False
    # POSITIVELY, OR NOT AT ALL. "American" on its own admitted Khashoggi and
    # Mogadishu; "first" on its own admitted Opus Dei and a Vancouver
    # cathedral. Agriculture, sport, the presidency and military history each
    # stand alone -- presidents by Ross's call on 2026-10-01 and war on
    # 2026-10-13, since a fact about either is worth printing whether or not
    # it is also a "first". Anything else still has to be a US first.
    #
    # Standing alone is safe for war for the same reason it is for the
    # presidency: _GRIM has already run. The tag cannot admit anything the
    # veto would have caught, so the worst a stray match does is offer one
    # more piece of military history.
    return bool(tags) and ("sport" in tags or "ag" in tags or "pres" in tags
                           or "war" in tags
                           or ("US" in tags and "first" in tags))


def candidates(when: date = None, limit: int = 8) -> dict:
    """
    {"items": [...], "errors": [...], "source_url": ...} for the pick list.

    Each item is {year, text, tags, source}. history.com first because it is
    better curated -- Babe Ruth's 60th homer, Cesar Chavez founding the
    National Farm Workers Association -- with Wikipedia behind it so a restyle
    degrades the panel rather than emptying it.
    """
    d = when or date.today()
    items, errors, seen = [], [], set()

    raw, source = [], "history.com"
    try:
        raw = fetch_history_com(d)
        if not raw:
            errors.append("history.com returned no events -- their page layout has "
                          "probably changed. Falling back to Wikipedia.")
    except Exception as e:                          # noqa: BLE001
        errors.append(f"history.com unreachable ({type(e).__name__}). "
                      "Falling back to Wikipedia.")

    if not raw:
        source = "Wikipedia"
        try:
            raw = fetch_wikipedia(d)
        except Exception as e:                      # noqa: BLE001
            errors.append(f"Wikipedia also unreachable ({type(e).__name__}).")

    for year, text in raw:
        # Dedupe on a stemmed prefix: the two feeds phrase the same event as
        # "NBC broadcast the first..." and "NBC broadcasts the first...".
        key = (year, " ".join(w.rstrip("s") for w in re.findall(r"[a-z]+", text.lower())[:8]))
        if key in seen:
            continue
        tags = _tags(text)
        if not _keep(text, tags):
            continue
        seen.add(key)
        # Presidents rank with sport, above a bare US item: they are their own
        # reason to print, and agriculture still outranks everything.
        weight = (3 if "ag" in tags else 0) + (2 if "sport" in tags else 0) \
            + (2 if "pres" in tags else 0) + (2 if "war" in tags else 0) \
            + (1 if "US" in tags else 0)
        items.append({"year": year, "text": text, "tags": tags,
                      "source": source, "_w": weight})

    # TWO SORTS, AND BOTH ARE NEEDED. The weight decides WHICH facts survive
    # the cut -- ag over sport over US -- so it has to run before the limit or
    # the panel fills with whatever happens to be most recent. The display
    # order is then chronological, NEWEST FIRST so the oldest sits at the
    # bottom, which is how Ross wants them reading down the letter. Sorting
    # by year before the cut would quietly change the selection, not just the
    # order.
    items.sort(key=lambda i: (-i["_w"], -i["year"]))
    chosen = items[:limit]
    chosen.sort(key=lambda i: -i["year"])
    for i in chosen:
        i.pop("_w", None)
    return {"items": chosen, "errors": errors,
            "source_url": HISTORY_URL.format(month=_MONTHS[d.month - 1], day=d.day)}
