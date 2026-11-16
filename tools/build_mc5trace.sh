#!/usr/bin/env bash
# Builds the redirect libraries for the game (mc5trace/*.c -> work/mc5trace/mc5trace.c):
#   work/mc5trace/libmc5trace.so + wrap-trace.sh : debug build "MC5 Debug" (logs to logcat and $MC5TRACE_FILE, tunnels to the PC, documentation/protocol.md)
#   work/mc5trace/libmc5net.so   + wrap-net.sh   : product build (-DMC5_QUIET: no log, no file hooks; hosts of Gameloft -> 127.0.0.1)
# The bridge APK carries both; the patcher puts the right pair into the game's lib/arm64-v8a as libXXX.so + wrap.sh. Needs the NDK in ./ndk.
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p work/mc5trace
cat mc5trace/*.c > work/mc5trace/mc5trace.c
CC=ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android24-clang
mkdir -p work/mc5trace
$CC -shared -fPIC -O2 -Wall -Wextra -o work/mc5trace/libmc5trace.so work/mc5trace/mc5trace.c -llog -ldl
$CC -shared -fPIC -O2 -DMC5_QUIET -Wno-unused-function -Wno-unused-parameter -Wno-unused-variable -o work/mc5trace/libmc5net.so work/mc5trace/mc5trace.c -llog -ldl
ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip --strip-unneeded work/mc5trace/libmc5net.so
cat > work/mc5trace/wrap-trace.sh <<'W'
#!/system/bin/sh
HERE="$(cd "$(dirname "$0")" && pwd)"
export MC5TRACE_FILE=/sdcard/Android/data/com.gameloft.android.ANMP.GloftM5HM/files/mc5trace.log
export MC5_REDIRECT=1
export LD_PRELOAD="$HERE/libmc5trace.so"
exec "$@"
W
cat > work/mc5trace/wrap-net.sh <<'W'
#!/system/bin/sh
HERE="$(cd "$(dirname "$0")" && pwd)"
export MC5_REDIRECT=1
export LD_PRELOAD="$HERE/libmc5net.so"
exec "$@"
W
chmod +x work/mc5trace/wrap-*.sh
cp work/mc5trace/wrap-trace.sh work/mc5trace/wrap.sh
ls -l work/mc5trace
