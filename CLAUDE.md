# JSA Admin Portal

A single Streamlit process (`Home.py`) that merges ~20 previously standalone
dashboards under `apps/`. Most of what bites here comes from that merge.

## `apps/<name>/` is a generated mirror. Never edit it here.

Each bundled dashboard is owned by another repo (listed in `sync/apps.json`:
a standalone repo, or `livestock-portal` for the livestock family). **Change the
dashboard in that repo, then run `python sync/sync_apps.py apply <name>`.** Edits
made inside `apps/` are overwritten by the next sync. This replaced hand-copying,
which left 13 of 16 bundled apps behind their source by October 2026.

- `status` shows drift per app, `plan <name>` the files and any NEW secrets the
  app now reads, `diff <name>` the diff. `check` finds module-name collisions and
  cwd-relative paths (no network). `python sync/smoke.py` loads every page once in
  one process, like the portal does. A page whose import can't resolve (a module the
  portal doesn't ship) FAILS it; missing secrets or runtime data files only warn.
- The sync copies the source and applies three idempotent patches, never touching
  logic: it removes `st.set_page_config` (`Home.py` makes the one call allowed per
  run), adds a `sys.path` shim so sibling imports resolve to the app's folder, and
  anchors literal relative file names to the app's folder (the portal's cwd is the
  repo root). `Home.py` also restores the top navigation if an app's CSS hides the
  header, and reloads any app module whose file changed on disk.
- **Collisions:** every bundled app shares one `sys.modules`. `check` fails if two
  apps ship the same sibling module name with different content. Fix by adding
  `"prefix_modules": "xx_"` to that app in `apps.json` (as `cost_of_carry` does).
- **A new upstream feature may need a secret, a Snowflake grant or a package the
  portal doesn't have.** `plan` lists new secret names; compare `requirements.txt`
  too. Secrets stay per deployment (see "Apps sharing code do not share secrets").
- **Themes:** the portal's `.streamlit/config.toml` applies to every page; a
  source's own `.streamlit/config.toml` is ignored. The portal is light-only, so a
  source with a dark inline palette needs a light option upstream: `vessel_lineup`
  reads `VESSEL_THEME` (dark by default) and the sync pins it to `light` (`pin_env`).
  Its data files (`*.db`, `*.xlsx`) are not mirrored: on Cloud the app downloads
  them from the public repo at runtime (`data_sync.py`, because `/mount/src`).
- `.github/workflows/sync-apps.yml` runs the sync daily and opens one pull request.
  Merging it is the update; the push deploys itself. A source that can't be cloned (the `SYNC_TOKEN` PAT
  can't read a private repo, a repo was renamed or deleted) is **skipped, not failed**: its mirror stays as
  it was, the run goes on with the other apps, and the skip shows as a warning annotation and on the run's
  summary page. If every source is skipped, or anything other than a clone goes wrong, `apply` still fails.
  (Before 2026-10-26 one unreadable private repo, `cftc_cot`, failed the whole run, so no sync PR opened
  from 10-11 on.) A skipped app goes stale quietly apart from that warning, so glance at the run summary
  now and then, or fix the token. `python -m pytest sync/test_sync_apps.py` covers the skip behaviour.

## Home page: Grain Apps / Livestock Apps tabs (2026-10-15)

