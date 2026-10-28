"""
Client view vs staff view — one question, asked in one place.

A client opens the portal to read the market. Everything this portal grew to
answer a BUILD question — the method tabs, the raw Data tabs, the audit
captions, the forecast that grades its own accuracy — is noise to them and
costs the attention the headline needs. `is_client()` is the one question that
decides, the way `portal_auth.is_admin()` is the one question that decides who
sees the letter tool.

THE MODE IS STRUCTURAL, NOT A SECRET, AND THAT IS THE WHOLE SAFETY OF IT.
Streamlit Cloud takes a main file path per deployment, so the client app points
at `Client.py` and the staff app stays on `Home.py`. There is no PORTAL_VIEW
secret to forget on a redeploy, and therefore no way for a client deployment to
come up silently serving the analyst view — which a missing secret would do,
because absence has to mean "staff" or the existing deployment would strip
itself the first time it rebooted.

The two run the SAME `Home.py` and the same fifteen pages. Client.py sets the
flag and executes the shell; it is six lines and holds no layout of its own, so
there is nothing here to drift the way `snowflake_db.py` drifted five ways.

WHAT THE CLIENT VIEW HIDES, which is a standing rule rather than a list:

  1. Tabs that are a working tool rather than a market reading — the Monday
     print forecast and its scorecard, packer leverage, the spread matrix,
     state-by-state comparisons.
  2. Raw `Data` tabs and the download panels under them.
  3. Method and audit furniture — "How this is built" tabs, "Technical
     details" expanders, reconciliation banners, provenance captions.

It does NOT hide the two crush calculators' "How this is calculated"
explainers. Those are not provenance; a margin a reader cannot take apart is
one they will not trust, and trust is the point of showing them at all.

THREE WAYS TO USE IT:

    # a tab the client does not get -- same arity, so the unpacking is unchanged
    tab_a, tab_b = portal_view.tabs(["Prices", "How this is built"],
                             hide={"How this is built"})

    # a body that is not already behind `if tab.open:`
    if portal_view.shown(tab_b):
        with tab_b:
            ...

    # a control the client does not need, and the value it would have chosen
    unit = portal_view.pick("Dressed Weight",
                     lambda: st.sidebar.radio("Weight basis", UNITS))

A HIDDEN TAB'S BODY MUST NOT RUN. A hidden Streamlit tab is hidden, not
skipped — the rule recorded in CLAUDE.md — which is why `tabs()` removes the
label outright and hands back a stand-in rather than rendering the tab and
styling it away. The stand-in is a no-op context manager with `open = False`,
so a page already written as `with tab: if tab.open:` needs no change at all
and the body's fetches never fire. `shown()` is for the pages written without
that guard, where adding `on_change="rerun"` to get `.open` would ALSO make
every sibling tab lazy — and the two crush pages depend on a hidden sibling
executing, which is exactly the trap this module must not spring.
"""
from __future__ import annotations

from typing import Any, Callable, Iterable, Sequence, TypeVar

import streamlit as st

T = TypeVar("T")

# A module global, not session state. Client.py sets it at the top of every
# rerun before anything renders, and session state would be the wrong home:
# this is a property of the DEPLOYMENT, not of the person looking at it, so a
# reader must not be able to carry it between the two apps or clear it.
_CLIENT = False


def set_client(value: bool = True) -> None:
    """Pin this run to the client view. Called by Client.py and by tests."""
    global _CLIENT
    _CLIENT = bool(value)


def is_client() -> bool:
    """The one question."""
    return _CLIENT


def is_staff() -> bool:
    return not _CLIENT


class Hidden:
    """
    Stand-in for a tab the client does not get.

    `open` is False so `if tab.open:` — the guard five pages already use —
    skips the body and its fetches with no edit to those pages. It is a plain
    attribute rather than Streamlit's, which matters: a real TabContainer's
    `.open` is None unless `on_change="rerun"` was passed, and None is falsy,
    so a page that does NOT pass it must use `shown()` instead or the staff
    view would skip the body too.
    """

    open = False

    def __enter__(self) -> "Hidden":
        return self

    def __exit__(self, *exc: Any) -> bool:
        return False

    def __repr__(self) -> str:  # pragma: no cover - debugging only
        return "<portal_view.Hidden tab>"


