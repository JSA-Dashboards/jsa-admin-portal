"""Live market data — manual per-contract price cards (ported from the HTML tool's
`buildMktStrip()`) plus the "Update prices from Massive" button that fills them in
automatically when Massive is configured.
"""
from datetime import datetime, timedelta
from typing import List, Tuple

import streamlit as st

from jsa_risk import state
from jsa_risk.data import audit_repo, reference_repo
from jsa_risk.pricing.commodities import CORN, CommoditySpec
from jsa_risk.pricing.stress import Position, effective_underlying_display, effective_underlying_key


def _distinct_contract_groups(positions: List[Position], commodity: CommoditySpec) -> List[Tuple[str, Position]]:
    """Dedupes by each position's *effective* underlying (its underlying_override if set,
    else the auto-derived one) -- so an Oct option and its Dec future collapse into one
    card, and an overridden position collapses into whatever it was overridden to, not
    whatever its symbol alone would auto-resolve to. Keeps a representative Position per
    group so the card can still show a proper decoded (and override-aware) name."""
    seen = set()
    groups: List[Tuple[str, Position]] = []
    for p in positions:
        key = effective_underlying_key(p, commodity=commodity)
        if key not in seen:
            seen.add(key)
            groups.append((key, p))
    return groups


def render_market_strip(positions: List[Position], commodity: CommoditySpec = CORN) -> None:
    groups = _distinct_contract_groups(positions, commodity)
    if not groups:
        st.caption("No contracts in the book to price.")
        return

    marks = state.get_contract_marks()
    cols = st.columns(min(len(groups), 4))
    for i, (key, rep_position) in enumerate(groups):
        display_name = (
            effective_underlying_display(rep_position, commodity=commodity) if rep_position.label
            else f"{commodity.name} futures (unlabeled)"
        )
        widget_key = f"mkt_price_{commodity.code}_{key}"
        if widget_key not in st.session_state:
            current = marks.get(key)
            st.session_state[widget_key] = float(current) if current is not None else commodity.default_price

        def _on_change(k=key, wk=widget_key):
            state.set_contract_price(k, st.session_state[wk], source="manual")

        with cols[i % len(cols)]:
            st.number_input(
                display_name, step=0.01, format="%.4f", key=widget_key, on_change=_on_change,
                help=f"$/{commodity.unit} — current mark ({key})",
            )


def render_massive_refresh(positions: List[Position], commodity: CommoditySpec = CORN) -> None:
    """Button + status, stacked (not side-by-side columns) so this renders cleanly
    whether called full-width or wrapped in an external column, e.g. alongside
    render_iv_refresh on the dashboard."""
    from jsa_risk.config import get_massive_config
    from jsa_risk.integrations import massive_client

    config = get_massive_config()
    canon_keys = sorted({effective_underlying_key(p, commodity=commodity) for p in positions})

    from jsa_risk.pricing.market_hours import market_is_open, now_central
    use_settlement = not market_is_open(commodity)

    clicked = st.button("↻ Update prices from Massive", disabled=config is None)

    if config is None:
        st.caption("Massive isn't configured — add a [massive] block to .streamlit/secrets.toml to enable live prices.")
    elif clicked:
        with st.spinner(f"Fetching {', '.join(canon_keys) or 'nothing'} from Massive…"):
            try:
                result = massive_client.fetch_futures_prices(
                    config, canon_keys, commodity.code, use_settlement=use_settlement,
                    price_divisor=commodity.price_divisor)
            except Exception as e:
                audit_repo.log_fetch("massive", "/futures/v1/snapshot", success=False, error_message=str(e))
                st.error(f"Couldn't fetch from Massive: {e}")
            else:
                from jsa_risk.integrations.massive_client import BASIS_SETTLE
                for key, price in result.updated.items():
                    source = "massive settlement" if result.basis.get(key) == BASIS_SETTLE else "massive"
                    state.set_contract_price(key, price, source=source)
                    st.session_state.pop(f"mkt_price_{commodity.code}_{key}", None)  # let the card re-seed from the fresh mark
                audit_repo.log_fetch("massive", "/futures/v1/snapshot", success=True, http_status=200)
                if result.updated:
                    delay_note = (
                        " (~10 min delayed)" if result.timeframe == "DELAYED"
                        else (f" ({result.timeframe.lower()})" if result.timeframe else "")
                    )
                    updated_str = ", ".join(f"{k} ${v:.4f}" for k, v in result.updated.items())
                    settled = [k for k in result.updated if result.basis.get(k) == BASIS_SETTLE]
                    if use_settlement:
                        delay_note = " (settlement prices — market closed)"
                        missing = [k for k in result.updated if k not in settled]
                        if missing:
                            delay_note = (f" (settlement where posted; {', '.join(missing)} had none yet, "
                                          "so last trade)")
                    else:
                        delay_note = delay_note.replace("(", "(last trade — market open, ", 1) if delay_note else                             " (last trade — market open)"
                    # Rerun so the KPIs/Greeks/charts above this section (already rendered
                    # earlier in this same script pass, off the pre-update cached prices)
                    # pick up the fresh marks too -- stash the message since a message shown
                    # right before rerun() never reaches the user.
                    st.session_state["_flash_market_update"] = (
                        f"Updated {len(result.updated)} contract price(s) from Massive{delay_note}: {updated_str}."
                    )
                    st.rerun()
                else:
                    st.warning("No matching contracts returned from Massive.")
    now = now_central()
    st.caption(
        ("Market is closed — the button pulls each contract's official settlement."
         if use_settlement else
         "Market is open — the button pulls the last trade, delayed ~10 minutes (not an executable quote).")
        + f" ({now:%a %H:%M} Central)"
    )


