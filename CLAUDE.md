# JSA Admin Portal

A single Streamlit process (`Home.py`; `Client.py` is the same shell for clients, see "Client portal") that merges ~20 previously standalone
dashboards under `apps/`. Most of what bites here comes from that merge.

## `apps/<name>/` is a generated mirror. Never edit it here.

Each bundled dashboard is owned by another repo (listed in `sync/apps.json`:
a standalone repo, or `livestock-portal` for the livestock family). **Change the
dashboard in that repo, then run `python sync/sync_apps.py apply <name>`.** Edits
made inside `apps/` are overwritten by the next sync. This replaced hand-copying,
which left 13 of 16 bundled apps behind their source by October 2026.

**`apply` with no name syncs EVERY app to its repo's latest commit**, so it also deploys other people's pending pushes (a
logo-only sync on 2026-11-09 dragged in ~1,800 lines: rail shipments, the letter, draw model, scrapers). Read
`git diff --stat -- . ':!*.sync.json'` before committing a sync, and sync just the app you changed when that is all that was
asked. A peer session may be mid-sync in the same checkout (uncommitted `apps/` edits that are not yours): leave them.

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

## Client portal (`Client.py`, added 2026-11-04)

The same codebase serves clients: a SECOND Streamlit Cloud app (jsa-dashboards workspace, this repo, branch
`master`, **main file `Client.py`**) next to the staff app on `Home.py`. Modelled on the Livestock Portal's
`Client.py`. `Client.py` sets `JSA_PORTAL_VIEW=client` and `portal_view.set_client()`, then `runpy`s `Home.py`; which
portal a deployment is comes from the main file it points at, never a secret, so a client deployment cannot come up
as the staff portal (and a lost secret cannot turn the staff one into the client one).

What `CLIENT` (in `Home.py`) changes:
- **Login:** `require_client_login()` (`shared/auth.py`) with one shared `CLIENT_PASSWORD`. It FAILS CLOSED: with no
  password configured the page says it is closed. Different from `ADMIN_PASSWORD`, so handing it out never opens staff.
- **Tiles:** DEFAULT-DENY. `CLIENT_PAGES` lists the url_paths clients get; anything not listed is neither shown nor
  registered with `st.navigation` (so its URL does not route). `test_client_portal.py` fails if a new tile is in neither
  CLIENT_PAGES nor the staff-only set. Left off: CSO & Spread Risk Analyzer (a Coming soon tile instead), RMA Production
  Map, Teams Broadcast, Morning Financial Wire, Grain Marketing Desk, and the Livestock staff tools (Daily Cattle
  Reports, Cattle Market Board). Farmer Selling Survey is shown under **Cash Grain** (`CLIENT_CATEGORY`).
