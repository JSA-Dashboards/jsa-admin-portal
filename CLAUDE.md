# JSA Admin Portal

A single Streamlit process (`Home.py`) that merges ~20 previously standalone
dashboards under `apps/`. Most of what bites here comes from that merge.

## Never set SNOWFLAKE_SCHEMA in this app's secrets

Several bundled dashboards read Snowflake, and each defaults
`SNOWFLAKE_SCHEMA` to the schema **it** owns:

| module | its default |
|---|---|
| `apps/*/nass_cache_client.py` (beef_weight, crop_conditions, domestic_production, livestock_inventory) | `NASS_CACHE` |
| `apps/cme_feeder_cattle/snowflake_db.py` | `CME_FEEDER_CATTLE` |
| `apps/teams_broadcast/app.py` | `TEAMS_BROADCAST` |

Setting `SNOWFLAKE_SCHEMA` to any one value overrides all of them and silently
breaks the rest — pages load, queries miss, charts are empty, no error is
raised. **Leaving it unset is the only working configuration.** This was set to
`CME_FEEDER_CATTLE` and broke four NASS pages until 2026-09-05.

`SNOWFLAKE_DATABASE = "JSA"` is safe to set; everything defaults to `JSA` anyway.

## Each app's DB env var is renamed to avoid collisions

Two dashboards sharing one process would otherwise clobber each other's
`DATABASE_URL`. `Home.py` bridges renamed secrets into `os.environ` once at
startup:

- `BASISTRACKER_DATABASE_URL` — basis_tracker's own DB
- `RIVER_DATABASE_URL` — rail_fob's cross-read of river (CIF) data
- `RIVERFOB_DATABASE_URL` — river_fob's own DB
- `BASIS_DATABASE_URL` — river_fob + rail_fob cross-read of basis data

If you copy a dashboard in from its standalone repo, rename its `DATABASE_URL`
the same way or it will fight whichever app loads first.

**These were removed from the deployed Secrets on 2026-10-04. Do not re-add
them.** They pointed at the frozen Supabase copies (newest day Sept 3), and
having them there is what made a missing `USE_SNOWFLAKE` fail *silently*:
without the flag, River FOB, Rail FOB and the bids tab quietly served Sept-3
data instead of erroring. The deployed Secrets turned out to have no
`USE_SNOWFLAKE` at all, so the portal had been on Supabase (River FOB), the CSV
fallback (Cost of Carry) and a "No NASS cache backend" error (every NASS page)
for an unknown stretch. With the URLs gone, a missing flag now fails loudly.

## Pushing to GitHub does not deploy

This repo moved from a personal account into the `JSA-Dashboards` org. Streamlit
still has the app registered under the old owner path, so its webhook fires,
returns `200 OK`, and does nothing. There is no error.

To ship: push, then open the app URL → **Manage app → ⋮ → Reboot app**. The
reboot re-clones from GitHub. Allow 2–5 minutes; it shows a "not found" page
partway through provisioning, which is not a failure.

## Apps sharing code do not share secrets

Most dashboards here also exist as standalone repos running the same file. Each
deployment has its own separate secrets store. Changing a secret here does
nothing to the standalone app, and a secret one has may be absent in the other.
Check both before removing anything.

## Deployment facts

- Branch `master`, main file `Home.py`, Python 3.14
- Live at `jsatools-corporate.streamlit.app`
- Password-gated via `ADMIN_PASSWORD` (`require_admin_login()` in `Home.py`)

## Data backends

Snowflake is the live warehouse. Every bundled app reads Snowflake when
`USE_SNOWFLAKE` is truthy; the Postgres/Supabase `*_DATABASE_URL` values still in
secrets are stale rollback fallbacks only. Do not "fix" a stale number by
pointing an app back at Postgres.