def shown(tab: Any) -> bool:
    """True unless `tab` is the stand-in for one hidden from the client."""
    return not isinstance(tab, Hidden)


def tabs(labels: Sequence[str], *, hide: Iterable[str] = (), **kwargs: Any):
    """
    `st.tabs`, with `hide` dropped for the client.

    Returns one object per label, in the caller's order, so the unpacking at
    the call site never changes — hidden positions get `Hidden()`. In the staff
    view it is `st.tabs` and nothing else, so a page's behaviour there is
    untouched including whether its tabs are lazy.
    """
    labels = list(labels)
    if not is_client():
        return st.tabs(labels, **kwargs)

    drop = set(hide)
    unknown = drop - set(labels)
    if unknown:
        # A label renamed on the page and not here would silently stop hiding
        # its tab, and the client would simply get the analyst tool back with
        # nothing raising. Loud, because nothing downstream can report it.
        raise ValueError(
            f"portal_view.tabs: hide names labels that are not on this tab set: "
            f"{sorted(unknown)}"
        )

    keep = [label for label in labels if label not in drop]
    if not keep:
        return tuple(Hidden() for _ in labels)

    real = iter(st.tabs(keep, **kwargs))
    return tuple(Hidden() if label in drop else next(real) for label in labels)


def options(all_options: Sequence[T], *, hide: Iterable[T] = ()) -> list[T]:
    """
    The choices for a `st.segmented_control`, with `hide` dropped for a client.

    The caller still decides what to do with one remaining choice — usually
    not drawing the control at all, since a switch with nothing to switch to
    reads as a broken one.
    """
    if not is_client():
        return list(all_options)
    drop = set(hide)
    return [o for o in all_options if o not in drop]


def pick(default: T, build: Callable[[], T]) -> T:
    """
    A control the client does not need, and the value it would have chosen.

    The widget is not rendered for a client and `default` is returned, so the
    chart below it draws exactly as it would have on the staff view's opening
    state. Passing a callable rather than the widget's return value is what
    stops the widget rendering at all — Streamlit draws on call, so evaluating
    it to pass it in would put it on the client's page.
    """
    return default if is_client() else build()


def staff_only(render: Callable[[], None]) -> None:
    """Run `render` on the staff view and not for a client."""
    if not is_client():
        render()


def staff_block() -> Iterable[None]:
    """
    A block the client does not get, with no re-indentation at the call site:

        for _ in portal_view.staff_block():
            st.dataframe(raw)

    WHY A `for` AND NOT AN `if`. Most of what comes out of these pages is
    already written as `with st.expander(...):`, and there is no way to make a
    context manager skip its own body — `__enter__` cannot decline. The two
    honest options are to re-indent every such block under an `if`, or this.
    Re-indenting won: this repo has already shipped a CSS block that ended up
    inside a comment and a `<style>` that ended itself, both from moving code
    that contained a multi-line string, so a mechanical pass over twenty blocks
    is the riskier of the two. A generator that yields once or not at all skips
    the body outright — the fetches inside it never fire and nothing reaches
    the DOM for a reader to find in view-source.
    """
    if not is_client():
        yield


def staff_expander(label: str, **kwargs: Any) -> Iterable[None]:
    """
    `st.expander`, for staff only, as a drop-in for `with st.expander(...)`:

        for _ in portal_view.staff_expander("📋  Data Table"):
            st.dataframe(raw)

    The expander and its body are drawn for staff exactly as before. For a
    client neither exists — not drawn, not computed, not in the page source.
    """
    if is_client():
        return
    with st.expander(label, **kwargs):
        yield
