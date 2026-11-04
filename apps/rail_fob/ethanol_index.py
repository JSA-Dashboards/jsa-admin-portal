"""
State ethanol index bid (Kolten, 2026-11-02: "add in a column for the state ethanol index bid to benchmark against ... get this from the
Basis Tracker on the summary page").

The Basis Tracker's `Corn Processing` locations (its ethanol plants and corn processors, the category its Trends tab calls "Corn Processing -
Corn") carry each plant's corn bids as snapshots in JSA.BASIS_TRACKER. A state's index for a delivery month is the simple average of the
plants' basis for it (cents vs the futures month each bid is tagged to, the same unit as the rail corridors' bids), read from each plant's
LATEST snapshot within the last 10 days. Pure functions plus the one SQL string; the caller runs it (rail_data._sf_rows) and caches.
"""
import delivery_period as DP

LOOKBACK_DAYS = 10

SQL = """
WITH latest AS (
  SELECT s.id, s.provider, s.location, s.timestamp,
         ROW_NUMBER() OVER (PARTITION BY s.provider, s.location ORDER BY s.timestamp DESC) AS rn
  FROM snapshots s
  JOIN location_meta lm ON lm.provider = s.provider AND lm.location = s.location
  WHERE lm.facility_type = 'Corn Processing' AND s.timestamp >= %s
)
SELECT l.provider, l.location, lm.state, r.grain, r.delivery_month, r.futures_symbol, r.basis_cents, r.is_spot
FROM latest l
JOIN location_meta lm ON lm.provider = l.provider AND lm.location = l.location
JOIN snapshot_rows r ON r.snapshot_id = l.id
WHERE l.rn = 1 AND r.basis_cents IS NOT NULL
"""


def state_index(rows):
    """{state: {(year, month): (average basis in cents, number of plants)}} from the SQL's rows: corn only, forward (non-spot) bids,
    a plant counted once per delivery month (its bids for the month are averaged first, so a plant with two bids doesn't weigh double)."""
    per_plant = {}
    for r in rows:
        if not str(r["grain"]).lower().startswith("corn") or r.get("is_spot") or not r.get("state"):
            continue
        ym = DP.canonical(r["delivery_month"], r["futures_symbol"])
        if not ym:
            continue
        per_plant.setdefault((r["state"], ym, r["provider"], r["location"]), []).append(r["basis_cents"])
    by_state = {}
    for (state, ym, _p, _l), vals in per_plant.items():
        by_state.setdefault((state, ym), []).append(sum(vals) / len(vals))
    out = {}
    for (state, ym), plants in by_state.items():
        out.setdefault(state, {})[ym] = (sum(plants) / len(plants), len(plants))
    return out


def lookup(index, state, month, today):
    """The state's (average basis, plants) for the next occurrence of `month` (1-12) on or after today's month, or None."""
    year = today.year if month >= today.month else today.year + 1
    return (index.get(state) or {}).get((year, month))


# ---- per-location series for the State Level tab (Kolten, 2026-11-03): each plant / river terminal in one state, not the state average
LOC_SQL = """
WITH latest AS (
  SELECT s.id, s.provider, s.location, s.timestamp,
         ROW_NUMBER() OVER (PARTITION BY s.provider, s.location ORDER BY s.timestamp DESC) AS rn
  FROM snapshots s
  JOIN location_meta lm ON lm.provider = s.provider AND lm.location = s.location
  WHERE lm.facility_type IN ('Corn Processing', 'River Terminal') AND lm.state = %s AND s.timestamp >= %s
)
SELECT l.provider, l.location, lm.state, lm.facility_type, r.grain, r.delivery_month, r.futures_symbol, r.basis_cents, r.is_spot
FROM latest l
JOIN location_meta lm ON lm.provider = l.provider AND lm.location = l.location
JOIN snapshot_rows r ON r.snapshot_id = l.id
WHERE l.rn = 1 AND r.basis_cents IS NOT NULL
"""


def location_series(rows):
    """{(facility_type, provider, location): {(year, month): basis cents}} — corn, forward bids only, a location's bids for one delivery month
    averaged. facility_type is 'Corn Processing' (ethanol plants and corn processors) or 'River Terminal'."""
    per = {}
    for r in rows:
        if not str(r["grain"]).lower().startswith("corn") or r.get("is_spot"):
            continue
        ym = DP.canonical(r["delivery_month"], r["futures_symbol"])
        if ym:
            per.setdefault((r["facility_type"], r["provider"], r["location"], ym), []).append(r["basis_cents"])
    out = {}
    for (ft, prov, loc, ym), vals in per.items():
        out.setdefault((ft, prov, loc), {})[ym] = sum(vals) / len(vals)
    return out
