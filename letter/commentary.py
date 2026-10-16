"""
The parts of the letter that stay Ross's: Market Action, the technical read and
the Fundamental Rundown.

These live in a plain markdown file per issue, one "## " heading per section,
bullets as "- ". The builder writes the file with the headings already in place
and the computed figures quoted underneath as HTML comments, so the numbers you
are writing about are in front of you while you write, and re-running the build
picks up whatever you saved without re-fetching anything.

An HTML comment is used for the hints on purpose: they are visible while editing
and cannot reach the rendered letter even if left in place.
"""
from __future__ import annotations

import re
from pathlib import Path

# Order matters -- this is the order the sections appear in each letter.
#
# The two letters do NOT share a section list. Friday replaces Market Action
# with Key Headlines, drops the Fundamental Rundown, and adds a Cash Trade Recap
# plus a Cattle on Feed note that is only used on release weeks. The technicals
# keys are shared on purpose, so a technical read typed for one carries the same
# meaning in the other.
SECTIONS_BY_KIND = {
    "tuesday": [
        # Added 2026-09-23. Headlines LEAD the evening letter, the way Key
        # Headlines lead Friday's and Headlines lead the morning brief -- all
        # three now open on what happened before they explain it.
        #
        # THE KEY IS "headlines", the same one the AM brief uses, on the same
        # reasoning as the shared technicals keys below: the section means the
        # same thing in both letters, so a headline typed into the morning box
        # reads correctly if it is carried into the evening one. The drafts are
        # still separate files per kind, so nothing is shared by accident.
        ("headlines", "Headlines"),
        ("market_action", "Market Action"),
        ("technicals_lc", "Technicals: Live Cattle"),
        ("technicals_fc", "Technicals: Feeder Cattle"),
        ("fundamental", "Fundamental Rundown"),
        # LAST, and on every evening letter. Ross's catch-all: whatever the
        # named sections do not cover. Placed above the sign-off rather than
        # below the rundown literally, because the three formats end with
        # different blocks -- Friday's rundown sits mid-letter -- and "the last
        # thing before Have a good evening" is the same position in all three.
        #
        # NOT on the morning brief: that is one page and under three minutes,
        # and a free-text catch-all is the easiest way to lose the budget.
        ("comments", "Comments"),
    ],
    # The morning brief has ONE written section. Everything else on the page is
    # fetched, and the whole thing is meant to be read in under three minutes --
    # a second commentary slot is the easiest way to lose that.
    #
    # Border status lives HERE by choice, not automation: a line that says the
    # same thing for three weeks stops being read, so it appears when it is news
    # and not otherwise.
    "am": [
        ("headlines", "Headlines"),
    ],
    # Tue/Wed/Thu. The session, briefly.
    #
    # ONE TECHNICALS SECTION PER PRODUCT, the same as the full letter and the
    # Friday one -- changed 2026-10-15 at Ross's request. It carried a single
    # "technicals" key until then, and two things followed from that which were
    # not obvious until he asked why Thursday looked different:
    #
    #   The heading. render.technicals_block prints "<month> <product>" --
    #   "Feb Live Cattle" -- and returns NOTHING when that product has no
    #   written bullets of its own. One combined read therefore had no headings
    #   to sit under and printed under a bare "Technicals", while Monday and
    #   Friday named the contract. On a week when the front month rolls, which
    #   contract the read is about is the first thing a reader needs.
    #
    #   THE FIGURES NEVER REACHED THE DRAFT, which is the one that mattered.
    #   build.hints writes the close, the 9-day, the 20-day and the swing
    #   high/low into slots named technicals_lc and technicals_fc, and its
    #   add() skips a slot the format does not have -- so Tue/Wed/Thu drafts
    #   carried an EMPTY figure block, measured 2026-10-15: 0 hint lines
    #   against 6 per product on Monday. That silently included the "DO NOT
    #   QUOTE, the series has a hole" warning, which 0435450 moved into the
    #   draft precisely because a wrong average restated in Ross's own prose
    #   carries no [[?]]. Exactly the kind="am" failure described in hints()
    #   itself, repeated on a second format.
    #
    # The recap is still the lighter letter: no Fundamental Rundown, and the
    # cash block is the week to date rather than last week's weighted average.
    # Two technicals boxes is what it costs to name the contracts.
    "recap": [
        ("headlines", "Headlines"),
        ("market_action", "Market Action"),
        ("technicals_lc", "Technicals: Live Cattle"),
        ("technicals_fc", "Technicals: Feeder Cattle"),
        # LAST, and on every evening letter. Ross's catch-all: whatever the
        # named sections do not cover. Placed above the sign-off rather than
        # below the rundown literally, because the three formats end with
        # different blocks -- Friday's rundown sits mid-letter -- and "the last
        # thing before Have a good evening" is the same position in all three.
        #
        # NOT on the morning brief: that is one page and under three minutes,
        # and a free-text catch-all is the easiest way to lose the budget.
        ("comments", "Comments"),
    ],
    "friday": [
        ("key_headlines", "Key Headlines"),
        ("technicals_lc", "Technicals: Live Cattle"),
        ("technicals_fc", "Technicals: Feeder Cattle"),
        ("cash_recap", "Cash Trade Recap"),
        ("cof_note", "Cattle on Feed Commentary"),
        # LAST, and on every evening letter. Ross's catch-all: whatever the
        # named sections do not cover. Placed above the sign-off rather than
        # below the rundown literally, because the three formats end with
        # different blocks -- Friday's rundown sits mid-letter -- and "the last
        # thing before Have a good evening" is the same position in all three.
        #
        # NOT on the morning brief: that is one page and under three minutes,
        # and a free-text catch-all is the easiest way to lose the budget.
        ("comments", "Comments"),
    ],
}

