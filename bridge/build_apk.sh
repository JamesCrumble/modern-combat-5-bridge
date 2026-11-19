#!/usr/bin/env bash
# Builds the MC5 bridge APK (documentation/architecture.md). Pattern of ../eternity-warriors-3-probe/apk/build_apk.sh (no Gradle: aapt2, javac, d8, zipalign, apksigner).
#   bridge/build_apk.sh            -> bridge/MC5-Bridge-debug.apk   (debug key bridge/build/debug.keystore, made on first use)
#   RELEASE=1 bridge/build_apk.sh  -> MC5-Bridge-<version>.apk signed with bridge/build/release.keystore (created on first use; keep a copy)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
source env.sh
tp() { [ -e "$PWD/${2:-$1}" ] && echo "$PWD/${2:-$1}" || echo "${SHARED_3P:-$PWD/../__shared-third-party__}/$1"; }  # third-party: this project first (run from the project root), then ../__shared-third-party__
BT="$ANDROID_HOME/build-tools/34.0.0"
PLATFORM="$ANDROID_HOME/platforms/android-34/android.jar"
NDKBIN="$(tp ndk)/toolchains/llvm/prebuilt/linux-x86_64/bin"
B=bridge/build
OUT=$B/apk
[ -f "$B/python.zip" ] || bridge/tools/mk_pyhome.sh
bridge/tools/mk_serverroot.sh
rm -rf "$OUT"; mkdir -p "$OUT"/{classes,dex,gen,res,lib/arm64-v8a,assets}

# native: JNI host of the embedded Python
PY="$(tp pyandroid work/pyandroid)/prefix"
"$NDKBIN/aarch64-linux-android24-clang" -shared -fPIC -O2 -Wl,-z,max-page-size=16384 -Wl,--build-id=none \
    -I "$PY/include/python3.14" bridge/jni/pyhost.c -L "$PY/lib" -lpython3.14 -llog -o "$OUT/lib/arm64-v8a/libpyhost.so"