def render_iv_refresh(positions: List[Position], commodity: CommoditySpec = CORN) -> None:
    """Re-pulls each option position's implied vol from IV_SNAPSHOT -- this commodity's
    CME DataMine feed sitting in Snowflake (see scripts/refresh_iv_from_cme.py, run daily
    by .github/workflows/refresh-iv.yml) -- so Greeks recompute against the latest
    settlement vol, the same way "Update prices from Massive" refreshes the futures mark
    Greeks are priced against. Futures carry no IV and are skipped; a position whose
    underlying has no snapshot row yet is left untouched rather than silently overwritten
    with the generic no-data-yet default (reference_repo.DEFAULT_IV)."""
    option_positions = [p for p in positions if p.type != "future"]
    snapshot = {row["key"]: row["iv"] for row in state.get_iv_provenance()}

    clicked = st.button("↻ Update Greeks from CME", disabled=not option_positions)

    if not option_positions:
        st.caption("No option positions in the book to update.")
    elif clicked:
        touched_keys = set()
        missing_keys = set()
        for p in option_positions:
            key = effective_underlying_key(p, commodity=commodity)
            if key not in snapshot:
                missing_keys.add(key)
                continue
            state.update_position_field(p.id, "IV", snapshot[key])
            state.update_position_field(p.id, "IV_ESTIMATED", True)
            touched_keys.add(key)

        if touched_keys:
            updated_str = ", ".join(f"{k} {snapshot[k]:.2f}%" for k in sorted(touched_keys))
            msg = f"Updated implied vol for {len(touched_keys)} contract(s) from the CME snapshot: {updated_str}."
            if missing_keys:
                msg += f" No CME data yet for {', '.join(sorted(missing_keys))} — left as-is."
            # Same reason as the Massive flow: rerun so everything above (already rendered
            # off the pre-update IV) recomputes Greeks from the fresh values.
            st.session_state["_flash_iv_update"] = msg
            st.rerun()
        else:
            st.warning(f"No CME snapshot data yet for any of this book's contracts ({', '.join(sorted(missing_keys))}).")
    st.caption(
        "Pulls each contract's latest settlement vol from CME DataMine (refreshed daily, "
        "or on demand via GitHub Actions → Run workflow) — one value per underlying, "
        "shared across its options."
    )


# The futures mark is the one input EVERY greek is priced off, and the only one with no
# schedule behind it: it moves when somebody presses the Massive button and not otherwise.
# So its age is stated unconditionally, not just when it crosses a threshold -- the fault
# this exists for was silent, and a caption that only appears when something is wrong
# cannot be checked at a glance when you are wondering whether anything IS wrong.
#
# Staleness is counted in SESSIONS rather than days: Friday's mark read on Monday morning
# is ~2.8 days old by the clock and is still the most recent settle there has been. Two
# sessions of slack also absorbs a single exchange holiday, which this does not model --
# there is no holiday calendar here and nothing that needs one at this tolerance.
MARK_STALE_AFTER_SESSIONS = 2


def sessions_since(then, now) -> int:
    """Weekdays strictly after `then`'s date, up to and including `now`'s -- i.e. how many
    trading sessions have had the chance to move this price since it was written.

    Weekdays, not days: the question is how many chances the market has had, and a
    calendar-day count calls every Monday stale and never catches a Tuesday-to-Thursday
    gap. Holidays are not modelled, which can overstate this by one; the threshold is set
    wide enough to absorb that rather than carrying a calendar that would need upkeep."""
    a, b = then.date(), now.date()
    if b <= a:
        return 0
    return sum(1 for i in range(1, (b - a).days + 1)
               if (a + timedelta(days=i)).weekday() < 5)


