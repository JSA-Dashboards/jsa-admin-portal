-- Read-only Snowflake login for the CLIENT portal (Client.py on Streamlit Cloud).
-- Run in Snowsight as ACCOUNTADMIN, one block at a time (the grants block is a Snowflake Scripting block).
--
-- WHY: the client app's controls are hidden in code, but this makes "clients cannot write" true in the
-- database too. CLIENT_PORTAL_ROLE can SELECT and nothing else: no INSERT, UPDATE, DELETE, TRUNCATE, DDL.
-- The staff portal keeps ADMIN_PORTAL_SVC / ADMIN_PORTAL_ROLE untouched.
--
-- ROLLBACK, if a client page needs something this role lacks: put SNOWFLAKE_USER / SNOWFLAKE_ROLE /
-- SNOWFLAKE_PRIVATE_KEY in the CLIENT app's Secrets back to the ADMIN_PORTAL_SVC values and reboot it.
-- The private key is NOT in this file: it is in the client app's Secrets only.
--
-- RUN LOG (2026-11-09): created and verified (fingerprint matched; CREATE TABLE and INSERT as CLIENT_PORTAL_ROLE both refused;
-- reads fine; SHOW GRANTS shows only USAGE and SELECT: 106 tables + 5 views, 4 databases, 15 schemas, 1 warehouse). The pre-check
-- found database-level FUTURE grants for AG_DQ_READER, JSA_ANALYST and JSA_EDITOR; only JSA.BOXED_BEEF and JSA.RAIL_FOB had no
-- schema-level future grants of their own, so schema-level copies of those three roles' grants were added there and nowhere else
-- (a schema-level future grant makes Snowflake ignore the database-level ones in that schema). The user inherits PUBLIC's
-- privileges (create rights in SNOWFLAKE_APPS.PUBLIC and similar): accepted, revoking them would affect every user.

USE ROLE ACCOUNTADMIN;

-- 0. PRE-CHECKS (read-only; run these first and look at the results).
--    (a) A schema-level FUTURE grant makes Snowflake ignore database-level future grants on that object type in
--        that schema. This script adds schema-level future grants for CLIENT_PORTAL_ROLE in the 15 schemas below, so
--        if any role (ADMIN_PORTAL_ROLE, an ETL role, SYSADMIN ...) currently gets NEW tables there through a
--        database-level future grant, it would quietly stop. Any rows returned here need the same schema-level future
--        grants added for that role in the same schemas BEFORE running section 3 (send the rows to Claude).
SHOW FUTURE GRANTS IN DATABASE JSA;
SHOW FUTURE GRANTS IN DATABASE EXPORTS;
SHOW FUTURE GRANTS IN DATABASE RIVER_FOB;
SHOW FUTURE GRANTS IN DATABASE YIELD_REPORTS;
--    (b) Every user also inherits whatever is granted to PUBLIC. It should be nothing beyond read access.
SHOW GRANTS TO ROLE PUBLIC;

-- 1. The role: warehouse use plus (below) SELECT on the schemas the client dashboards read.
CREATE ROLE IF NOT EXISTS CLIENT_PORTAL_ROLE
  COMMENT = 'Client portal (Client.py): read-only on the schemas the client dashboards read';
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE CLIENT_PORTAL_ROLE;
GRANT ROLE CLIENT_PORTAL_ROLE TO ROLE SYSADMIN;

-- 2. The service user: key-pair login only (no password, no MFA prompt), like the other portal users.
CREATE USER IF NOT EXISTS CLIENT_PORTAL_SVC
  TYPE = SERVICE
  DEFAULT_ROLE = CLIENT_PORTAL_ROLE
  DEFAULT_WAREHOUSE = COMPUTE_WH
  DEFAULT_NAMESPACE = JSA
  RSA_PUBLIC_KEY = 'MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA0D4eehHkwD9BropY+6Y0YTqbGMIVDMU/RYjqnD8/z+N8Y4Gm3nZ55mivBjUkU9cpjFOa0oPovryEco4o/E3iXqSR996TYSYJvHNztCc2td5Cp04fdXbv70ZMSedHos/RS/kmTpFAMkb0s0+wHrwYHcLflieXB9xE53kCg9v+ZHJ5eqgLQRj5dpe9F+UbHBAHjHneSyrYqoQoknlgJbzr7ynX382c9LrqL0fYxbAWAg8IaUyL22rJTWFFeNa5/Ved6K0rZ1N472MTD8jOSA8ugwLKwh9TlHSad3sVRKW6bHv/11iAWFVwppm7S8a1mmDnk3gAXd6unYNwgPdAFMD0zwIDAQAB'
  COMMENT = 'Client portal (Streamlit Cloud): read-only, key-pair login';
