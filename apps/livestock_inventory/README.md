# Animal Inventory Dashboard

Streamlit dashboard for USDA animal **inventory** (head counts) across
**Livestock, Poultry, and Aquaculture**, at up to four geographic levels —
**National · State · Agricultural District · County** — built on the USDA NASS
QuickStats API. JPSI dark theme, matching the Beef Weight / Crop Conditions
dashboards.

## Series covered
A sidebar **Category** switch filters the series list:

- **Livestock** — All Cattle & Calves, Beef Cows, Milk Cows, All Cows, Calves,
  Cattle on Feed, Hogs (+ Breeding / Market), Sheep & Lambs (+ Breeding), Goats.
- **Poultry** — Table-Egg Layers, Replacement Pullets (both monthly Survey +
  Census, all 4 levels); Broilers, Turkeys, Ducks (**Census years only** —
  2017, 2022 — populate state/district/county in those years).
- **Aquaculture** — Catfish Foodsize / Stockers / Broodstock / Fingerlings & Fry
  (annual Survey, **National + State only**; the major catfish states).
- **Dairy** — Milk (total production, lb) and Milk per Cow (lb/head). A
  **production** flow, not head inventory, in **pounds**; annual totals updated
  monthly, **National + State only** (county/district milk production was
  discontinued after 2009).

Available geographic levels and year options adapt to the selected series. Head
counts (inventory) and pounds (milk production) are handled through per-series
`unit`/`measure` metadata, so labels, formatting and axes switch automatically.

## How each level is sourced
| Level | Source | Notes |
|-------|--------|-------|
| **National** | NASS Survey, annual | Long-run trend back to 1867; `pick_period` selects the Jan 1 (cattle/sheep/goats) or Dec 1 (hogs) reference period so multi-period years aren't double-counted. |
| **State** | NASS Survey, annual | US-states choropleth + rankings + per-state time series. |
| **County** | NASS Survey (major livestock states, annual) + **Census** (all counties, 2017 & 2022) | Survey preferred over Census when a county appears in both for a year. |
| **Agricultural District** | Aggregated up from county records via `asd_code`/`asd_desc` | NASS doesn't publish ASD inventory directly for recent years; counties are summed into the 9-15 crop-reporting districts per state and shaded as blocks. |

Poultry layers/pullets are monthly (the app picks a year-end period so years
aren't double-counted); broilers/turkeys/ducks are Census-only. Catfish is
annual Jan 1 / Jul 1 Survey, national + catfish states (no county).

Records are filtered to `domain_desc=TOTAL`, `unit_desc=HEAD`, with combined-county
codes (998/999/000) and suppressed `(D)` values dropped.

## Run locally
```bash
python -m streamlit run app.py
```

## Deploy (Streamlit Cloud)
Point at `app.py`. Set the API key in **Settings → Secrets**:
```toml
NASS_API_KEY = "your-key"
```
(The app falls back to a built-in key if unset.) `requirements.txt` pins
`plotly<6` for Cloud PNG-export compatibility.

Data: USDA NASS QuickStats · John Stewart & Associates
