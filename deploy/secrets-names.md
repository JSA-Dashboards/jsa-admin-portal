# What goes in each portal's secrets file (setting NAMES only; the values come from the Streamlit Cloud app's Settings > Secrets)

Copy each block from its own Cloud app, so the client file never contains a staff value. TOML rule: top-level keys come BEFORE any `[section]`.

## Client portal (`/srv/jsa-client/home/.streamlit/secrets.toml`), from the client app (jsa-app-client-dashboard)
`CLIENT_PASSWORD`, `USE_SNOWFLAKE`, `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER` (CLIENT_PORTAL_SVC), `SNOWFLAKE_ROLE` (CLIENT_PORTAL_ROLE), `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_PRIVATE_KEY`
(no `SNOWFLAKE_SCHEMA`), `MASSIVE_API_KEY`, `MASSIVE_S3_ACCESS_KEY`, `MASSIVE_S3_SECRET_KEY`, `NASS_API_KEY`, `MARS_API_KEY`, `EIA_API_KEY`.
NOT: `ADMIN_PASSWORD`, `GRAPH_*`, `ANTHROPIC_API_KEY`, `EDIT_PASSWORD`, `APP_PASSWORD`, `SIG_*`.

## Staff portal (`/srv/jsa-staff/home/.streamlit/secrets.toml`), from the staff app (jsatools-corporate)
Whatever that app's Secrets holds today, typically `ADMIN_PASSWORD`, the Snowflake block for ADMIN_PORTAL_SVC, `USE_SNOWFLAKE`, `MASSIVE_API_KEY`, `MASSIVE_S3_*`, `NASS_API_KEY`,
`MARS_API_KEY`, `EIA_API_KEY`, `ANTHROPIC_API_KEY`, `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` / `GRAPH_SENDER`, `EDIT_PASSWORD`/`SIG_*` where used.