# Back-compatible alias. Callers that predate the Friday letter get Tuesday's.
SECTIONS = SECTIONS_BY_KIND["tuesday"]


def sections_for(kind: str = "tuesday") -> list:
    return SECTIONS_BY_KIND[kind]


_COUNT_WORDS = {1: "one", 2: "two", 3: "three", 4: "four",
                5: "five", 6: "six", 7: "seven"}


def sections_summary(kind: str = "tuesday") -> str:
    """
    "one written section (Headlines)" -- COUNTED AND NAMED FROM SECTIONS_BY_KIND.

    For the authoring page's captions, and derived for the same reason
    config.pm_format_summary() is: a caption that states what a format contains
    goes stale the first time a section moves, and nothing makes it fail. The
    evening letter gained a Headlines section on 2026-09-23 and the morning
    brief is one section by design -- count them here, do not type them out.
    """
    labels = [label for _key, label in sections_for(kind)]
    n = _COUNT_WORDS.get(len(labels), str(len(labels)))
    noun = "section" if len(labels) == 1 else "sections"
    return f"{n} written {noun} ({', '.join(labels)})"

_HEADING = re.compile(r"^##\s+(.*?)\s*$", re.MULTILINE)

# A heading a format USED to carry, and where its text goes now.
#
# Sections are matched on heading text and an unrecognised heading is ignored,
# so renaming one makes every draft already written under the old name vanish
# from the page and from the letter with no error -- the quiet loss that
# JSA.LETTER.DRAFTS exists to stop, arriving by a different route. The recap's
# "## Technicals" became two headings on 2026-10-15 while Ross was part way
# through that evening's letter.
#
# The carry-over fires ONLY when neither new heading is in the file, so it
# retires itself: the first save writes both and this can never fire again on
# that draft. The text lands under Live Cattle rather than being split, because
# no rule can tell which bullet is about which product -- it is visible and
# editable there, and visible-and-mislabelled beats silently gone.
LEGACY_SECTION = {
    "recap": {
        "heading": "Technicals",
        "into": "technicals_lc",
        "replaced_by": ("Technicals: Live Cattle", "Technicals: Feeder Cattle"),
    },
}


def path_for(out_dir: Path, issue_date, kind: str = "tuesday") -> Path:
    """One draft per letter per day. The kind is in the NAME because the two
    letters have different sections -- a Tuesday draft read as Friday would
    silently drop Key Headlines and the Cash Trade Recap."""
    return Path(out_dir) / f"commentary_{kind}_{issue_date}.md"