**Account: `JSA-ANALYTICS`, as the service user `ADMIN_PORTAL_SVC` (since
2026-10-04; verified that night from Snowflake's query log: River FOB, NASS
cache, basis tracker, CME, Cost of Carry and Teams Broadcast all queried
successfully as `ADMIN_PORTAL_SVC`, with zero errors and nothing on the old
account).** The portal ran as Kolten's personal `ACCOUNTADMIN` key on the old
`GNC89034` account until then. That account is abandoned and no longer receives
data, so pointing anything back at it serves stale numbers. `ADMIN_PORTAL_ROLE`
holds exactly what the bundled modules use:

- **read:** `JSA.NASS_CACHE`, `JSA.CME_FEEDER_CATTLE`, `JSA.BASIS_TRACKER`,
  `JSA.COST_OF_CARRY`, `YIELD_REPORTS.PUBLIC` (all + future tables; the future
  grant matters for `YIELD_REPORTS`, whose loader drops and recreates
  `ISA_STRIP_TRIALS` on every load)
- **read/write:** `JSA.TEAMS_BROADCAST` (APP_DATA MERGE/DELETE)
- **River FOB:** `RIVER_FOB_ROLE` is granted to it, which covers read/write on
  `RIVER_FOB.PUBLIC`, CREATE TABLE, and the `save_lock` table

**`Home.py` bridges `USE_SNOWFLAKE` and the `SNOWFLAKE_*` settings into
`os.environ` itself, before navigation (since 2026-10-04).** Do not rely on
Streamlit's automatic export of root-level secrets. It skips any value that
isn't a str/int/float, so `USE_SNOWFLAKE = true` (a TOML boolean) never arrived.
Every module then fell back to its stale Postgres URL with no error: River FOB
showed "Postgres" / Sept 3. Cost of Carry and CME also bridge these lazily when
opened, so the backend used to depend on which page loaded first. `Home.py`
normalizes the flag to `"1"`. A setting under a `[section]` header is not
root-level and still won't be seen.

The key is unencrypted, and the Secrets carry no `SNOWFLAKE_PRIVATE_KEY_PWD`.
Every module's loader treats the passphrase as optional. **Adding a passphrase
line breaks every module**: cryptography refuses a password for an unencrypted
key. A new bundled app that reads another schema needs a grant on
`ADMIN_PORTAL_ROLE`, or it fails with "does not exist or not authorized".

**River FOB's "Save to archive" takes a lock.** This page is one of three writers
to `RIVER_FOB.PUBLIC`, along with the river-fob-portal app and its Bid Sheet
import. `apps/river_fob/db.py` `save_snapshot` runs one transaction that UPDATEs
the one-row `save_lock` table first, because Snowflake autocommits and doesn't
enforce PRIMARY KEYs. Without the lock, two simultaneous saves of a date
duplicate its rows. Keep it in step with river-fob-portal's `db.py`.

**River FOB's tile now opens river-fob.streamlit.app (2026-10-06), like Basis
Tracker's.** `apps/river_fob/` is no longer served. Kolten chose this over
porting about 1,000 lines plus 17 modules: the bundled copy had drifted far behind
the standalone (no Net Carry, Return to Carry or Massive button), and that drift
is what let a bad paste through. The code is kept for rollback only. Re-enabling
it means restoring the tile's `"page": "apps/river_fob/app.py"` + `url_path`, and
then it is a writer to `RIVER_FOB.PUBLIC` again. Everything below about this page
describes the dormant copy. The save check described next also lives in
river-fob-portal, where it is live.

