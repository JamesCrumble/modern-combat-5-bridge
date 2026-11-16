#!/usr/bin/env bash
# Keeps `adb reverse` of the server ports on every connected phone (the forwards disappear when the USB transport restarts: the game then shows
# "Failed to connect"). Run next to tools/run_servers.sh while testing: tools/reverse_all.sh [seconds, default 8] (Ctrl+C to stop).
cd "$(dirname "$0")/.."
PORTS="18080 18443 33508 33600 33601 33602 33698 33699 33700 $(seq 33710 33809)"
while true; do
    for s in $(tools/adb devices | tr -d '\r' | awk 'NR>1 && $2=="device" {print $1}'); do
        if [ "$(tools/adb -s "$s" reverse --list | tr -d '\r' | grep -c .)" -lt 8 ]; then
            for p in $PORTS; do tools/adb -s "$s" reverse tcp:$p tcp:$p >/dev/null 2>&1; done
            echo "$(date +%T) reverse restored on $s"
        fi
    done
    sleep "${1:-8}"
done
