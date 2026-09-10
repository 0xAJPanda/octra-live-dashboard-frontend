#!/bin/sh
set -eu

NODE_DIR=${OCTRA_NODE_DIR:-/opt/octra/libv_litecore}
UPGRADE_PATH=${OCTRA_UPGRADE_PATH:-/var/lib/octra/dashboard/upgrade.txt}
UPGRADE_DIR=$(dirname -- "$UPGRADE_PATH")

mkdir -p "$UPGRADE_DIR"
TEMP_UPGRADE=$(mktemp "$UPGRADE_DIR/.upgrade.XXXXXX")
RAW_UPGRADE=$(mktemp "$UPGRADE_DIR/.upgrade-raw.XXXXXX")
trap 'rm -f "$TEMP_UPGRADE" "$RAW_UPGRADE"' EXIT HUP INT TERM

# controls/upgrade.sh is diagnostic-only unless --apply is explicitly supplied.
# This collector never passes --apply and publishes only strict, public tokens.
(cd "$NODE_DIR" && sh controls/upgrade.sh) > "$RAW_UPGRADE"
awk '
BEGIN {
  split("sequence action public_commit source_commit expires_at binary_match source_match runtime_match rpc head_epoch peer_epoch lag voting validator_member validator_scheduled release_published upgrade_available status gate", fields, " ")
  for (i in fields) allowed[fields[i]] = 1
}
{
  for (i = 1; i <= NF - 2; i++) {
    if (($i in allowed) && $(i + 1) == "=") print $i " = " $(i + 2)
  }
}
' "$RAW_UPGRADE" > "$TEMP_UPGRADE"

chmod 0644 "$TEMP_UPGRADE"
mv "$TEMP_UPGRADE" "$UPGRADE_PATH"
rm -f "$RAW_UPGRADE"
trap - EXIT HUP INT TERM
