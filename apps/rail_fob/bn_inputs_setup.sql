-- One-time setup for the BN freight inputs the Rail Corridors portal saves (bn_inputs.py):
-- the secondary-market BN shuttle quotes and the monthly fuel surcharge Kolten feeds on the BN tab.
-- Run in a Snowsight worksheet as ACCOUNTADMIN (or the role that owns JSA).
--
-- Append-only: every Save inserts ONE row holding the whole input set as JSON, and the tab reads the
-- latest row. So there is no DELETE-then-INSERT race, and every change stays as history.

USE ROLE ACCOUNTADMIN;

CREATE SCHEMA IF NOT EXISTS JSA.RAIL_FOB;

CREATE TABLE IF NOT EXISTS JSA.RAIL_FOB.BN_FREIGHT_INPUTS (
    SAVED_AT TIMESTAMP_NTZ NOT NULL,   -- UTC (the portal inserts SYSDATE())
    SAVED_BY VARCHAR,
    PAYLOAD  VARCHAR NOT NULL          -- {"as_of":..., "quotes":[{period,bid,offer}], "months":[{key,fsc,cars_override}]}
);

-- If the portal's Streamlit secrets log in as ACCOUNTADMIN (the other Snowflake apps' .env files do), that's all:
-- the role already owns what it just created. ONLY if the Cloud app's SNOWFLAKE_ROLE is a different role, put its
-- name below in place of PORTAL_ROLE and run these two lines too:
-- GRANT USAGE ON SCHEMA JSA.RAIL_FOB TO ROLE PORTAL_ROLE;
-- GRANT SELECT, INSERT ON TABLE JSA.RAIL_FOB.BN_FREIGHT_INPUTS TO ROLE PORTAL_ROLE;

-- Check it exists (returns no rows until the first Save on the BN tab):
SELECT SAVED_AT, SAVED_BY, PAYLOAD FROM JSA.RAIL_FOB.BN_FREIGHT_INPUTS ORDER BY SAVED_AT DESC;