def _hint_block(lines: list[str]) -> str:
    if not lines:
        return ""
    body = "\n".join(f"  {ln}" for ln in lines)
    return f"<!-- computed for reference, not printed:\n{body}\n-->\n\n"


def write_template(path: Path, hints: dict, kind: str = "tuesday") -> None:
    """
    Create the editable file. Never overwrites: an existing file is your draft.
    """
    if path.exists():
        return
    parts = [
        "<!-- Your sections. Bullets as '- '. Blank sections are skipped in the",
        "     rendered letter, so you can drop one by leaving it empty. -->",
        "",
    ]
    for key, title in sections_for(kind):
        parts.append(f"## {title}")
        parts.append("")
        block = _hint_block(hints.get(key, []))
        if block:
            parts.append(block.rstrip("\n"))
            parts.append("")
        parts.append("- ")
        parts.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def read(path: Path, kind: str = "tuesday") -> dict:
    """
    Parse the markdown back into {key: [bullet, ...]}.

    The file handling only -- parse() does the reading, so the page's
    "has this been written in yet?" test cannot drift from what the letter
    actually renders.
    """
    if not path.exists():
        return {key: [] for key, _ in sections_for(kind)}
    return parse(path.read_text(encoding="utf-8"), kind)


def has_content(text: str, kind: str = "tuesday") -> bool:
    """
    Does this markdown carry any actual writing?

    Written for draft_store.restore(), which otherwise cannot tell a finished
    letter from the file write_template() just created: both are a few hundred
    bytes of headings. On 2026-09-28 that difference mattered -- opening the
    deployed page without typing pushed a template up, and it was NEWER than a
    real draft sitting on the desktop, so the newest-wins rule would have
    replaced real writing with empty headings.

    Parses rather than checking length: the template's bare "- " placeholder
    and the HTML comment header are exactly what read() already knows to
    discard, and duplicating that judgement here would let the two disagree.
    """
    return any(parse(text, kind).values())


def parse(text: str, kind: str = "tuesday") -> dict:
    """
    read(), over a string. read() is this plus the file handling.

    Sections are matched on their HEADING TEXT, so reordering them in the file
    is harmless and an unrecognised heading is ignored rather than guessed at.
    """
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.DOTALL)
    by_title = {}
    matches = list(_HEADING.finditer(text))
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        by_title[m.group(1).strip().lower()] = text[m.end():end]

    def _bullets(block: str) -> list:
        bullets = []
        for line in block.splitlines():
            line = line.strip()
            # The template seeds each section with a bare "- ". An untouched one
            # must not reach the letter as an empty bullet.
            if not line or line in ("-", "*"):
                continue
            # "- x" and "  - x" (a sub-bullet, kept with its indent intact so the
            # renderer can nest it the way Word's "o" level did).
            m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
            if m and m.group(2).strip():
                bullets.append(m.group(2).strip())
            elif not line.startswith("#"):
                bullets.append(line)
        return bullets

    out = {key: _bullets(by_title.get(title.lower(), ""))
           for key, title in sections_for(kind)}

    # A draft written before this format's headings were renamed. See
    # LEGACY_SECTION -- it fires only while no new heading is present.
    spec = LEGACY_SECTION.get(kind)
    if spec and spec["heading"].lower() in by_title:
        if not any(t.lower() in by_title for t in spec["replaced_by"]):
            out[spec["into"]] = _bullets(by_title[spec["heading"].lower()])
    return out


def write_sections(path: Path, sections: dict, kind: str = "tuesday") -> None:
    """
    Write {key: [bullet, ...]} back out in the same format read() parses.

    The JSA Daily Cattle Reports page edits in text areas; the CLI edits the file.
    Both must leave the file in one format or a letter half-written in one place
    cannot be finished in the other.
    """
    parts = []
    for key, title in sections_for(kind):
        parts.append(f"## {title}")
        parts.append("")
        for bullet in sections.get(key, []):
            text = str(bullet).strip()
            if text:
                parts.append(f"- {text}")
        parts.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(parts), encoding="utf-8")


def is_empty(sections: dict) -> bool:
    return not any(v for v in sections.values())
