#!/usr/bin/env bash
# (Re)start the local server (one process): HTTP :18080, HTTPS :18443, alert TLS :33508, AH game server :33600 (log work/server_run.log).
# Usage: tools/run_servers.sh [server options, e.g. --data <server-data folder> --host 0.0.0.0]; ANDROID_SERIAL=<serial> picks the phone for adb reverse.
# Certificate: work/tls/self.* (self-signed; the client accepts any certificate after the TLS_NOVERIFY patch, bridge/patch/native.spec; no CA on the phone).
# The phone reaches the PC through `adb reverse` (no root). Old servers are stopped by PORT (a stale process would keep serving the old code).
cd "$(dirname "$0")/.."
tools/mk_tls_cert.sh
C=work/tls/self
# record mode (MC5_UPSTREAM=1, documentation/development.md): traffic to the real servers goes through a SOCKS5 proxy, MC5_SOCKS=host:port
for port in 18080 18443 33508 33600 33601 33602 33698 33699 33700 $(seq 33710 33809); do
    pid=$(ss -ltnp 2>/dev/null | grep ":$port " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)
    [ -n "$pid" ] && kill "$pid"
done
sleep 2
mkdir -p work/state
nohup .venv/bin/python server/mc5server.py --tls-cert $C.pem --tls-key $C.key "$@" > work/server_run.log 2>&1 &
for port in 18080 18443 33508 33600 33601 33602 33698 33699 33700 $(seq 33710 33809); do tools/adb ${ANDROID_SERIAL:+-s $ANDROID_SERIAL} reverse tcp:$port tcp:$port >/dev/null || echo "adb reverse $port failed"; done
sleep 3
curl -s -m 5 http://127.0.0.1:18080/_mc5/ready | head -c 60; echo
