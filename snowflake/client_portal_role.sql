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

USE ROLE ACCOUNTADMIN;

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
-- Check: RSA_PUBLIC_KEY_FP must read SHA256:M0RWJ27ohKW6AqhLuUKi/9Jo/RFOZk66GwPY3lqywQs=
DESC USER CLIENT_PORTAL_SVC;

-- 3. SELECT only, on exactly the schemas the client-visible dashboards read. A schema that does not exist
--    in this account is skipped and named in the result instead of stopping the script.
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
      granted := granted || s || '  ';
    EXCEPTION
      WHEN OTHER THEN
        skipped := skipped || s || '  ';
    END;
  END FOR;
  RETURN 'GRANTED: ' || granted || ' | SKIPPED (missing?): ' || skipped;
END;
$$;

-- 4. Prove it. As the client role, a read works and a write is refused.
USE ROLE CLIENT_PORTAL_ROLE;
USE WAREHOUSE COMPUTE_WH;
SELECT COUNT(*), MAX(DATE) FROM JSA.COST_OF_CARRY.FUTURES_SETTLEMENTS;      -- should return a count and a recent date
CREATE TABLE JSA.NASS_CACHE.CLIENT_ROLE_WRITE_TEST (A INT);                 -- should FAIL: insufficient privileges
USE ROLE ACCOUNTADMIN;
SHOW GRANTS TO ROLE CLIENT_PORTAL_ROLE;                                     -- every row should be USAGE or SELECT
