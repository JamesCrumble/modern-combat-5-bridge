#!/usr/bin/env bash
# Combined APK B (documentation/architecture.md) built by the SAME Java patcher that runs on the phone (bridge/src/.../patch, bridge/patch/*.spec, bridge/patch/manifest_add.txt):
# original Play files (base + arm64 split) + the bridge -> work/full/MC5-full.apk, signed with work/patched-apk.key (created on first use).
# The bridge parts (dex, libraries, assets) come from the bridge APK built by bridge/build_apk.sh.
#   tools/build_full.sh             builds the bridge APK first
#   SKIP_BASE=1 tools/build_full.sh reuses bridge/MC5-Bridge-debug.apk as it is
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh
SRC=${GAME_APKS:-gamebin/latest-from-google-play-6.0.12a/apks}   # folder with the original base.apk and split_config.arm64_v8a.apk
OUT=work/full
PC=bridge/build/pc
if [ "${SKIP_BASE:-0}" != 1 ]; then
    tools/build_mc5trace.sh >/dev/null
    bridge/build_apk.sh >/dev/null
fi
rm -rf "$OUT" "$PC"; mkdir -p "$OUT" "$PC"
CP=$(ls work/tools/smali/*.jar android-sdk/build-tools/34.0.0/lib/apksigner.jar | tr '\n' ':')
# the patcher classes were compiled by bridge/build_apk.sh (bridge/build/apk/classes); PcMain is the PC front
javac -nowarn -source 8 -target 8 -Xlint:-options -cp "bridge/build/apk/classes:$CP" -d "$PC" bridge/pc/PcMain.java
java -cp "$PC:bridge/build/apk/classes:$CP" PcMain "$SRC/base.apk" "$SRC/split_config.arm64_v8a.apk" bridge/MC5-Bridge-debug.apk \
    "$OUT/MC5-full.apk" "$OUT/work" work/patched-apk.key bridge/patch
rm -rf "$OUT/work"
android-sdk/build-tools/34.0.0/apksigner verify --verbose "$OUT/MC5-full.apk" | head -3
android-sdk/build-tools/34.0.0/aapt2 dump badging "$OUT/MC5-full.apk" 2>&1 | grep -E "^package|launchable-activity|native-code" | cut -c1-160
ls -l "$OUT/MC5-full.apk"
