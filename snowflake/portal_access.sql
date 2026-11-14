-- The portal access list: who may sign in to the CLIENT portal with Microsoft sign-in (shared/signin.py).
-- Run in Snowsight as ACCOUNTADMIN, one block at a time. NOT RUN YET (written 2026-11-13).
--
-- JSA.PORTAL_ACCESS.USERS holds one row per person (email address, lower case):
--   ROLE   'client' (client portal) or 'staff' (also opens the client portal; reserved for the staff portal later)
--   ACTIVE FALSE switches a person off without deleting the row
-- The CLIENT portal's role can only READ it (and asks about one address at a time); the STAFF portal's Portal Access
-- page is the only writer. Nothing here touches the existing grants.
--
-- ROLLBACK: DROP SCHEMA JSA.PORTAL_ACCESS;  (the portals fall back to the SIGNIN_ALLOWED_EMAILS secret, then to nobody.)

USE ROLE ACCOUNTADMIN;

CREATE SCHEMA IF NOT EXISTS JSA.PORTAL_ACCESS
  COMMENT = 'Who may sign in to the portals (shared/signin.py in jsa-admin-portal)';

CREATE TABLE IF NOT EXISTS JSA.PORTAL_ACCESS.USERS (
  EMAIL      VARCHAR       NOT NULL,                         -- lower case, one row per address (the app MERGEs on it)
  ROLE       VARCHAR       NOT NULL DEFAULT 'client',        -- 'client' | 'staff'
  NAME       VARCHAR,
  NOTE       VARCHAR,                                        -- e.g. the client company
  ACTIVE     BOOLEAN       NOT NULL DEFAULT TRUE,
  ADDED_AT   TIMESTAMP_NTZ DEFAULT SYSDATE(),
  ADDED_BY   VARCHAR,
  UPDATED_AT TIMESTAMP_NTZ DEFAULT SYSDATE(),
  PRIMARY KEY (EMAIL)                                        -- informational only: Snowflake does not enforce it
);

-- Client portal: read only.
GRANT USAGE ON SCHEMA JSA.PORTAL_ACCESS TO ROLE CLIENT_PORTAL_ROLE;
GRANT SELECT ON TABLE JSA.PORTAL_ACCESS.USERS TO ROLE CLIENT_PORTAL_ROLE;

-- Staff portal: the Portal Access page adds, switches off and removes people.
GRANT USAGE ON SCHEMA JSA.PORTAL_ACCESS TO ROLE ADMIN_PORTAL_ROLE;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE JSA.PORTAL_ACCESS.USERS TO ROLE ADMIN_PORTAL_ROLE;

-- CHECK (run as ACCOUNTADMIN): the client role must show USAGE + SELECT only, the admin role USAGE + the four table rights.
SHOW GRANTS ON TABLE JSA.PORTAL_ACCESS.USERS;
SHOW GRANTS ON SCHEMA JSA.PORTAL_ACCESS;

-- FIRST PERSON (optional; the Portal Access page does the same): yourself, to test.
-- INSERT INTO JSA.PORTAL_ACCESS.USERS (EMAIL, ROLE, NAME, NOTE, ADDED_BY)
--   VALUES ('someone@example.com', 'client', 'Test User', 'test', 'Kolten');
