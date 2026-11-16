#!/usr/bin/env bash
# Self-signed TLS certificate of the server (work/tls/self.pem + self.key), made once if missing. The client does not check it
# (TLS_NOVERIFY, documentation/client-patches.md), but libcurl still matches the host name against the SAN: 127.0.0.1 and *.gameloft.com.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f work/tls/self.pem ] && [ -f work/tls/self.key ] && exit 0
mkdir -p work/tls
openssl req -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=gameloft.com" -keyout work/tls/self.key -out work/tls/self.pem \
    -addext "subjectAltName=IP:127.0.0.1,DNS:localhost,DNS:gameloft.com,DNS:*.gameloft.com,DNS:*.gold0033.gameloft.com,DNS:*.xsilo-gold.gameloft.com,DNS:*.tools.gameloft.com,DNS:*.datalake.gameloft.com" 2>/dev/null
echo "made work/tls/self.pem"