**Major Exporters' tile now opens global-exports-dashboard-jsa.streamlit.app
(2026-10-07).** `apps/major_exporters/` is no longer served. The dashboard moved to
its own repo (JSA-Dashboards/global-exports-dashboard) and this bundled copy had
gone stale: it called TDM live from Cloud (Ukraine never loaded), used hardcoded
USDA forecasts, and kept the old chart legend, so colleagues using the portal never
saw any of the changes. The standalone reads a Snowflake cache that a droplet cron
fills daily, plus live USDA PSD forecasts. The code is kept for rollback only;
re-enabling it means restoring the tile's `"page":
"apps/major_exporters/corn_exporter_dashboard.py"` + `url_path`. The standalone's
Vessel Lineup tab asks for an upload (this copy shipped a 2026-08-21 snapshot of
`Vessel Lineup - US.xlsx`); the portal's own Vessel Lineup tile is the place for it.

**River FOB's futures: Massive button + a check before Save (2026-10-06).** On
10/06 a paste here archived the Bid Sheet's cached Eikon futures (12-14% under the
market, 4 of 8 months), and because that paste saved first, the Bid Sheet email
import correctly skipped the day. So:

- **Button:** the Inputs tab now has river-fob-portal's **🔄 Pull live CBOT
  futures (Massive)** button (`_pull_massive_futures`). It uses
  `riverfob_massive_api.py` / `riverfob_massive_futures.py`, copies of
  river-fob-portal's modules renamed because `grain_seasonal` has its own,
  different `massive_api.py` in the shared `sys.modules`.
- **Save check:** **Save to archive** runs `_futures_issues()` first:
  - months with no CBOT price;
  - for today's sheet only, any contract more than `STALE_FUTURES_PCT` (3%) from
    the live board.

  If it finds problems, nothing is saved: a warning offers **Save anyway** or
  **Cancel**. The live board after 7 PM is overnight trade (about 2% off the
  close one evening), which is why the threshold isn't tighter.
- `MASSIVE_API_KEY` reaches the page through `Home.py`'s bridge (and the page's
  own secrets loop).
- To test locally, use AppTest with `at.secrets` set; the local
  `secrets.toml` points at the dead old account.

Two data homes, because River FOB owns its own database:

| App / tab | Snowflake location | pinned in |
|---|---|---|
| basis_tracker (retired stub) | — redirects to the Streamlit-in-Snowflake app, touches no DB | `apps/basis_tracker/app.py` |
| river_fob own archive | `RIVER_FOB.PUBLIC` | `apps/river_fob/db.py::_sf_connect` |
| river_fob bids cross-read | `JSA.BASIS_TRACKER` | `apps/river_fob/bids_data.py` (`USE SCHEMA`) |
| rail_fob basis cross-read | `JSA.BASIS_TRACKER` | `apps/rail_fob/rail_data.py::_sf_connect` |
| rail_fob river (CIF) cross-read | `RIVER_FOB.PUBLIC` | `apps/rail_fob/river_data.py::_sf_connect` |
| strip_trials (JSA Yield Observations tile) | `YIELD_REPORTS.PUBLIC.ISA_STRIP_TRIALS` + `JSA.NASS_CACHE` | fully qualified in `apps/strip_trials/isa_strip_data.py` |

**JSA Yield Observations (`apps/strip_trials/`) is the yield portal's Strip trials page, read-only.** The
table is loaded by `JSA-Dashboards/yield-portal` (`load_isa.py`, run on the
Droplet); `apps/strip_trials/` only reads it, beside Iowa's NASS county yields
(the `yield_portal` job list in usda-nass-etl caches them from 2005). Its module
is named `isa_strip_data`, not `db`, because every bundled app shares one
`sys.modules`. A change to how the yield portal counts fields or compares them
with NASS belongs in both. ISA states its copyright and no other terms, which is
why it lives only behind passwords: here and the yield portal's internal pages.

The local `.streamlit/secrets.toml` still holds the old `GNC89034` personal key,
which Snowflake refuses ("JWT token is invalid"); the deployed Secrets are the
`ADMIN_PORTAL_SVC` ones. To try a page locally, give it a working login another
way (e.g. AppTest with `at.secrets`).

**The `SNOWFLAKE_DATABASE=JSA` collision:** the shell sets `SNOWFLAKE_DATABASE=JSA`
(no schema) globally, but the River FOB archive lives in a **separate**
`RIVER_FOB.PUBLIC` database. Every module that reads it therefore pins
`database="RIVER_FOB", schema="PUBLIC"` at connect time (see the `_sf_connect`
helpers), ignoring the ambient `JSA`. Miss that and the tab reads `JSA`, finds
nothing, and shows empty with no error. Migrated 2026-09-18; before that these
two tabs still read Supabase and served stale data.