def summarize_mark_provenance(rows, in_book, now,
                              stale_after_sessions=MARK_STALE_AFTER_SESSIONS) -> dict:
    """Pure half of render_mark_provenance, so the staleness rules are testable without
    Streamlit. Returns {caption, warning, behind}; warning is None when marks are fresh."""
    if not rows:
        return {"caption": None, "warning": None, "behind": []}

    dated = [r for r in rows if r.get("updated_at") is not None]
    newest = max((r["updated_at"] for r in dated), default=None)
    source = next((r["source"] for r in rows if r.get("source")), "")

    # Label and source are ONE bit, matching the IV caption's "**Implied vol:** family" --
    # as two they render "**Futures marks:** · massive", with a separator between a
    # label and the thing it labels.
    bits = [f"**Futures marks:** {source or 'unknown source'}"]
    if newest is not None:
        behind_n = sessions_since(newest, now)
        age = (f"updated {newest:%Y-%m-%d %H:%M}"
               + ("" if behind_n == 0 else f" - {behind_n} session(s) ago"))
        bits.append(age)
    else:
        bits.append("never updated")
    bits.append(f"{len(rows)} contract(s)")

    warning = None
    if newest is None:
        warning = ("Futures marks carry no update time, so their age cannot be checked - "
                   "every greek on this page is priced off them.")
    else:
        behind_n = sessions_since(newest, now)
        if behind_n > stale_after_sessions:
            warning = (
                f"Futures marks are {behind_n} sessions old (newest {newest:%Y-%m-%d %H:%M}). "
                f"Press ↻ Update prices from Massive - the blotter still moves off each "
                f"leg's own last tick, but the greeks, the scenario heatmap and Net Position "
                f"are all priced off this mark and will not."
            )

    # One contract lagging the rest is the case that actually misprices a position: it is
    # a normal-looking number in the blotter with nothing to mark it out, and the headline
    # age above stays reassuring because some OTHER contract was refreshed recently.
    behind = []
    if newest is not None and in_book:
        behind = sorted(
            r["key"] for r in rows
            if r["key"] in in_book
            and (r.get("updated_at") is None
                 or sessions_since(r["updated_at"], newest) > stale_after_sessions)
        )
    return {"caption": " · ".join(bits), "warning": warning, "behind": behind}


def render_mark_provenance(positions: List[Position], commodity: CommoditySpec = CORN) -> None:
    """One line saying where the futures marks came from and how old they are."""
    try:
        rows = state.get_contract_mark_provenance()
    except Exception:
        return                                   # never break the dashboard over a caption
    if not rows:
        st.caption("Futures marks: no rows - contracts fall back to the commodity default.")
        return

    in_book = {effective_underlying_key(p, commodity=commodity) for p in positions}
    summary = summarize_mark_provenance(rows, in_book, datetime.now())
    if summary["caption"]:
        st.caption(summary["caption"])
    if summary["warning"]:
        st.warning(summary["warning"])
    if summary["behind"]:
        st.warning(
            "These contracts in your book are marked older than the rest: "
            + ", ".join(summary["behind"])
        )


# Vols come from a scheduled refresh, not from anything the viewer can see happening, so
# the dashboard states their age. STALE_AFTER_DAYS is deliberately short: corn settlement
# vols are published every trading day, so anything older than a long weekend means the
# refresh has stopped rather than the market being quiet.
STALE_AFTER_DAYS = 4


def summarize_iv_provenance(rows, in_book, now, stale_after_days=STALE_AFTER_DAYS) -> dict:
    """Pure half of render_iv_provenance, so the staleness rules are testable without
    Streamlit. Returns {caption, warning, behind}; warning is None when vols are fresh."""
    if not rows:
        return {"caption": None, "warning": None, "behind": []}

    dated = [r for r in rows if r.get("as_of") is not None]
    newest = max((r["as_of"] for r in dated), default=None)
    source = next((r["source"] for r in rows if r.get("source")), "")
    family = (source.split(" ATM")[0].split(" (")[0] or "unknown source").strip()

    bits = [f"**Implied vol:** {family}"]
    if newest is not None:
        bits.append(f"settled {newest:%Y-%m-%d}")
    bits.append(f"{len(rows)} contract(s)")

    warning = None
    if newest is not None:
        age = (now - newest).days
        if age > stale_after_days:
            warning = (f"Implied vols are {age} days old (newest settlement "
                       f"{newest:%Y-%m-%d}). Run scripts/refresh_iv_from_cme.py - "
                       f"positions are being priced off stale vol.")

    # A single contract lagging the rest is the case that actually misprices a position:
    # it looks like a normal number in the blotter with nothing to mark it out.
    behind = []
    if newest is not None and in_book:
        behind = sorted(
            r["key"] for r in rows
            if r["key"] in in_book
            and (r.get("as_of") is None or (newest - r["as_of"]).days > stale_after_days)
        )
    return {"caption": " · ".join(bits), "warning": warning, "behind": behind}


def render_iv_provenance(positions: List[Position], commodity: CommoditySpec = CORN) -> None:
    """One line saying where the implied vols came from and how old they are."""
    try:
        rows = state.get_iv_provenance()
    except Exception:
        return                                   # never break the dashboard over a caption
    if not rows:
        st.caption(f"Implied vol: no snapshot rows - positions fall back to "
                   f"{reference_repo.DEFAULT_IV:.0f}%.")
        return

    in_book = {effective_underlying_key(p, commodity=commodity) for p in positions}
    summary = summarize_iv_provenance(rows, in_book, datetime.now())
    if summary["caption"]:
        st.caption(summary["caption"])
    if summary["warning"]:
        st.warning(summary["warning"], icon=":material/warning:")
    if summary["behind"]:
        st.caption(f"Older than the rest, and in your book: {', '.join(summary['behind'])}")
