# AJPanda Octra Validator Dashboard

A safe, read-only deployment of the upstream Octra live dashboard frontend, adapted for our validator:

`oct8mvdkX3babyBsrzHYUB1cSU9a79RTbHXi7nJNfHJnUmk`

The original responsive UI is retained. A small dependency-free backend and host collector were added so the page can consume official `controls/stat.sh` output without exposing the node RPC, validator files, keys, IP addresses, or arbitrary host data.

## Security design

- Binds to `127.0.0.1:8789` by default; it is not publicly reachable.
- Collector and API use independent strict field allowlists.
- No wallet, mnemonic, private key, recovery file, config file, environment, IP address, or SSH information is returned.
- No third-party JavaScript, fonts, analytics, CDNs, or browser requests.
- Strict Content Security Policy and browser hardening headers.
- Container is read-only, non-root, capability-free, and uses `no-new-privileges`.
- The container receives only a read-only telemetry file, never the Octra node directory.
- Stale telemetry fails closed as `DEGRADED`.

The public validator address is intentionally displayed because it is already public chain identity.

## Run tests

```sh
cd /home/node/clawd/projects/octra-live-dashboard
make test
```

## Collect live status

```sh
cd /home/node/clawd/projects/octra-live-dashboard
sh ./collector.sh
```

For continuous collection, install the included hardened systemd timer:

```sh
sudo install -o root -g root -m 0755 collector.sh /usr/local/libexec/octra-dashboard-collector
sudo install -d -o octra -g octra -m 0755 /var/lib/octra/dashboard
sudo install -o root -g root -m 0644 deploy/octra-dashboard-collector.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/octra-dashboard-collector.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now octra-dashboard-collector.timer
```

## Launch locally

```sh
cd /home/node/clawd/projects/octra-live-dashboard
OCTRA_STATUS_DIR=/var/lib/octra/dashboard docker compose up -d --build
curl -fsS http://127.0.0.1:8789/healthz
```

Open `http://127.0.0.1:8789` on node3 or use an SSH tunnel. Do not expose the port directly to the internet. If remote access is later required, put it behind an authenticated reverse proxy with TLS and an IP allowlist.

## Cloudflare publication

Production publication uses a dedicated Cloudflare Tunnel at
`https://octra.ajpanda.com`. The origin stays bound to loopback and no inbound
firewall port is opened. The connector reads its token from
`/etc/octra-dashboard/cloudflared-token`; never commit or print this file.

The public site exposes only the telemetry allowlist enforced independently by
the collector and API. Cloudflare Access is not configured, so treat the
hostname as public.

## Data flow

```text
controls/stat.sh
  -> collector allowlist
  -> runtime/status.txt (read-only mount)
  -> API allowlist and derived metrics
  -> GET /api/snapshot
  -> browser dashboard
```

## Refresh and validator profiles

- The page refreshes local node telemetry every 10 seconds and the public
  validator set every 30 seconds. Refreshes are immediate when a visitor
  returns to the tab or window.
- Failed reads back off (up to five minutes) rather than stacking requests;
  the page displays a visible freshness indicator and marks unavailable data
  as degraded.
- Each observed public validator has a shareable profile at
  `/validator/<public-validator-address>`. Profiles expose only chain-observed
  set membership, weight, active-set share, recent consensus evidence, and
  this dashboard's active-set continuity observation.
- The local validator is highlighted on the explorer and its profile remains
  public, but no remote host uptime is claimed or collected.

## Upstream

UI derived from [gniwhcs/octra-live-dashboard-frontend](https://github.com/gniwhcs/octra-live-dashboard-frontend), MIT licensed.
