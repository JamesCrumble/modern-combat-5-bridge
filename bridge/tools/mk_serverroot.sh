#!/usr/bin/env bash
# Stages the server for the bridge APK: build/serverroot/server (code, data unless RELEASE=1, TLS certificate) -> build/serverroot.zip (documentation/architecture.md).
# Not included: mc5proxy.py (record mode, PC only, needs httpx), __pycache__.
set -euo pipefail
cd "$(dirname "$0")/../.."
B=bridge/build; rm -rf "$B/serverroot" "$B/serverroot.zip"
mkdir -p "$B/serverroot/server/mc5" "$B/serverroot/server/tls"
cp server/mc5server.py "$B/serverroot/server/"
cp server/mc5/*.py "$B/serverroot/server/mc5/"
# Gameloft reference data (server/data) only in personal builds; a release (RELEASE=1) carries none: the player downloads it separately
# (release/extra-data, documentation/architecture.md) into BridgeGames/<game>/server-data/
[ "${RELEASE:-0}" = 1 ] || cp -r server/data "$B/serverroot/server/data"
find "$B/serverroot" -name __pycache__ -type d -prune -exec rm -rf {} +
tools/mk_tls_cert.sh
cp work/tls/self.pem work/tls/self.key "$B/serverroot/server/tls/"
python3 bridge/tools/ziptool.py dir "$B/serverroot" "$B/serverroot.zip"
du -sh "$B/serverroot.zip"
