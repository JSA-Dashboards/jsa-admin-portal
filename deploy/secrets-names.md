# What goes in each portal's secrets file (setting NAMES only; the values come from the Streamlit Cloud app's Settings > Secrets)

Copy each block from its own Cloud app, so the client file never contains a staff value. TOML rule: top-level keys come BEFORE any `[section]`.

## Client portal (`/srv/jsa-client/home/.streamlit/secrets.toml`), from the client app (jsa-app-client-dashboard)
`CLIENT_PASSWORD`, `USE_SNOWFLAKE`, `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER` (CLIENT_PORTAL_SVC), `SNOWFLAKE_ROLE` (CLIENT_PORTAL_ROLE), `SNOWFLAKE_WAREHOUSE`, `SNOWFLAKE_PRIVATE_KEY`
(no `SNOWFLAKE_SCHEMA`), `MASSIVE_API_KEY`, `MASSIVE_S3_ACCESS_KEY`, `MASSIVE_S3_SECRET_KEY`, `NASS_API_KEY`, `MARS_API_KEY`, `EIA_API_KEY`.
NOT: `ADMIN_PASSWORD`, `GRAPH_*`, `ANTHROPIC_API_KEY`, `EDIT_PASSWORD`, `APP_PASSWORD`, `SIG_*`.

### Microsoft sign-in (optional; the client portal only; off until the `[auth]` block exists)
Top-level keys, ABOVE the `[auth]` header (TOML puts every key under the last header above it):
- `SIGNIN_PASSWORD_FALLBACK = true` keeps `CLIENT_PASSWORD` working next to the Sign in button while clients move over; leave it out and, once `[auth]` is complete, the shared password opens nothing.
- `SIGNIN_ALLOWED_EMAILS = "a@x.com, b@y.com"` (or a TOML list): addresses allowed without a row in `JSA.PORTAL_ACCESS.USERS`, for the first tests and as a way in if Snowflake is down. Remove it once the table is in use.

Then the section, all five keys required (a blank or `<placeholder>` value leaves sign-in OFF):
```
[auth]
redirect_uri = "https://clients.jpsi.com/oauth2callback"
cookie_secret = "<a long random string>"
client_id = "<Application (client) ID from the Entra External ID app registration>"
client_secret = "<the client secret VALUE>"
server_metadata_url = "<the app's OpenID Connect metadata document URL: https://<name>.ciamlogin.com/<tenant id>/v2.0/.well-known/openid-configuration>"
```
The redirect address must also be registered, exactly, on the app registration. The Streamlit Cloud client app needs its own `redirect_uri` (`https://jsa-app-client-dashboard.streamlit.app/oauth2callback`) and its own `cookie_secret`. The people allowed are managed on the staff portal's **Portal Access** page (table created by `snowflake/portal_access.sql`).

## Staff portal (`/srv/jsa-staff/home/.streamlit/secrets.toml`), from the staff app (jsatools-corporate)
Whatever that app's Secrets holds today, typically `ADMIN_PASSWORD`, the Snowflake block for ADMIN_PORTAL_SVC, `USE_SNOWFLAKE`, `MASSIVE_API_KEY`, `MASSIVE_S3_*`, `NASS_API_KEY`,
`MARS_API_KEY`, `EIA_API_KEY`, `ANTHROPIC_API_KEY`, `GRAPH_TENANT_ID` / `GRAPH_CLIENT_ID` / `GRAPH_CLIENT_SECRET` / `GRAPH_SENDER`, `EDIT_PASSWORD`/`SIG_*` where used.
