-- ============================================================================
-- One-time setup: GitHub Git integration + Streamlit-in-Snowflake hosting
-- for rail-fob-portal (koltenpostin93-blip/rail-fob-portal, public, branch
-- master). Run this in a Snowsight worksheet as a role with
-- CREATE INTEGRATION / CREATE NETWORK RULE privileges (ACCOUNTADMIN, or a
-- custom role granted those specifically).
--
-- Before running: replace the REPLACE_ME_* placeholders. Never commit this
-- file back to the repo with real values filled in — the repo is public.
--
-- Updated 2026-08-27 to cover everything added since the first pass
-- (2026-08-25, BASIS_DATABASE_URL only): a second Supabase project
-- (RIVER_DATABASE_URL, for the CN tab's CIF netback), the optional USDA
-- app token (Shipments tab), and the extra Python deps (pandas/numpy/
-- pyarrow/plotly/requests — all in environment.yml already).
-- ============================================================================

USE ROLE ACCOUNTADMIN;

-- 1. Database/schema to hold this app (reuse across future app migrations —
--    add a schema per app rather than a new database each time).
CREATE DATABASE IF NOT EXISTS JSA_APPS;
CREATE SCHEMA IF NOT EXISTS JSA_APPS.RAIL_FOB;
USE DATABASE JSA_APPS;
USE SCHEMA RAIL_FOB;

-- 2. Warehouse to run the app on. XSMALL + short auto-suspend keeps this
--    close to free for a low-traffic internal tool.
CREATE WAREHOUSE IF NOT EXISTS APPS_WH
  WAREHOUSE_SIZE = XSMALL
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;

-- 3. GitHub API integration — public repo, no auth/credentials needed.
--    API_ALLOWED_PREFIXES scopes this to your GitHub account; reuse it for
--    future repos under the same account instead of creating a new one.
CREATE OR REPLACE API INTEGRATION jsa_github_api
  API_PROVIDER = git_https_api
  API_ALLOWED_PREFIXES = ('https://github.com/koltenpostin93-blip')
  ENABLED = TRUE;

-- 4. Git repository object cloning rail-fob-portal into Snowflake.
CREATE OR REPLACE GIT REPOSITORY rail_fob_repo
  API_INTEGRATION = jsa_github_api
  ORIGIN = 'https://github.com/koltenpostin93-blip/rail-fob-portal.git';

-- Pull the current commit down; re-run this any time the repo updates —
-- Snowflake does NOT auto-sync a Git repository object. There's also a
-- "Pull" button in Snowsight under the app's Files tab, but this FETCH is
-- the CLI-equivalent "reboot" step you'll want after every future push.
ALTER GIT REPOSITORY rail_fob_repo FETCH;

-- Sanity check — should list app.py, environment.yml, requirements.txt,
-- freight_data.py, rail_data.py, river_data.py, shipment_data.py,
-- rail_corridors.py, data/rail_data.parquet, assets/, etc.
LS @rail_fob_repo/branches/master/;

-- 5. Network rules for every external host this app's Python backend calls
--    directly (NOT the same as things that only load client-side in the
--    browser, like the Map tab's CN GeoMapGuide iframe — that needs no rule
--    here at all, it's an iframe src, not a server-side request).
--    5a. basis-tracker's Supabase (BASIS_DATABASE_URL) — rail_fob bids.
CREATE OR REPLACE NETWORK RULE basis_supabase_egress_rule
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('aws-1-ca-central-1.pooler.supabase.com:5432');

--    5b. River FOB Portal's Supabase (RIVER_DATABASE_URL) — Corn/Soybean CIF
--        NOLA, feeds the CN tab's FOB netback. Different project, different
--        region — a separate rule since the host differs.
CREATE OR REPLACE NETWORK RULE river_supabase_egress_rule
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('aws-1-us-east-1.pooler.supabase.com:5432');

--    5c. OPTIONAL — only needed if you actually plan to click "Refresh from
--        live API" on the Shipments tab from inside Snowflake (the bundled
--        data/rail_data.parquet works fine without this). USDA's AMS API is
--        plain HTTPS.
CREATE OR REPLACE NETWORK RULE usda_api_egress_rule
  MODE = EGRESS
  TYPE = HOST_PORT
  VALUE_LIST = ('agtransport.usda.gov:443');

-- 6. The DB connection strings as Snowflake secrets — never plaintext in
--    code or in this file once filled in. Paste the real values (from
--    rail-fob-portal/.env locally) in place of the REPLACE_ME_* placeholders
--    below, run it, then clear it from your worksheet/history if you're on
--    a shared account.
CREATE OR REPLACE SECRET rail_fob_basis_db_secret
  TYPE = GENERIC_STRING
  SECRET_STRING = 'REPLACE_ME_WITH_YOUR_BASIS_DATABASE_URL';

CREATE OR REPLACE SECRET rail_fob_river_db_secret
  TYPE = GENERIC_STRING
  SECRET_STRING = 'REPLACE_ME_WITH_YOUR_RIVER_DATABASE_URL';

-- OPTIONAL — only if you have a real USDA app token and want higher API
-- rate limits for the live-refresh button. Skip this + drop it from the
-- SECRETS list below (and the usda_api_egress_rule above) if you don't.
-- CREATE OR REPLACE SECRET rail_fob_usda_token_secret
--   TYPE = GENERIC_STRING
--   SECRET_STRING = 'REPLACE_ME_WITH_YOUR_USDA_APP_TOKEN';

-- 7. External access integration tying the network rules + secrets together
--    — this is what CREATE STREAMLIT references to let the app dial out.
--    Drop usda_api_egress_rule from ALLOWED_NETWORK_RULES if you skipped
--    step 5c/6's optional USDA token secret.
CREATE OR REPLACE EXTERNAL ACCESS INTEGRATION rail_fob_egress
  ALLOWED_NETWORK_RULES = (basis_supabase_egress_rule, river_supabase_egress_rule,
                            usda_api_egress_rule)
  ALLOWED_AUTHENTICATION_SECRETS = (rail_fob_basis_db_secret, rail_fob_river_db_secret)
  ENABLED = TRUE;

-- 8. The Streamlit app itself, sourced directly from the Git repo clone.
--    SECRETS maps each Snowflake secret to the name each *_data.py module
--    looks up via _snowflake.get_generic_secret_string(...) when the plain
--    env var isn't set (all three of rail_data.py/river_data.py's _url()
--    and app.py's USDA_APP_TOKEN lookup have this fallback wired in).
CREATE OR REPLACE STREAMLIT rail_fob_sheet
  FROM @rail_fob_repo/branches/master/
  MAIN_FILE = 'app.py'
  QUERY_WAREHOUSE = APPS_WH
  EXTERNAL_ACCESS_INTEGRATIONS = (rail_fob_egress)
  SECRETS = ('BASIS_DATABASE_URL' = rail_fob_basis_db_secret,
             'RIVER_DATABASE_URL' = rail_fob_river_db_secret);
             -- add  , 'USDA_APP_TOKEN' = rail_fob_usda_token_secret  here too
             -- if you created that optional secret in step 6.

-- 9. Let your own role (or a team role) open the app if you're not already
--    using ACCOUNTADMIN day to day.
-- GRANT USAGE ON STREAMLIT rail_fob_sheet TO ROLE <your_role>;

-- Done — find the app under Projects > Streamlit in Snowsight, or grab its
-- shareable URL from SHOW STREAMLITS;
SHOW STREAMLITS LIKE 'rail_fob_sheet';

-- ============================================================================
-- Known unknowns (can't be verified from outside a live Snowflake account —
-- test these once the app is up, and ping back if any of them misbehave):
--
-- * Map tab: the CN GeoMapGuide embed is a plain iframe (client-side, no
--   network rule needed) — but Snowsight's own frame may block third-party
--   iframes inside it depending on your account's settings. If it's blank,
--   the "open in new tab" fallback link on that tab still works regardless.
-- * Every table's copy/PNG-download buttons use `st.components.v1.html`
--   (already flagged as deprecated by Streamlit itself, unrelated to this
--   migration) — should render the same in SiS since it's client-side, but
--   worth a spot-check across a few tabs after first load.
-- * Re-syncing after a future GitHub push: re-run step 4's
--   `ALTER GIT REPOSITORY rail_fob_repo FETCH;` (or use Snowsight's "Pull"
--   button on the app's Files tab) — this is the SiS equivalent of
--   Streamlit Community Cloud's "reboot app" step.
-- ============================================================================