- **Price strip** (`quotes.py`, rendered above the tabs): nearby Corn, Chi Platts ethanol, SRW, HRW, Soybeans, Meal,
  Soy oil and the Soy crush, each with its last settle and change from the prior settle. Nearby rolls after first notice
  day (the COT dashboard's own `futures_move.py`, loaded from `apps/cftc_cot`), both ends of a change on the same
  contract. Grains come from `JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS` (filled 4:30pm CT, so the strip reads the prior
  session until then); Chi Platts is the CME Chicago Ethanol futures settle in `JSA.BASIS_TRACKER.ETHANOL_FUTURES` (a
  futures proxy, not the Platts print); the crush is the board crush on the soybean nearby's month. End-of-day, not live.
  **Check CME's terms for showing settlements to clients before this goes out.**
- **Read-only mode of each app**, structural and set by the client flag: Basis Tracker reads `VIEW_ONLY` (Home sets it);
  River FOB, China Soybeans, Farmer Selling Survey (Admin tab, sidebar upload) and Grain Seasonal (Ask AI tab) are patched
  by `replace` pairs in `sync/apps.json` that call `portal_view.is_client()` / `portal_view.tabs(hide=...)`, which are
  no-ops for staff; the yield tile (`sync/templates/yield_portal.py`) shows only Explore and Report text, exactly what
  the yield portal's own `?view=1` link shows (variety trials await Ohio State's permission, strip trials are ISA's).
  The 13 livestock pages that import `portal_view` hide their working tabs, raw Data tabs, analyst-estimate inputs
  (COF Recap), Spread Builder / Chat and Refresh buttons on their own (63 tests in the livestock repo pin it).
- **Standing rule for the grain apps, same as the livestock view's:** a client gets no data-entry, upload, admin, AI-chat
  or cache-refresh control. Session-only what-if inputs (the calculators: Cost of Carry, the two crush pages, Risk
  Analyzer's positions, Mexican feeder scenario boxes) stay; they write nothing anyone else sees. Done by `replace`
  pairs in `sync/apps.json` (`is_client()` / `staff_expander` / `portal_view.tabs(hide=...)`), all no-ops for staff:
  Refresh/Reload buttons (Cost of Carry, Grain Seasonal, CFTC COT, EIA, Major Exporters, Vessel Lineup, River FOB,
  Domestic Production), Rail FOB's "Data source" expander (USDA token + live refresh), Vessel Lineup's file uploads,
  and Grain Seasonal's **Ask AI and H/L Forecast tabs** (High/Low Model is a Coming-soon tile for now; take
  `"📊 H/L Forecast"` out of the hide set to show it).
- **Risk Analyzer writes to shared tables** (contract marks, import presets) when a user types a price or saves a preset.
  In the client view the wrapper sets `st.session_state["_session_only"]`, which the app's `state.session_only()` honors:
  a client's price stays in their session and the preset boxes disappear. That code lives in the jsa-risk-analyzer repo
  (`state.py`, `pages/import_excel.py`, `tests/test_session_only.py`); until it is pushed there and synced, the flag does nothing.
- **Secrets for the client app:** the Snowflake settings (no `SNOWFLAKE_SCHEMA`), `USE_SNOWFLAKE`, `MASSIVE_API_KEY`,
  `MASSIVE_S3_ACCESS_KEY` / `_SECRET_KEY`, `NASS_API_KEY`, `MARS_API_KEY` (Beef Trimmings, Cattle Weights and the CME
  Feeder Cattle Index read it), `EIA_API_KEY`, `CLIENT_PASSWORD`. NOT `ADMIN_PASSWORD`, `GRAPH_*`, `ANTHROPIC_API_KEY`,
  `EDIT_PASSWORD`, `APP_PASSWORD`, `SIG_*`: the features that used them are hidden for clients.
- **Read-only Snowflake login (2026-11-09):** `snowflake/client_portal_role.sql` creates `CLIENT_PORTAL_ROLE` (SELECT only, on
  exactly the schemas the client dashboards read) and `CLIENT_PORTAL_SVC` (key-pair, TYPE=SERVICE, COMPUTE_WH). The client
  app's Secrets then carry `SNOWFLAKE_USER` / `SNOWFLAKE_ROLE` / `SNOWFLAKE_PRIVATE_KEY` for that user instead of the
  ADMIN_PORTAL_SVC ones, so a write fails in the database whatever the UI does. The private key lives only in the client app's
  Secrets (and `~/.snowflake/keys/` on Kolten's PC), never in the repo. ROLLBACK: put the ADMIN_PORTAL_SVC values back in the
  client app's Secrets and reboot. A NEW client dashboard that reads a new schema needs it added to the script's list and
  re-run, or its tile says "does not exist or not authorized". Things that wrote on view and were handled: Rail FOB's BN
  freight inputs (its own `RAIL_VIEW_ONLY` switch, which Home.py now sets for clients), the beef cutout's opportunistic bank
  of the AM cutout (skipped for clients), Risk Analyzer's audit-log insert (now best-effort).
- **Disclaimer + tile wording (2026-11-09):** the client home ends with the standard JSA legal footer (`DISCLAIMER_FOOTER_HTML` in
  Home.py, client mode only; staff pages carry their own per-app footers). `CLIENT_DESC` overrides the tile text for China Soybean
  Purchases, Yield Observations and Farmer Selling Survey so clients are not told about admin queues, entry screens or trials they
  cannot see (a test keeps "admin" / "entry" out of it). Add an override whenever a tile's description mentions a staff-only feature.
- **Logo (2026-11-09):** the 500x140 JSA logo replaced the old 222x60 file in `assets/logo-full.png` and in 12 standalone repos
  (dark = `logo-full.png` / `jsa_logo_full.png`, white for dark headers = `jsa_logo_white.png`). All size code is by height, so a
  same-shape logo drops in. The client header uses `assets/logo-jsa-large.png` at width 380.
- **Price strip follows the tab (2026-11-09):** `strip_slot` in Home.py is filled after the Grain / Livestock tabs, with
  `quotes.render("livestock" if livestock_tab.open else "grain")`. The Livestock strip is live cattle, feeder cattle, the CME Feeder
  Cattle Index, lean hogs and corn: the three futures are Massive settles on the nearest unexpired contract (cash-settled, so no
  notice day; read the way the COT dashboard does, `cot_massive.livestock_settles`), the index is CME's PUBLISHED value from
  `JSA.CME_FEEDER_CATTLE.CME_FTP_DAILY` with its own date (CME posts it 1-3 days late; JSA's reconstruction is never shown to
  clients), corn is the grain strip's own tile. Futures and index are cached separately and a failed read raises so it is not cached.
  `quotes.warm_livestock()` (called once the grain strip is drawn) fills those caches in a daemon thread so the Livestock tab opens
  instantly (the Massive fetch alone takes ~13 s); at most one warm-up per 13 minutes per app process, whoever visits. The strip
  shows shimmer placeholder tiles on a session's first paint (`placeholder_html`) and the real one replaces them only once the
  prices are fetched (`fetch` then `render`: opening a container inside an st.empty slot clears the slot at once).
- **A read path must never run DDL (found 2026-11-10, Trends blank for clients).** The client app's Snowflake role is SELECT-only, and the Basis Tracker's
  `get_index_excludes()` ran `CREATE TABLE IF NOT EXISTS` before every read (the Trends tab's outlier list); Snowflake refuses that statement for a role with no
  create right even when the table exists, so the whole tab failed. Fixed in the source repo (basis-tracker-streamlit `fed8211`: read first, create only if the
  read fails, return an empty set if even that is refused) and synced (`c311c05`). Anything else a client page reads through an `_ensure_*` / `CREATE ... IF NOT
  EXISTS` first will break the same way: when a client tile errors with "insufficient privileges", look for DDL in the read path before touching the grants.
- **The strips show DELAYED prices, not settlements (2026-11-10, Kolten: "make the quote tiles the 10 min delay after all").** `quotes.with_delayed` lays Massive
  `/snapshot` last-trade prices (one batch call, cached 60 s for everyone) over the settlement tiles, and the footnote gives the time of the last trade. Rules that
  matter: (1) a snapshot is used ONLY when Massive labels it `DELAYED` (a real-time feed would be ignored: redistributing real-time CME data to clients is a licence matter);
  (2) the change is against the prior SESSION's settlement taken from our own settlement series (`prior_settle` / `trade_date`: CME's trade date rolls at 5 PM CT), NOT the
  snapshot's `previous_settlement`, which Massive rolls to the settle just posted once the day's settlement is out (Dec corn on 11-10 read 449.0 = that day's settle, so
  a +9.75 day showed -1.0); (3) the ethanol proxy and the Feeder Cattle Index have no intraday price and are marked "settle" / "CME cash index"; the soy crush is rebuilt from
  three delayed legs; (4) any failure leaves the settlement tiles. The ticker is under `details.ticker` in a snapshot row. The 10-minute figure is the feed's own DELAYED label: not
  yet measured against a live session (the market was closed when this was built): check a last-trade time against the clock while the market is open. **CME licensing is
  still unchecked** (see Still open): delayed data shown to clients is the kind of thing its terms cover.
- **Global Crop Conditions & Progress (2026-11-10, both portals, Supply & Demand).** A mirror of `JSA-Dashboards/canada-crop-conditions` (PRIVATE repo; its code and ~18 MB of
  data are now in this public repo, Kolten approved): the world crop-conditions app with a Country switch (Canada, Mexico, France, Brazil, Argentina, South Africa). `sync/apps.json`
  `global_crops` uses `prefix_modules: "gcc_"` (its siblings are `model`, `charts`, `theme`, `geo`, `production`, ...) and one `replace` that turns off `theme.apply`'s
  `_plotly()` and `titles.apply()`: they rewrite the shared `plotly_white` template and wrap `st.title` / `st.header` / `go.Figure.update_layout` for EVERY app in the process, for good.
  The cost is that its headings are not auto title-cased and its charts use the stock template. It reads only its bundled CSVs (no secrets, no Snowflake). All six country views were run
  headless without an exception. Data refreshes when the droplet job pushes to that repo, then `apply global_crops`.
- **Keep-alive:** the client URL is in `sync/keep_alive_apps.txt` (20 apps, all up at the 11-09 check).
- **Still open:** CME's terms for showing settlements to clients were not checked.
- Adding an app: add its tile, decide client or staff (test enforces it), and make sure it has a read-only mode.

## Lazy tabs: only the open tab runs (2026-10-12)

`st.tabs()` builds every tab on every run. Basis Tracker (13 tabs), River FOB (11) and, since 2026-10-13, Cost of Carry, Grain Seasonal, Vessel Lineup, RMA map, CFTC COT, Domestic Production, USDA rail, and the livestock apps now use
`st.tabs(..., on_change="rerun")` with each body behind `if <tab>.open:`, so a first open or a
tab click runs only the tab being viewed. The rewrite is done by `sync/lazy_tabs.py` (run it
on the source repo's `app.py`, never on `apps/`): `check` lists any name a tab sets that another
reads (that would be a NameError once the setter is skipped) and `apply` refuses until there
are none. Both apps also had every tab body run alone with the rest skipped. Cost: widgets in
a tab are discarded when you leave it, so its dropdowns reset on return.


## Crop Conditions removed from the portal (2026-11-03)

Kolten asked for the Crop Conditions & Yield Model dashboard to come off the portal "for now" because it was
hurting the other apps here (its first load reads a lot from the NASS cache and shares this one process).
Removed: its tile, `apps/crop_conditions/`, its `sync/apps.json` entry (with the `FIELD_CHECK` pin) and the
Yield Observations "Field check (beta)" page that ran it. NOT touched: the standalone Crop Conditions app, the
NASS ETL and cache, and the separate **Crop Progress** tile. To bring it back: re-add the `apps.json` entry
(`repo` `JSA-Dashboards/crop-conditions-dashboard`, `"private": true`, `pin_env` `FIELD_CHECK` `"1"`), the
`LIVE_DASHBOARDS` tile (`apps/crop_conditions/app.py`, url_path `crop-conditions`), then `apply crop_conditions`;
the yield portal's Field check page reappears on its own.

**Back on the CLIENT portal only (2026-11-10).** Kolten: "the Crop Conditions dashboard should be included on the Supply & Demand, but the
view only side". The tile has `"client_only": True` in `LIVE_DASHBOARDS` (Home.py drops client_only tiles for staff, so the staff portal still
does not have it), `crop-conditions` is in `CLIENT_PAGES`, and `sync/apps.json` has the entry again WITHOUT the `FIELD_CHECK` pin (so the yield portal's
Field check page stays hidden) and with one `replace` that hides the 🔄 NASS refresh button for clients. The app is otherwise read-only (it reads
`JSA.NASS_CACHE` through `nass_cache_client.py`, writes nothing; its Excel download buttons stay, like the other client apps' downloads). **Its code is now
mirrored into this PUBLIC repo** (Kolten approved that on 11-10; before it was history only). The cost to watch is the one that took it off staff: a heavy first load,
now in the client app's process. `test_client_portal.py` pins the client-only set to exactly `crop-conditions`.

## Legacy Apps tab (2026-11-13)

Kolten: "add a Tab that is legacy apps" for seven dashboards that still live as pages on the jpsi.com website. A fourth home-page tab (after Reports Calendar) in BOTH portals, drawn by `_render_legacy()` from `LEGACY_APPS` in Home.py
as the same tiles as the rest of the page (keys `tile_legacy_N`); each is a link that opens the jpsi.com page in a new tab: Crop Conditions, Crop Progress, Domestic Production, Export Inspections, Export Sales, World S&D, Quarterly Grain
Stocks (all answered 200 on 11-13; their descriptions are only the title, since the pages carry no description). To add or retire one, edit that list (`test_client_portal.py` checks they are unique jpsi.com links).

## Self-hosted portals: `clients.jpsi.com` and `portal.jpsi.com` (built 2026-11-13, `deploy/`)

Streamlit Community Cloud cannot serve a custom domain, so Kolten chose to run the same code on a droplet of its own: `jsa-portals`, 161.35.113.169 (Ubuntu 24.04, 2 vCPU / 3.9 GB, 2 GB swap). Everything is in `deploy/`: `README.md` (runbook),
`setup_droplet.sh` (idempotent, run as root over ssh; `--caddy` writes the Caddyfile and reloads, only AFTER the DNS records exist or Caddy keeps failing to get certificates) and `secrets-names.md` (setting names only). Not a new copy of the apps:
each portal is its own clone of THIS repo (`master`) with its own OS user, venv and secrets, so the client process can never read the staff secrets.

| | client portal | staff portal |
|---|---|---|
| name | `clients.jpsi.com` | `portal.jpsi.com` |
| main file / port (127.0.0.1) | `Client.py` / 8601 | `Home.py` / 8602 |
| user, clone, venv | `jsa-client`, `/srv/jsa-client/{repo,venv}` | `jsa-staff`, `/srv/jsa-staff/{repo,venv}` |
| secrets (0600) | `/srv/jsa-client/home/.streamlit/secrets.toml` | `/srv/jsa-staff/home/.streamlit/secrets.toml` |
| service | `jsa-portal@client` | `jsa-portal@staff` |

- **Deploying a change does NOT happen on push** (Streamlit Cloud does): push, then `ssh root@161.35.113.169 /srv/deploy/update.sh` (pulls both clones, reinstalls requirements only if they changed, restarts both; a restart drops sessions). Streamlit Cloud apps keep
  redeploying on push as before and stay as the fallback for about a month after cutover.
- **State at 2026-11-13:** the client portal is installed and RUNNING (health ok, ~60 MB idle); its login verified as `CLIENT_PORTAL_SVC` / `CLIENT_PORTAL_ROLE` (reads, refuses CREATE TABLE). Not reachable by name until IT adds the A records for both names to
  161.35.113.169 (DNS only, TTL 300); the staff portal has no secrets installed and is not started. Order: DNS, `--caddy`, test https://clients.jpsi.com as a client, watch `free -m` for a day, then the staff portal (strong `ADMIN_PASSWORD` on the server copy first),
  then tell clients and staff the new addresses. Add both origins to the Legacy Apps hosts' `frame-ancestors` only if embedding is ever wanted (see the Legacy Apps section).
- **Secrets install traps (all hit on 11-13; the README has the safe commands):** check the clipboard by NAMES before installing (the client block has `CLIENT_PASSWORD` and `SNOWFLAKE_USER=CLIENT_PORTAL_SVC`; a block with ACCOUNTADMIN, `ADMIN_PASSWORD` or `GRAPH_*`, or the Livestock
  Portal's `PORTAL_PASSPHRASE`, is the wrong app); Windows PowerShell adds a BOM when piping, which hides line 1 (strip with `sed`); never `grep` a secrets file for names with a pattern a PEM key line also matches; leave `ANTHROPIC_API_KEY`, `WA_*`, `TDM_PASSWORD` out of the client copy.
  `MARS_API_KEY` is missing from the live client app (and so the server copy): Beef Trimmings, Cattle Weights and the CME Feeder Cattle Index tiles need it.
- Shell scripts are pinned LF in `.gitattributes` (`*.sh text eol=lf`): a CRLF `setup_droplet.sh` fails on the server.

## Report calendar: "This Week's Reports" and the Reports Calendar tab (2026-11-12)

Kolten: a USDA reports calendar tab for grain and livestock, "This Weeks Reports" on the home page for each, the economic reports (CPI, PPI) mixed into both, then (same day) EIA
under Economic, the weekly export inspections / export sales / CFTC report, federal holidays and CME grain holidays with their effect on trading hours. Answers when asked: ONE "Reports Calendar" tab,
BOTH portals. `report_calendar.py` (the portal's own, not a mirror) + `report_schedule_data.py` + `test_report_calendar.py` (35 checks); `Home.py` has a third home-page tab and a card at the top of the
Grain and Livestock tabs (`render_week`). The tab has five on/off pills (Grain, Livestock, Economic, Holidays [federal, CME, China], International, all on); an event shows when any of its tags is on.

- **Tags and scopes.** grain / livestock / economic / holiday / international. A card or scope shows its own plus every economic AND holiday event. WASDE, Agricultural Prices, Export Sales and the CFTC report are tagged for both; Export
  Inspections grain only; CPI, PPI and EIA economic; federal holidays and CME closures holiday. Times are shown in Central; events with no known hour (EIA STEO / PSM, holidays) show date only.
- **Read live (scripts are allowed):** USDA NASS (its .ics; ~45 of ~92 titles kept in `GRAIN_NASS` / `LIVESTOCK_NASS`), EIA (four schedule pages: the Weekly Petroleum Status Report incl. ethanol, Wed 10:30 ET
  except the holiday-exception table; Natural Gas Storage, Thu 10:30 ET, same; STEO and Petroleum Supply Monthly = the page's "Release Date / Next Release Date" only, so one or two dates ahead),
  CFTC Commitments of Traders (its release-schedule page, 3:30 PM ET, `*` = holiday delay). EIA's weekly dates are generated only to the end of the last year its exception table covers (`eia_weekly`: each exception
  REPLACES the standard day nearest to it), because later holiday weeks would be guessed.
- **TYPED in `report_schedule_data.py` (their sites answer a script with 403; read in a browser 2026-11-12; refresh by hand):** WASDE 2026 + 2027 (usda.gov), CPI and PPI reference Oct 2026 - Nov 2027 (bls.gov),
  FAS Weekly Export Sales dates Nov 13 - Dec 31 2026 (fas.usda.gov/data/scheduled-reports lists only ~2 months), CME's normal day-session hours and the Thanksgiving 2026 early close (cmegroup.com). The footnote turns amber
  under 60 days from the end of WASDE/CPI/PPI.
- **Rule-based, flagged "Usual schedule" in the note (120 days ahead at most):** Export Sales after the typed dates = FAS's own rule (Thursday 8:30 ET; Friday when a federal holiday falls the previous Friday or Mon-Thu of that
  week; checked against FAS's Nov 13 and Nov 27); Export Inspections = Mondays 11:00 ET, Tuesday after a Monday holiday (USDA publishes no calendar for it).
- **Holidays.** Federal holidays are computed from the statute with the observed rule (Sat -> Fri, Sun -> Mon); the 2026 list equals NASS's own HOLIDAY rows exactly (tested). CME grain and livestock futures are closed on those
  less Columbus Day and Veterans Day (they trade), plus Good Friday; a New Year's Day on a Saturday closes nothing (2028: federal Dec 31 2027, CME open), the same rule as `grain_calendar.py` in the basis tracker. **CME holiday hours are typed from CME's own page for every holiday through 2027** (`CME_HOLIDAY_HOURS`, read 2026-11-12, Grains and Livestock groups): the page
  takes the date in its address (`cmegroup.com/trading-hours.html#tradeDate=2027-01-18`) but only reads it on a full page LOAD (navigate, then reload; a hash change or a script click on the holiday chips does nothing).
  What they say: Thanksgiving closed, the Friday after and Christmas Eve 2026 close 12:05 PM CT; the Monday holidays (MLK, Presidents, Memorial, Labor) close the day session but the GRAIN evening session still opens
  7:00 PM CT for the next trade date (livestock reopens next morning); Independence Day 2027 (Mon Jul 5) has NO evening session, so grains resume Tue 8:30 AM CT; Good Friday, Juneteenth (Fri Jun 18 2027), Christmas (Fri Dec 24 2027) and
  New Year's Day (Fri Jan 1 2027) are closed days; New Year's Day 2028 falls on a Saturday so Fri Dec 31 2027 trades normally. CME says holiday hours are finalized about two weeks ahead and can change. 2028 closures fall
  back to a generic "CME has not published the hours" note.
- **China holidays (Kolten 2026-11-12).** The State Council General Office's holiday notices (2026 on 2025-11-04, 2027 on 2026-11-05; the full texts are on news.cn and answer a script), typed in `CHINA_HOLIDAYS` /
  `CHINA_MAKEUP_WORKDAYS`: New Year's Day, Spring Festival (9 days: Feb 15-23 2026, Feb 5-13 2027), Qingming, Labour Day, Dragon Boat (1 day in 2027: Jun 9), Mid-Autumn (Sep 15 2027), National Day (Oct 1-7), and the weekend
  make-up working days. Tagged holiday (so they show in every scope and under the Holidays pill) with a CHINA chip. A holiday is ONE event with `span_end`: `between()` counts it in any overlapping week, the week card lists it once on the
  week's first covered day, the month grid shows it on every day. The "mainland exchanges (Dalian, Zhengzhou) are normally closed, also on make-up weekend days" wording is the usual practice, not part of the State Council notice:
  the exchanges publish their own notices. A 2028 notice normally appears in November 2027: refresh then.
- **CME hours are highlighted on the week card (Kolten 2026-11-12).** Any event with `cme_alert` (a CME closure, an early close, the Monday-holiday evening-session wording, Independence Day's no-evening-session) puts a red
  "CME holiday hours this week" banner at the top of the card with the hours, and its chip reads CME CLOSED / CME HOURS (red, in the month grid too). Holidays with no CME effect (Veterans Day, Columbus Day) get no banner.
- **International (Kolten 2026-11-12: "build the international").** Canada: Statistics Canada's own JSON behind its release calendar (`schedule-key_indicators-eng.json`, scriptable, looks ahead to ~March 2027): crop reports
  (areas, production, stocks, model-based), Farm income, Canadian CPI (international only, NOT mixed into the US economic list), livestock titles if they appear; 8:30 AM ET. Brazil: CONAB's calendar PDF typed in `report_schedule_data.py`
  (grain surveys Oct 15 - Jan 14, monitoring bulletins, and its statement that crop progress comes out every Monday 7 PM Brasilia time); refresh when CONAB issues the 2027 calendar. International crop reports are tagged grain AND
  international, so they also appear on the Grain card. **Argentina is NOT included: the Buenos Aires Grain Exchange (bolsadecereales.com) sits behind a Cloudflare challenge (not bypassed) and Rosario (bcr.com.ar) shows no release
  calendar, so there is no official date to show; if Kolten pastes their schedules, add them to `report_schedule_data.py`.**
- **"This week"** is Monday-Sunday (the week ahead on a weekend). A failed live read is NOT cached: the typed and rule-based events show at once with a note, and NASS / EIA / CFTC are not asked again for 5 minutes (a good
  read is cached 6 hours for everyone). Not done: Argentina (above), the Livestock Portal (separate app), Grain Seasonal's own historical Report Calendar tab.

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
(*Option: Buy / Sell*, default Buy), and a **second option leg** can be added, with one-click *Put spread*,
*Collar* and *Call spread* buttons (`cso_qs_*` keys: a button's key must not start with `cso_st_`, whose values
the app re-assigns on every run) and the resulting strategy named for you. Unlike the Risk Analyzer it needs
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
  `crop_conditions`, which left the portal 2026-11-03) can read it. A fine-grained PAT limited to selected repos would otherwise make `apply`
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
| `apps/*/nass_cache_client.py` (domestic_production, livestock apps) | `NASS_CACHE` |
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

**Field check (beta)** used to be a page of that tile: the wrapper ran `apps/crop_conditions/app.py` with
`FIELD_CHECK_ONLY = True`. It left with Crop Conditions on 2026-11-03 (below); the wrapper only lists it while that
mirror exists, so it stays hidden until Crop Conditions is bundled again. ISA states its copyright and no other
terms, which is why the strip trials live only behind passwords. The old `apps/strip_trials/` copy is deleted.

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
