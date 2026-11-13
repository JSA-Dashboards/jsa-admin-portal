# Self-hosting the portals on their own server (clients.jpsi.com and portal.jpsi.com)

Kolten 2026-11-12: "make the portal link associated with JPSI.com", chose to **self-host** both portals instead of a redirect or an embed,
at **`clients.jpsi.com`** (the client portal, main file `Client.py`) and **`portal.jpsi.com`** (the staff portal, main file `Home.py`).
Streamlit Community Cloud cannot serve an app on a custom domain, so the same code runs on a droplet of its own behind Caddy.
The Streamlit Cloud apps (`jsa-app-client-dashboard.streamlit.app`, `jsatools-corporate.streamlit.app`) stay up as the fallback until each new name has been used for a while.

## Why a NEW droplet, not the old one
The old droplet (the basis-tracker / WhatsApp one) has 2 GB of RAM and 1 vCPU and already uses ~1.1 GB (WhatsApp bridge, scrapers, River FOB email, the admin portal's per-dashboard copies);
one portal process alone can use 1-2.5 GB once its tabs are opened. It also holds every other secret, which a public web server should not sit next to
(the River FOB API got its own droplet for the same reason). Start with **Ubuntu 24.04, 2 vCPU / 4 GB RAM (about $24/month), NYC1, the same SSH key**; resizing a droplet is a
couple of clicks, and `setup_droplet.sh` adds 2 GB of swap.

## What runs where
| | client portal | staff portal |
|---|---|---|
| name | `clients.jpsi.com` | `portal.jpsi.com` |
| main file | `Client.py` | `Home.py` |
| OS user | `jsa-client` | `jsa-staff` |
| port (127.0.0.1 only) | 8601 | 8602 |
| code | `/srv/jsa-client/repo` (its own clone) | `/srv/jsa-staff/repo` |
| venv | `/srv/jsa-client/venv` | `/srv/jsa-staff/venv` |
| secrets | `/srv/jsa-client/home/.streamlit/secrets.toml` (0600) | `/srv/jsa-staff/home/.streamlit/secrets.toml` (0600) |
| systemd | `jsa-portal@client` | `jsa-portal@staff` |

The two portals are separate users with separate clones and separate secrets files, so the client process can never read the staff secrets (`ADMIN_PASSWORD`, `GRAPH_*`, `ANTHROPIC_API_KEY`,
the editor's Snowflake key): that is the same wall the two Streamlit Cloud apps have. Streamlit listens on 127.0.0.1 only; Caddy terminates TLS (Let's Encrypt, automatic) and proxies,
websockets included. The firewall allows 22 (rate-limited), 80 and 443 only.

## Order of work
1. **Kolten creates the droplet** (spec above, SSH key `basis-tracker-droplet`, name e.g. `jsa-portals`) and sends its IP.
2. **IT adds two A records**, `clients.jpsi.com` and `portal.jpsi.com`, both to that IP, DNS only (no proxy), TTL 300. Same request as `api.jpsi.com` (a draft can be made from the 2026-11-10 one).
3. `ssh root@<ip> 'bash -s' < deploy/setup_droplet.sh` : users, swap, firewall, Caddy, clones, venvs, systemd units. Safe to re-run. It does NOT start the portals (no secrets yet) and does not touch Caddy's config until `--caddy`.
4. **Secrets**, from each Streamlit Cloud app's Settings > Secrets (never typed into chat): copy a block to the clipboard and install it from the PC without printing it:
   ```
   Get-Clipboard -Raw | ssh root@<ip> "sed '1s/^\xEF\xBB\xBF//' | tr -d '\r' | install -m 600 -o jsa-client -g jsa-client /dev/stdin /srv/jsa-client/home/.streamlit/secrets.toml"
   Get-Clipboard -Raw | ssh root@<ip> "sed '1s/^\xEF\xBB\xBF//' | tr -d '\r' | install -m 600 -o jsa-staff -g jsa-staff /dev/stdin /srv/jsa-staff/home/.streamlit/secrets.toml"
   ```
   The `sed` / `tr` strip the byte-order mark and carriage returns that Windows PowerShell adds when it pipes text: with the BOM left in, the FIRST line (`CLIENT_PASSWORD`) is not read and the TOML
   does not parse (hit on 2026-11-13). Check the result by names only, never `grep` the key lines (a private key's body lines would print):
   `ssh root@<ip> 'python3 -c "import tomllib; print(sorted(tomllib.load(open(\"/srv/jsa-client/home/.streamlit/secrets.toml\",\"rb\"))))"'`.
   Names to expect in each block: `secrets-names.md`. The client block is the CLIENT app's Secrets (read-only Snowflake login `CLIENT_PORTAL_SVC`, role `CLIENT_PORTAL_ROLE`); the staff block is the staff app's.
   The live client app's Secrets also carry a few settings the client portal does not use (`ANTHROPIC_API_KEY`, `WA_SERVICE_URL`, `WA_API_KEY`, `TDM_PASSWORD`): leave them out of the server copy
   (filter the lines before sending). Never copy a block from another app: the Livestock Portal's has `PORTAL_PASSPHRASE` / `ACCOUNTADMIN` and must not reach this server.
5. `systemctl start jsa-portal@client` and check `curl -s 127.0.0.1:8601/_stcore/health` (`ok`). Then `bash setup_droplet.sh --caddy` once DNS resolves, and open `https://clients.jpsi.com`.
6. Run the same checks as a client (password gate, price strip, a few tiles), watch `free -m` and `journalctl -u jsa-portal@client` for a day, then do the staff portal the same way.
7. Only then tell clients the new address. Keep the Streamlit Cloud apps for a while as the fallback (and consider turning their keep-alive off later).

## Day to day
- **Deploy** a change: push to GitHub as now, then `ssh root@<ip> /srv/deploy/update.sh` (pulls both clones, reinstalls requirements only when `requirements.txt` changed, restarts both portals).
  Streamlit Cloud redeployed on push by itself; this server does not, on purpose (a restart drops everyone's session). An every-few-minutes timer can be added if that is wanted.
- **Logs** `journalctl -u jsa-portal@client -f`; Caddy: `journalctl -u caddy`.
- **Restart** `systemctl restart jsa-portal@client`.
- **Memory** if `free -m` shows swap in use all day, resize the droplet.

## Things that change compared with Streamlit Cloud (check each)
- No automatic Reboot button: `systemctl restart`. `st.cache_data` lives in the process, so a restart clears it (the keep-alive job is not needed).
- The apps' Snowflake, Massive, EIA and other keys are IP-open today (Streamlit Cloud's addresses vary), so nothing needs adding to a network policy; if a policy exists for a service user, add this droplet's IP.
- Local files an app writes (caches, `logs/`) go inside that user's clone; check for permission errors in the journal after first use.
- `pip` builds: the requirements need wheels for Python 3.12 (Ubuntu 24.04's default); kaleido 0.2.1 and pymupdf install as wheels. If a package fails, `setup_droplet.sh` stops with its error.
- The public repo is cloned over https (no token). Mirrored apps are committed in it, so no private-repo access is needed on this server.