`render_home` shows two tabs (lazy, `on_change="rerun"`, so only the open one runs). Both are tile grids
over `LIVE_DASHBOARDS`: **Livestock Apps** is every tile with `"category": "Livestock"`, **Grain Apps** is
everything else. The 15 livestock dashboards are generated mirrors of `JSA-Dashboards/livestock-portal`
(`subdir` entries in `sync/apps.json`: cme_feeder_cattle, livestock_seasonal, cot_report, cash_trade,
beef_cutout, mexican_feeder_imports, canadian_feeder_cattle, beef_trimmings, beef_trade, beef_weight,
us_cow_herd, cattle_on_feed, livestock_inventory, fed_cattle_crush, backgrounding_crush). Since 2026-10-23 most
of those pages `import portal_view` (the livestock repo's client-vs-staff switch, a repo-root module), so
`root_files` ships it to the portal root like `wasde.py`; it stays in staff mode here because `Client.py`, which
would flip it, is not mirrored. The livestock
portal's two staff tools (JSA Daily Cattle Reports = `weekly_reports`, Cattle Market Board = `market_board`)
are mirrors too, but they reach into the livestock repo's layout: its root `letter/` package, `portal_auth.py`,
`assets/agmarket-net.png` and sibling apps by file path. So `sync/apps.json` `root_files` also carries those (a
whole `dir` entry for `letter/`, copied to the portal's repo root like `wasde.py`), and `replace` pairs patch the
few spots that import a renamed sibling by bare name (`letter/sources.py` `import massive_api` -> `ls_massive_api`;
`market_board/loaders.py` `import corn_cost` -> `fcc_corn_cost`). A replace whose target text has gone fails the
sync loudly. Staff gate: they ask `portal_auth.is_admin()`, which `Home.py` satisfies once the portal login has
passed (`st.session_state["_portal_is_admin"]`), so there is no second passphrase here. They need `MARS_API_KEY`
in the portal Secrets (read straight from `st.secrets` by the allowlist at the top of `weekly_reports`), `msal` and
`python-pptx` in `requirements.txt` (Reboot). The Outlook-digest panel needs a device-code Graph sign-in cached on
the machine that signed in, so it stays empty on Cloud, as in the standalone app; PDF printing needs Chrome, which
Cloud lacks too.
`livestock_seasonal`, `fed_cattle_crush` and `backgrounding_crush` carry module prefixes
(`ls_`, `fcc_`, `bgc_`) because their `massive_api` / `snowflake_db` siblings differ from other apps'.
`LIVESTOCK_PORTAL_URL` in `Home.py` is the standalone portal, linked under the tiles.

History: the tab briefly embedded that portal in an iframe (2026-10-15) and six of these mirrors were deleted
and then restored the same day when the tiles were wanted back; the iframe version is in git history.

## Lazy tabs: only the open tab runs (2026-10-12)

`st.tabs()` builds every tab on every run. Basis Tracker (13 tabs), River FOB (11) and, since 2026-10-13, Cost of Carry, Grain Seasonal, Vessel Lineup, RMA map, CFTC COT, Domestic Production, USDA rail, and the livestock apps now use
`st.tabs(..., on_change="rerun")` with each body behind `if <tab>.open:`, so a first open or a
tab click runs only the tab being viewed. The rewrite is done by `sync/lazy_tabs.py` (run it
on the source repo's `app.py`, never on `apps/`): `check` lists any name a tab sets that another
reads (that would be a NameError once the setter is skipped) and `apply` refuses until there
are none. Both apps also had every tab body run alone with the rest skipped. Cost: widgets in
a tab are discarded when you leave it, so its dropdowns reset on return.


## Risk Analyzer (`apps/risk_analyzer/`, added 2026-10-12)

A synced mirror of `JSA-Dashboards/jsa-risk-analyzer`, tile under "Futures, Options & Spreads".
Its own `app.py` (shell + `st.navigation` + shared-password gate) can't nest, so
`sync/templates/risk_analyzer.py` is copied in as `app.py`: the same commodity picker and header,
a segmented control for its three pages (Risk dashboard / Add position / Import from Excel), and
each page script run as-is. The wrapper sets `authenticated` (the portal login is the only gate)
and `_embedded`; `add_position.py` then asks the wrapper to open the dashboard after a save
instead of calling `st.switch_page`.

- **Secrets:** upstream `jsa_risk/config.py` uses a `[snowflake]` block when present, otherwise
  this portal's root-level `SNOWFLAKE_ACCOUNT/USER/ROLE/WAREHOUSE/PRIVATE_KEY` against
  `JSA.RISK_ANALYZER`. `MASSIVE_API_KEY` (already here) feeds the market strip; the CME DataMine
  IV lookup needs optional root-level `CME_DATAMINE_API_ID` + `CME_DATAMINE_PASSWORD`. Don't add
  `[snowflake]` etc. blocks here. The `plan` command's long NEW SECRETS list is mostly SQL column
  constants; only those names are real.
- **Grant:** `ADMIN_PORTAL_ROLE` needs `USAGE` on schema `JSA.RISK_ANALYZER` plus SELECT/INSERT/
  UPDATE/DELETE on its tables (positions, import presets, IV snapshot, contract marks, audit log).
- Header/disclaimer colors were made theme-neutral upstream (the standalone app is dark, the portal
  light). `scipy` is in `requirements.txt` for it; adding it needs a Reboot.

## CSO & Spread Risk Analyzer (`apps/cso_risk_analyzer/`, added 2026-10-15)

A synced mirror of `JSA-Dashboards/cso-risk-analyzer` (branch `main`; **public since 2026-10-15**, made
public "for now"), tile under "Futures, Options & Spreads". CME calendar spread options priced as one
option on the nearby-minus-deferred spread (Bachelier), with quote-implied skew, hedged-vs-unhedged
analysis and, as its first tab (added 2026-10-26), a **Strategy builder**: a put or call, bought or sold, laid
over a spread position (the position control names the long and the short contract month), with the payoff
shaded green where it gains and red where it loses, and the spread's full carry and 12-month range beside it.
On 2026-10-26 it gained a **leg picker** (*Spread from → Live curve*: pick the near and far contract from the
feed's current curve) and a **seasonal overlay** (the same pair in up to five earlier years, plus a replay of
each year's move as dots on the payoff chart); on 2026-10-28 the option can be **sold** as well as bought
(*Option: Buy / Sell*, default Buy). Unlike the Risk Analyzer it needs
no Snowflake, no grant and no new package (scipy, altair and requests were already here), so merging or pushing
it is the whole deploy. Its one secret is the optional root-level `MASSIVE_API_KEY`, which this portal already
holds (`Home.py` bridges it): it powers *Fetch futures prices* and the Strategy builder's fed-funds rate,
contract list and settlement history (the history calls take about 5-7 s each on the first open, then are cached
for 6 hours; the seasonal overlay reads about ten of them in parallel, so its first load takes about 20 s, and
it is off until switched on). `sync_apps.py plan` lists it as a "new secret"; it is not. Its entry `app.py` is the source's own (no wrapper: single page, no `st.navigation`);
session and widget keys are `cso_`-prefixed because every bundled app shares one session; tabs use the lazy
`on_change="rerun"` pattern. The app also reloads its own `cso/*` modules when a push changes them, alongside
`drop_changed_modules()`.

- **Password:** the standalone app sits behind a shared-password gate (`cso/auth.py`, keyed on
  `st.session_state["_authed"]`). `"preauth": true` in `sync/apps.json` makes the sync pre-set that key, so
  the portal login stays the only gate here. Take `preauth` away and the tile asks for a second password.
- **Source visibility:** it is public, so CI clones it without a token. If it goes private again, put
  `"private": true` back in `sync/apps.json` and make sure the `SYNC_TOKEN` PAT (as for `cftc_cot` and
  `crop_conditions`) can read it. A fine-grained PAT limited to selected repos would otherwise make `apply`
  skip this app (the tile stays at its last synced version, with a warning on the run) until the token can
  read it. This portal repo is public, so every mirrored app's code is readable here whatever its source
  repo's visibility.
- Locally, `sync/smoke.py` times a page out at 25 s and a cold scipy import alone can take that long on a
  slow disk: run `SMOKE_TIMEOUT=200 python sync/smoke.py cso_risk_analyzer`.

## Never set SNOWFLAKE_SCHEMA in this app's secrets

Several bundled dashboards read Snowflake, and each defaults
`SNOWFLAKE_SCHEMA` to the schema **it** owns:

| module | its default |
|---|---|
| `apps/*/nass_cache_client.py` (crop_conditions, domestic_production) | `NASS_CACHE` |
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

- `RIVER_DATABASE_URL` — rail_fob's cross-read of river (CIF) data
- `BASIS_DATABASE_URL` — rail_fob's cross-read of basis data

If you copy a dashboard in from its standalone repo, rename its `DATABASE_URL`
the same way or it will fight whichever app loads first. (basis_tracker and river_fob take their DB from Snowflake, pinned by the sync.)

**These were removed from the deployed Secrets on 2026-10-04. Do not re-add
them.** They pointed at the frozen Supabase copies (newest day Sept 3), and
having them there is what made a missing `USE_SNOWFLAKE` fail *silently*:
without the flag, River FOB, Rail FOB and the bids tab quietly served Sept-3
data instead of erroring. The deployed Secrets turned out to have no
`USE_SNOWFLAKE` at all, so the portal had been on Supabase (River FOB), the CSV
fallback (Cost of Carry) and a "No NASS cache backend" error (every NASS page)
for an unknown stretch. With the URLs gone, a missing flag now fails loudly.

## Pushing to GitHub deploys (fixed 2026-10-11)

A push to `master` redeploys the portal within about a minute, no reboot. It did
nothing from the org move until 2026-10-11: the Streamlit app was registered in a
personal workspace under the old owner path (`koltenpostin93-blip/jsa-admin-portal`),
so its webhook fired, returned `200 OK` and matched no app. It was recreated in the
**jsa-dashboards** workspace as `JSA-Dashboards/jsa-admin-portal` / `master` /
`Home.py`, and proved by a page-title change that flipped after a push.

Merging the daily sync pull request is therefore the whole update. Reboot (Manage
app > Reboot app) only after a change to `requirements.txt` or the Python version.
`drop_changed_modules()` already reloads changed app modules on hot reload.

To check the hook again: change `page_title` in `Home.py`, push, reload the live
URL and read `iframe.contentDocument.title`. A delivery showing `200` on GitHub
proves nothing; the same `200` came back for weeks while nothing deployed.

If the app ever has to be recreated: copy Settings > Secrets out first, delete it,
switch to the **jsa-dashboards** workspace, then Create app from
`JSA-Dashboards/jsa-admin-portal`, branch `master`, main file `Home.py`, URL
`jsatools-corporate`, Python 3.14, and paste the Secrets (no `SNOWFLAKE_SCHEMA`).

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

**Basis Tracker, River FOB and Major Exporters are bundled again (2026-10-11),
as generated mirrors** of basis-tracker, river-fob-portal and global-exports-dashboard
(see "`apps/<name>/` is a generated mirror" above). The earlier hand-copies drifted
and River FOB's was a second, stale writer to `RIVER_FOB.PUBLIC`; the mirrors run
the same code as the standalone apps, so a second writer is now harmless (River FOB's
save takes the `save_lock`). Things the sync does for them, in `sync/apps.json`:

- `preauth`: sets the apps' own password gate (`st.session_state["_authed"]`) so
  the portal's login is the only one.
- `pin_env`: River FOB reads `RIVER_FOB.PUBLIC` and Basis Tracker `JSA.BASIS_TRACKER`,
  but both take database/schema from `os.environ`, which this shell sets to `JSA`
  with no schema for everyone. The sync replaces those reads with the literals.
- `prefix_modules` (`bt_`, `rf_`): their sibling modules share names with each
  other and with other apps.
- Grants: `ADMIN_PORTAL_ROLE` reads `JSA.BASIS_TRACKER` but Basis Tracker's admin
  actions (imports, snapshot deletes, rundown posts) also WRITE it; without a write
  grant those fail with "insufficient privileges". Major Exporters reads `EXPORTS.PUBLIC`.

Where each bundled app reads Snowflake:

| App / tab | Snowflake location | pinned in |
|---|---|---|
| rail_fob basis cross-read | `JSA.BASIS_TRACKER` | `apps/rail_fob/rail_data.py::_sf_connect` |
| rail_fob river (CIF) cross-read | `RIVER_FOB.PUBLIC` | `apps/rail_fob/river_data.py::_sf_connect` |
| yield_portal (JSA Yield Observations tile) | `YIELD_REPORTS.PUBLIC` + `JSA.NASS_CACHE` | pinned in `apps/yield_portal/yp_db.py` |
| crop_conditions Field Check tab (beta, internal) | `YIELD_REPORTS.PUBLIC.FIELD_SIGNAL` | fully qualified in the query; the tab shows only where `FIELD_CHECK` is "1", which only this portal's sync pins (`pin_env`), so the public standalone app never shows it |

**JSA Yield Observations (`apps/yield_portal/`) is the whole yield portal, a synced mirror
of `JSA-Dashboards/yield-portal`**: Explore, Report text, Reports vs normal, Field issues,
Variety trials, Strip trials, and the entry screens Add reports, Review & edit and Import
PDF. The yield portal runs them under its own `st.navigation`, which can't nest inside this
portal's, so `sync/templates/yield_portal.py` is copied in as `app.py`: a page switcher that
runs each page script as-is. Internal only (this portal is password-gated; the yield portal's
own `?view=1` client link is a separate app). The entry screens write to `YIELD_REPORTS.PUBLIC`,
so `ADMIN_PORTAL_ROLE` needs INSERT/UPDATE/DELETE on `YIELD_OBSERVATIONS` and
`REVIEW_DECISIONS` plus CREATE TABLE on the schema (granted 2026-10-11), on top of the
SELECT it already had. `yp_db.py` pins `YIELD_REPORTS.PUBLIC` itself, so the shell's
`SNOWFLAKE_DATABASE` doesn't matter.

**Field check (beta)** in that tile (2026-10-14, Kolten: "I want it in the JSA Yield
observations as well but under the admin page") is not a yield portal page: the wrapper
runs `apps/crop_conditions/app.py` with `FIELD_CHECK_ONLY = True` in its globals
(`runpy` `init_globals`), and the Conditions script then shows a commodity/season picker
and only its Field Check (the conditions model beside the yield portal's
`FIELD_SIGNAL`), then stops. Same code and numbers as the Crop Conditions tab, no copy of
the model; it needs both mirrors present and `FIELD_CHECK` pinned for crop_conditions.
First open is as slow as the Conditions page (shared caches after). ISA states its copyright and no other terms, which is
why the strip trials live only behind passwords. The old `apps/strip_trials/` copy is deleted.

The local `.streamlit/secrets.toml` still holds the old `GNC89034` personal key,
which Snowflake refuses ("JWT token is invalid"); the deployed Secrets are the
`ADMIN_PORTAL_SVC` ones. To try a page locally, give it a working login another
way (e.g. AppTest with `at.secrets`).

**The `SNOWFLAKE_DATABASE=JSA` collision:** the shell sets `SNOWFLAKE_DATABASE=JSA`
(no schema) globally, but the River FOB archive (read by rail_fob) lives in a **separate**
`RIVER_FOB.PUBLIC` database. Every module that reads it therefore pins
`database="RIVER_FOB", schema="PUBLIC"` at connect time (see the `_sf_connect`
helpers), ignoring the ambient `JSA`. Miss that and the tab reads `JSA`, finds
nothing, and shows empty with no error. Migrated 2026-09-18; before that these
two tabs still read Supabase and served stale data.
