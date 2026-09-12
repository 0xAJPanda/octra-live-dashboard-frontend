#!/bin/sh
set -eu

NODE_DIR=${OCTRA_NODE_DIR:-/opt/octra/libv_litecore}
STATUS_PATH=${OCTRA_STATUS_PATH:-"$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)/runtime/status.txt"}
STATUS_DIR=$(dirname -- "$STATUS_PATH")

mkdir -p "$STATUS_DIR"
TEMP_STATUS=$(mktemp "$STATUS_DIR/.status.XXXXXX")
trap 'rm -f "$TEMP_STATUS"' EXIT HUP INT TERM

if [ "$(id -un)" = "octra" ]; then
  (cd "$NODE_DIR" && sh controls/stat.sh)
else
  sudo -n -u octra -- sh -c 'cd "$1" && sh controls/stat.sh' sh "$NODE_DIR"
fi | awk '
BEGIN {
  split("address role process restarts rpc state_sync epoch head_epoch txid_hi accounts voting voting_reason round round_step round_peers p2p_connected p2p_known consensus_peers peer_max_lag validator_active validator_scheduled validator_activation_epoch validator_next_set_epoch validator_enrollment validator_bond validator_bonded_epoch validator_ready_epoch cpu rss disk_used disk_free", fields, " ")
  for (i in fields) allowed[fields[i]] = 1
}
($1 in allowed) && $2 == "=" { print }
' > "$TEMP_STATUS"

# Append only coarse, non-sensitive host telemetry needed by the UI.
awk '/^MemTotal:/ { print "dashboard_memory_total_bytes = " $2 * 1024 } /^MemAvailable:/ { print "dashboard_memory_available_bytes = " $2 * 1024 }' /proc/meminfo >> "$TEMP_STATUS"
awk '{ print "dashboard_load_1m = " $1 }' /proc/loadavg >> "$TEMP_STATUS"
awk '{ print "dashboard_host_uptime_seconds = " int($1) }' /proc/uptime >> "$TEMP_STATUS"

chmod 0644 "$TEMP_STATUS"
mv "$TEMP_STATUS" "$STATUS_PATH"
trap - EXIT HUP INT TERM

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
STORAGE_HISTORY_PATH=${OCTRA_STORAGE_HISTORY_PATH:-"$STATUS_DIR/storage-history.json"}
python3 "$SCRIPT_DIR/storage_collector.py" \
  --status-file "$STATUS_PATH" \
  --history-file "$STORAGE_HISTORY_PATH"

RELIABILITY_HISTORY_PATH=${OCTRA_RELIABILITY_HISTORY_PATH:-"$STATUS_DIR/reliability-history.json"}
python3 "$SCRIPT_DIR/reliability_collector.py" \
  --status-file "$STATUS_PATH" \
  --history-file "$RELIABILITY_HISTORY_PATH"

NETWORK_PATH=${OCTRA_NETWORK_PATH:-"$STATUS_DIR/network.json"}
HISTORY_PATH=${OCTRA_HISTORY_PATH:-"$STATUS_DIR/network-history.json"}
RPC_URL=${OCTRA_RPC_URL:-http://127.0.0.1:29080/rpc}
python3 "$SCRIPT_DIR/network_collector.py" \
  --rpc-url "$RPC_URL" \
  --status-file "$STATUS_PATH" \
  --network-file "$NETWORK_PATH" \
  --history-file "$HISTORY_PATH"
