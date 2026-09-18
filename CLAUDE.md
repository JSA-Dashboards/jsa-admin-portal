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

**These are now Postgres-rollback only.** As of 2026-09-18 all four consumers
read Snowflake when `USE_SNOWFLAKE` is truthy (see **Data backends**), so every
URL above is ignored in normal operation. `BASISTRACKER_DATABASE_URL` is fully
dead (basis_tracker is a redirect stub). Keep the other three only as a
rollback (clear `USE_SNOWFLAKE` → back on Supabase); delete all four once
Supabase is decommissioned.

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

Two data homes, because River FOB owns its own database:

| App / tab | Snowflake location | pinned in |
|---|---|---|
| basis_tracker (retired stub) | — redirects to the Streamlit-in-Snowflake app, touches no DB | `apps/basis_tracker/app.py` |
| river_fob own archive | `RIVER_FOB.PUBLIC` | `apps/river_fob/db.py::_sf_connect` |
| river_fob bids cross-read | `JSA.BASIS_TRACKER` | `apps/river_fob/bids_data.py` (`USE SCHEMA`) |
| rail_fob basis cross-read | `JSA.BASIS_TRACKER` | `apps/rail_fob/rail_data.py::_sf_connect` |
| rail_fob river (CIF) cross-read | `RIVER_FOB.PUBLIC` | `apps/rail_fob/river_data.py::_sf_connect` |

**The `SNOWFLAKE_DATABASE=JSA` collision:** the shell sets `SNOWFLAKE_DATABASE=JSA`
(no schema) globally, but the River FOB archive lives in a **separate**
`RIVER_FOB.PUBLIC` database. Every module that reads it therefore pins
`database="RIVER_FOB", schema="PUBLIC"` at connect time (see the `_sf_connect`
helpers), ignoring the ambient `JSA`. Miss that and the tab reads `JSA`, finds
nothing, and shows empty with no error. Migrated 2026-09-18; before that these
two tabs still read Supabase and served stale data.
