#!/usr/bin/env bash
# Stages the Python runtime for the bridge APK (documentation/architecture.md): build/stage/python (pruned stdlib incl. lib-dynload) -> build/python.zip,
# interpreter libraries -> build/jnilibs/arm64-v8a. Source: work/pyandroid (python-3.14.0-aarch64-linux-android.tar.gz from python.org).
set -euo pipefail
cd "$(dirname "$0")/../.."
SRC=work/pyandroid/prefix
[ -d "$SRC" ] || { echo "unpack python-3.14.0-aarch64-linux-android.tar.gz into work/pyandroid first" >&2; exit 1; }
B=bridge/build; rm -rf "$B/stage" "$B/jnilibs" "$B/python.zip"
mkdir -p "$B/stage/python/lib" "$B/jnilibs/arm64-v8a"
cp -a "$SRC/lib/python3.14" "$B/stage/python/lib/"
L="$B/stage/python/lib/python3.14"
rm -rf "$L"/{test,idlelib,tkinter,ensurepip,pydoc_data,turtledemo,lib2to3,site-packages,config-*} "$L"/turtle.py "$L"/__pycache__
find "$L" -name __pycache__ -type d -prune -exec rm -rf {} +
rm -f "$L"/lib-dynload/_test* "$L"/lib-dynload/_xxtestfuzz* "$L"/lib-dynload/_ctypes_test* "$L"/lib-dynload/_sqlite3* "$L"/lib-dynload/_remote_debugging* "$L"/lib-dynload/_interp*
mkdir -p "$L/site-packages"
# pure-Python server dependencies (Starlette stack, no FastAPI/pydantic: server/mc5/web.py); wheels are zips
for w in "$B"/wheels/*.whl; do python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$w" "$L/site-packages"; done
rm -rf "$L"/site-packages/*.dist-info
cp "$SRC"/lib/libpython3.14.so "$SRC"/lib/libssl_python.so "$SRC"/lib/libcrypto_python.so "$B/jnilibs/arm64-v8a/"
python3 bridge/tools/ziptool.py dir "$B/stage/python" "$B/python.zip"
du -sh "$B/stage/python" "$B/python.zip" "$B/jnilibs"
