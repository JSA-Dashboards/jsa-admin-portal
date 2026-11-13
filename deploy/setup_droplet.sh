#!/bin/bash
# Sets up the portal droplet (see deploy/README.md). Run as root on a fresh Ubuntu 24.04:
#     ssh root@<ip> 'bash -s' < deploy/setup_droplet.sh
# Safe to re-run. It does NOT start the portals (they need their secrets first) and it leaves Caddy's config alone until
#     ssh root@<ip> 'bash -s -- --caddy' < deploy/setup_droplet.sh
# which writes the Caddyfile (clients.jpsi.com, portal.jpsi.com) and reloads Caddy: do that only after the DNS records exist,
# or Caddy will keep failing to get certificates.
set -euo pipefail

REPO_URL="https://github.com/JSA-Dashboards/jsa-admin-portal.git"
BRANCH="master"
export DEBIAN_FRONTEND=noninteractive
# A brand-new droplet runs its own first update and holds the apt lock for a few minutes: wait for it (up to 10 min) instead of failing.
APT="apt-get -o DPkg::Lock::Timeout=600"

if [ "${1:-}" = "--caddy" ]; then
    cat > /etc/caddy/Caddyfile <<'CADDY'
# JSA portals. Streamlit listens on 127.0.0.1 only; Caddy adds TLS and proxies (websockets included).
clients.jpsi.com {
	reverse_proxy 127.0.0.1:8601
	header {
		-Server
		Strict-Transport-Security "max-age=31536000"
	}
}

portal.jpsi.com {
	reverse_proxy 127.0.0.1:8602
	header {
		-Server
		Strict-Transport-Security "max-age=31536000"
	}
}
CADDY
    caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
    systemctl reload caddy
    echo "Caddy now serves clients.jpsi.com and portal.jpsi.com"
    exit 0
fi

echo "== packages"
$APT update -y
$APT install -y python3-venv python3-dev build-essential git ufw curl unattended-upgrades \
    debian-keyring debian-archive-keyring apt-transport-https gpg libgl1 libglib2.0-0
if ! command -v caddy >/dev/null; then
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
    $APT update -y
    $APT install -y caddy
fi

echo "== swap (2 GB)"
if ! swapon --show | grep -q /swapfile; then
    fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
    grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== firewall"
ufw default deny incoming
ufw default allow outgoing
ufw limit OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "== the two portals"
mkdir -p /etc/jsa-portal /srv/deploy
for who in client staff; do
    user="jsa-$who"
    id "$user" >/dev/null 2>&1 || adduser --system --group --home "/srv/$user" --shell /usr/sbin/nologin "$user"
    install -d -o "$user" -g "$user" -m 755 "/srv/$user" "/srv/$user/home" "/srv/$user/home/.streamlit"
    chmod 700 "/srv/$user/home/.streamlit"
    if [ ! -d "/srv/$user/repo/.git" ]; then
        sudo -u "$user" git clone --branch "$BRANCH" "$REPO_URL" "/srv/$user/repo"
    fi
    if [ ! -x "/srv/$user/venv/bin/python" ]; then
        sudo -u "$user" python3 -m venv "/srv/$user/venv"
    fi
    sudo -u "$user" "/srv/$user/venv/bin/pip" install --upgrade pip wheel
    sudo -u "$user" "/srv/$user/venv/bin/pip" install -r "/srv/$user/repo/requirements.txt"
done
printf 'PORT=8601\nMAIN=Client.py\n' > /etc/jsa-portal/client.env
printf 'PORT=8602\nMAIN=Home.py\n'  > /etc/jsa-portal/staff.env

cat > /etc/systemd/system/jsa-portal@.service <<'UNIT'
[Unit]
Description=JSA %i portal (Streamlit)
After=network-online.target
Wants=network-online.target

[Service]
User=jsa-%i
Group=jsa-%i
WorkingDirectory=/srv/jsa-%i/repo
Environment=HOME=/srv/jsa-%i/home
EnvironmentFile=/etc/jsa-portal/%i.env
ExecStart=/srv/jsa-%i/venv/bin/streamlit run ${MAIN} --server.port ${PORT} --server.address 127.0.0.1 --server.headless true --server.runOnSave false --browser.gatherUsageStats false
Restart=always
RestartSec=5
# a runaway page cannot take the whole droplet (and the other portal) down with it
MemoryHigh=2200M
MemoryMax=2800M
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable jsa-portal@client jsa-portal@staff

cat > /srv/deploy/update.sh <<'UPD'
#!/bin/bash
# Pull both portals' clones, reinstall requirements only if they changed, restart.
set -euo pipefail
for who in client staff; do
    user="jsa-$who"; repo="/srv/$user/repo"
    before=$(sudo -u "$user" git -C "$repo" rev-parse HEAD)
    sudo -u "$user" git -C "$repo" pull --ff-only -q
    after=$(sudo -u "$user" git -C "$repo" rev-parse HEAD)
    if [ "$before" != "$after" ] && ! sudo -u "$user" git -C "$repo" diff --quiet "$before" "$after" -- requirements.txt; then
        sudo -u "$user" "/srv/$user/venv/bin/pip" install -r "$repo/requirements.txt"
    fi
    echo "$who: $before -> $after"
    systemctl is-enabled --quiet "jsa-portal@$who" && systemctl try-restart "jsa-portal@$who"
done
UPD
chmod +x /srv/deploy/update.sh

echo
echo "Done. Next: install each portal's secrets (deploy/README.md step 4), then:"
echo "  systemctl start jsa-portal@client   # and check: curl -s 127.0.0.1:8601/_stcore/health"
echo "  (after DNS) bash -s -- --caddy < deploy/setup_droplet.sh"
