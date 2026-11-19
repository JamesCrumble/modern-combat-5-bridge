#!/usr/bin/env bash
# Debug build "MC5 Debug" (documentation/architecture.md): the same patcher + the logging redirect library libmc5trace.so (logcat tag mc5trace and
# /sdcard/Android/data/<package>/files/mc5trace.log), trace hooks of the installer (dex/trace.spec), name "MC5 Debug", icon with a DEBUG band,
# signature of its own (work/debug-apk.key): it never updates the bridge-made game. Same package as the game: installing one removes the other
# (the progress comes back through the mirror mc5_state.json). Output: work/full/MC5-debug.apk
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh
tp() { [ -e "$PWD/${2:-$1}" ] && echo "$PWD/${2:-$1}" || echo "${SHARED_3P:-$PWD/../__shared-third-party__}/$1"; }  # third-party: this project first (run from the project root), then ../__shared-third-party__
SRC=${GAME_APKS:-gamebin/latest-from-google-play-6.0.12a/apks}   # folder with the original base.apk and split_config.arm64_v8a.apk
OUT=work/full
PC=bridge/build/pc
if [ "${SKIP_BASE:-0}" != 1 ]; then
    tools/build_mc5trace.sh >/dev/null
    bridge/build_apk.sh >/dev/null
fi
rm -rf "$PC" "$OUT/work"; mkdir -p "$OUT" "$PC"
CP=$(ls "$(tp tools/smali work/tools/smali)"/*.jar "$ANDROID_HOME"/build-tools/34.0.0/lib/apksigner.jar | tr '\n' ':')
javac -nowarn -source 8 -target 8 -Xlint:-options -cp "bridge/build/apk/classes:$CP" -d "$PC" bridge/pc/PcMain.java
java -cp "$PC:bridge/build/apk/classes:$CP" PcMain "$SRC/base.apk" "$SRC/split_config.arm64_v8a.apk" bridge/MC5-Bridge-debug.apk \
    "$OUT/MC5-debug.apk" "$OUT/work" work/debug-apk.key bridge/patch debug
rm -rf "$OUT/work"
"$ANDROID_HOME"/build-tools/34.0.0/apksigner verify "$OUT/MC5-debug.apk" | head -1
ls -l "$OUT/MC5-debug.apk"
