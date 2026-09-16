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
- Signed-upgrade telemetry is collected by a separate diagnostic-only job; it
  never passes `--apply`, and paths, PIDs, config, and keys are discarded.
- Disk runway uses only used/free byte totals, keeps a bounded history, requires
  six hours of evidence, and never runs pruning, recovery, or storage commands.
- Reliability history stores only coarse health booleans, epoch, and restart
  count; it never stores validator identity, logs, paths, peers, or keys.
- Memory history stores only validator RSS, coarse host memory totals, and the
  restart counter; forecasts never bridge a process restart or expose raw
  samples to the browser.

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
sudo -iu octra sh ./transition_collector.sh
```

For continuous collection, install the included hardened systemd timer:

```sh
sudo install -o root -g root -m 0755 collector.sh /usr/local/libexec/octra-dashboard-collector
sudo install -o root -g root -m 0644 network_collector.py /usr/local/libexec/network_collector.py
sudo install -o root -g root -m 0644 storage_collector.py /usr/local/libexec/storage_collector.py
sudo install -o root -g root -m 0644 reliability_collector.py /usr/local/libexec/reliability_collector.py
sudo install -o root -g root -m 0644 memory_collector.py /usr/local/libexec/memory_collector.py
sudo install -o root -g root -m 0755 transition_collector.sh /usr/local/libexec/octra-dashboard-transition-collector
sudo install -d -o octra -g octra -m 0755 /var/lib/octra/dashboard
sudo install -o root -g root -m 0644 deploy/octra-dashboard-collector.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/octra-dashboard-collector.timer /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/octra-dashboard-transition-collector.service /etc/systemd/system/
sudo install -o root -g root -m 0644 deploy/octra-dashboard-transition-collector.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now octra-dashboard-collector.timer
sudo systemctl enable --now octra-dashboard-transition-collector.timer
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

controls/upgrade.sh (diagnostic only; never --apply)
  -> transition collector allowlist
  -> upgrade.txt (read-only mount)
  -> fail-closed GET /api/transition
  -> mainnet transition readiness panel

disk_used + disk_free (already allowlisted by collector)
  -> bounded storage-history.json (atomic, maximum 20,160 samples)
  -> conservative net-growth estimate
  -> GET /api/storage
  -> disk runway panel (observation only)

process + RPC + sync + voting + active + epoch + restart count
  -> bounded reliability-history.json (atomic, maximum 10,080 samples)
  -> GET /api/reliability
  -> 24-hour sampled reliability panel (observation only)

validator RSS + host memory totals + restart count
  -> bounded memory-history.json (atomic, maximum 10,080 samples)
  -> restart-aware growth and protected-reserve forecast
  -> GET /api/memory
  -> validator memory growth panel (observation only)
```

## Memory growth semantics

The memory panel requires at least six samples, 30 continuous minutes, and 80%
collection coverage before estimating a trend. It discards every sample before
the latest restart-counter transition so the expected RSS drop from a restart
cannot hide renewed growth. A median early/late slope is projected only when
growth exceeds 16 MiB/hour, and runway preserves the larger of 15% of host RAM
or 2 GiB available. Thresholds are critical below six hours, warning below 24,
and watch below 72. Stale or sparse evidence fails closed. The panel is an
operator observation; it never restarts the validator or initiates recovery.

## Reliability semantics

The collector retains at most seven days at a one-minute interval. The panel
summarizes the latest 24 hours and requires six hours of evidence before it can
report healthy. It shows observed health, voting observations, collection
coverage, the current healthy streak, and positive restart-counter changes.
It also proves that the observed epoch is advancing and degrades after 15
continuous minutes without a change, even if the process still reports healthy
and voting. Observation gaps produce an unknown state instead of a false stall.
Missing coverage and stale evidence fail closed. These are local sampled
observations—not independently measured uptime, proof of rewards, or an SLA.

## Disk runway semantics

The collector retains at most 14 days at a one-minute collection interval. The
dashboard requires four valid samples spanning at least six hours before it
shows a forecast. It estimates recent net growth using medians from the early
and late halves of the evidence window, then projects to a safety reserve equal
to the larger of 15% capacity or 100 GiB. Sparse, stale, malformed, or non-
growing evidence never produces a deadline. The panel does not recommend or
execute pruning because recovery and storage procedures remain release-specific.

## Transition readiness semantics

The transition panel checks the signed release sequence, diagnostic pass gate,
binary/source/runtime matches, RPC, head lag, voting, and validator-set
membership. When an upgrade is required, it derives a deadline watch from the
signed marker expiry: more than 24 hours is watch, 24 hours is warning, six
hours is critical, and an expired or malformed deadline is an explicit blocker.
The browser refreshes this status every minute while the diagnostic collector
updates the underlying signed evidence every five minutes. Missing or stale
evidence is a blocker. The panel intentionally
hard-codes `cutover_authorized: false`: even when every upgrade gate passes,
operators must wait for the official signed mainnet configuration and an
explicit cutover decision.

The transition collector runs every five minutes because the diagnostic may
fetch the official repository/release marker. Its systemd service therefore
allows outbound network access while retaining a read-only system, no-new-
privileges, private devices/tmp, and a single writable telemetry directory.

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