"$NDKBIN/llvm-strip" --strip-unneeded "$OUT/lib/arm64-v8a/libpyhost.so"
cp "$B"/jnilibs/arm64-v8a/*.so "$OUT/lib/arm64-v8a/"
# redirect of the game's hosts (wrap.sh + preload library, documentation/architecture.md): goes into the combined APK
cp work/mc5trace/libmc5net.so work/mc5trace/wrap-net.sh "$OUT/lib/arm64-v8a/"
# the logging library belongs to the debug build only (tools/build_debug.sh, PC); a release does not carry it
[ "${RELEASE:-0}" = 1 ] || cp work/mc5trace/libmc5trace.so work/mc5trace/wrap-trace.sh "$OUT/lib/arm64-v8a/"

# generated build info, resources
mkdir -p "$OUT/gen/com/jamescrumble/mc5bridge"
cat > "$OUT/gen/com/jamescrumble/mc5bridge/BuildInfo.java" <<JAVA
package com.jamescrumble.mc5bridge;
final class BuildInfo { static final String STAMP = "$(date +%Y%m%d%H%M%S)", VERSION = "$(grep -o 'versionName="[^"]*"' bridge/AndroidManifest.xml | head -1 | cut -d'"' -f2)"; private BuildInfo() {} }
JAVA
cp -a bridge/res/. "$OUT/res/"
# launcher icon: the game's own icon (like the other bridges) in personal builds; RELEASE=1 keeps the neutral one (no game artwork in a release)
GAME_APK=${GAME_APKS:-gamebin/latest-from-google-play-6.0.12a/apks}/base.apk
if [ "${RELEASE:-0}" != 1 ] && [ -f "$GAME_APK" ]; then
    mkdir -p "$OUT/res/drawable-xxhdpi"
    unzip -p "$GAME_APK" res/mipmap-xxxhdpi-v4/ic_launcher.png > "$OUT/res/drawable/icon.png"
    cp "$OUT/res/drawable/icon.png" "$OUT/res/drawable-xxhdpi/icon.png"
fi
"$BT/aapt2" compile --dir "$OUT/res" -o "$OUT/resources.zip"
"$BT/aapt2" link --manifest bridge/AndroidManifest.xml -I "$PLATFORM" --java "$OUT/gen" --min-sdk-version 26 --target-sdk-version 34 \
    -o "$OUT/base.ap_" "$OUT/resources.zip"
# the patcher libraries (documentation/architecture.md): smali/baksmali for the dex patches, apksig for the signature
SMALI=$(tp tools/smali work/tools/smali)
LIBJARS=$(ls "$SMALI"/smali-*.jar "$SMALI"/guava-*.jar "$SMALI"/failureaccess-*.jar "$SMALI"/antlr-runtime-*.jar "$BT/lib/apksigner.jar" | tr '\n' ' ')
find "$OUT/gen" bridge/src -name '*.java' -print0 | xargs -0 javac -source 8 -target 8 -encoding UTF-8 -Xlint:-options -classpath "$PLATFORM:$(echo $LIBJARS | tr ' ' ':')" -d "$OUT/classes"
"$BT/d8" --lib "$PLATFORM" --min-api 26 --output "$OUT/dex" $(find "$OUT/classes" -name '*.class') $LIBJARS

# assets: Python runtime, server files, scripts
cp "$B/python.zip" "$OUT/assets/python.zip"
cp "$B/serverroot.zip" "$OUT/assets/serverroot.zip"
cp bridge/python/*.py "$OUT/assets/"
mkdir -p "$OUT/assets/patch" && cp -r bridge/patch/. "$OUT/assets/patch/" 
ITEMS=()
for f in "$OUT"/lib/arm64-v8a/*; do ITEMS+=("S:lib/arm64-v8a/$(basename "$f")=$f"); done
for f in "$OUT"/assets/*.zip "$OUT"/assets/*.py; do ITEMS+=("D:assets/$(basename "$f")=$f"); done
for f in $(cd "$OUT/assets" && find patch -type f); do ITEMS+=("D:assets/$f=$OUT/assets/$f"); done
for f in "$OUT"/dex/classes*.dex; do ITEMS+=("D:$(basename "$f")=$f"); done
python3 bridge/tools/ziptool.py append "$OUT/base.ap_" "$OUT/unsigned.apk" "${ITEMS[@]}"

if [ "${RELEASE:-0}" = 1 ]; then
    KEY=$B/release.keystore; PASSFILE=$B/release.pass
    if [ ! -f "$KEY" ]; then
        head -c 18 /dev/urandom | base64 | tr -d '/+=' > "$PASSFILE"
        keytool -genkeypair -keystore "$KEY" -storepass "$(cat "$PASSFILE")" -keypass "$(cat "$PASSFILE")" -alias mc5bridge -keyalg RSA -keysize 4096 \
            -validity 36500 -dname "CN=MC5 Bridge,O=JamesCrumble,C=US" >/dev/null
    fi
    VER=$(grep -o 'versionName="[^"]*"' bridge/AndroidManifest.xml | head -1 | cut -d'"' -f2)
    APK_OUT=bridge/MC5-Bridge-$VER.apk; PASS=$(cat "$PASSFILE"); ALIAS=mc5bridge
    "$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
    "$BT/apksigner" sign --ks "$KEY" --ks-pass "pass:$PASS" --key-pass "pass:$PASS" --ks-key-alias $ALIAS --out "$APK_OUT" "$OUT/aligned.apk"
else
    KEY=$B/debug.keystore
    [ -f "$KEY" ] || keytool -genkeypair -keystore "$KEY" -storepass android -keypass android -alias androiddebugkey -keyalg RSA -keysize 2048 \
        -validity 10000 -dname "CN=Android Debug,O=Android,C=US" >/dev/null
    APK_OUT=bridge/MC5-Bridge-debug.apk
    "$BT/zipalign" -f -p 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
    "$BT/apksigner" sign --ks "$KEY" --ks-pass pass:android --out "$APK_OUT" "$OUT/aligned.apk"
fi
"$BT/apksigner" verify --verbose "$APK_OUT" | head -3
ls -l "$APK_OUT"