GRANT ROLE CLIENT_PORTAL_ROLE TO USER CLIENT_PORTAL_SVC;
-- No secondary roles: this login must act as CLIENT_PORTAL_ROLE only, never as anything else it might be granted.
ALTER USER CLIENT_PORTAL_SVC SET DEFAULT_SECONDARY_ROLES = ();
-- Check: RSA_PUBLIC_KEY_FP must read SHA256:M0RWJ27ohKW6AqhLuUKi/9Jo/RFOZk66GwPY3lqywQs=
DESC USER CLIENT_PORTAL_SVC;

-- 3. SELECT only, on exactly the schemas the client-visible dashboards read. A schema that does not exist
--    in this account (or one this role cannot grant on) is skipped and named, with Snowflake's error text, in the
--    result instead of stopping the script. A tile that later says "not authorized" for an object type not
--    covered here (a function or procedure, say) needs a USAGE grant on it.
EXECUTE IMMEDIATE $$
DECLARE
  targets ARRAY DEFAULT ARRAY_CONSTRUCT(
    'JSA.NASS_CACHE', 'JSA.CME_FEEDER_CATTLE', 'JSA.BASIS_TRACKER', 'JSA.COST_OF_CARRY', 'JSA.CFTC_COT',
    'JSA.BEEF_TRIMMINGS', 'JSA.BOXED_BEEF', 'JSA.EIA_ETHANOL_CACHE', 'JSA.FLASH_SALES', 'JSA.RAIL_FOB',
    'JSA.FARMER_SURVEY', 'JSA.RISK_ANALYZER',
    'EXPORTS.PUBLIC', 'RIVER_FOB.PUBLIC', 'YIELD_REPORTS.PUBLIC');
  n INTEGER;
  s STRING;
  db STRING;
  granted STRING DEFAULT '';
  skipped STRING DEFAULT '';
BEGIN
  n := ARRAY_SIZE(targets);
  FOR i IN 0 TO n - 1 DO
    s := GET(targets, i)::STRING;
    db := SPLIT_PART(s, '.', 1);
    BEGIN
      EXECUTE IMMEDIATE 'GRANT USAGE ON DATABASE ' || db || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT USAGE ON SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON ALL TABLES IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON ALL VIEWS IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON FUTURE TABLES IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON FUTURE VIEWS IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      -- the other readable object types (harmless where a schema has none)
      EXECUTE IMMEDIATE 'GRANT SELECT ON ALL DYNAMIC TABLES IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON FUTURE DYNAMIC TABLES IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON ALL MATERIALIZED VIEWS IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON FUTURE MATERIALIZED VIEWS IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON ALL EXTERNAL TABLES IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      EXECUTE IMMEDIATE 'GRANT SELECT ON FUTURE EXTERNAL TABLES IN SCHEMA ' || s || ' TO ROLE CLIENT_PORTAL_ROLE';
      granted := granted || s || '  ';
    EXCEPTION
      WHEN OTHER THEN
        skipped := skipped || s || ' (' || SQLERRM || ')  ';
    END;
  END FOR;
  RETURN 'GRANTED: ' || granted || ' | SKIPPED (with the reason): ' || skipped;
END;
$$;

-- 4. Prove it. As the client role, a read works and a write is refused.
USE ROLE CLIENT_PORTAL_ROLE;
USE WAREHOUSE COMPUTE_WH;
SELECT COUNT(*), MAX(DATE) FROM JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS;      -- should return a count and a recent date
CREATE TABLE JSA.NASS_CACHE.CLIENT_ROLE_WRITE_TEST (A INT);                 -- should FAIL: insufficient privileges (schema level)
INSERT INTO JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS
  SELECT * FROM JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS LIMIT 0;               -- should FAIL: insufficient privileges (existing table; LIMIT 0 inserts nothing even if it worked)
SELECT CURRENT_ROLE(), CURRENT_SECONDARY_ROLES();                            -- CLIENT_PORTAL_ROLE and no secondary roles
USE ROLE ACCOUNTADMIN;
SHOW GRANTS TO ROLE CLIENT_PORTAL_ROLE;                                     -- every row should be USAGE or SELECT
