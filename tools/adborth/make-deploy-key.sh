#!/bin/bash
# Makes the key the deploy helper trusts: one copy in this Mac's Keychain, one
# on the NAS beside the helper. Run once, with the NAS share mounted. The key
# is never printed.
set -euo pipefail
SHARE="${ADBORTH_SHARE:-/Volumes/container/freeframe}"
[ -d "$SHARE" ] || { echo "The NAS share is not mounted at $SHARE."; exit 1; }
mkdir -p "$SHARE/deployer"
KEY="$(openssl rand -hex 32)"
security add-generic-password -U -s adborth-deploy-key -a adborth -w "$KEY" >/dev/null
printf '%s\n' "$KEY" > "$SHARE/deployer/key"
chmod 600 "$SHARE/deployer/key" 2>/dev/null || true
unset KEY
echo "Key made: in the Keychain as 'adborth-deploy-key' and on the NAS in deployer/key."
