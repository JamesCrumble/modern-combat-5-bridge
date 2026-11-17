#!/usr/bin/env bash
# Release bundle (files to attach to a release; documentation/architecture.md), like the other bridges (MC3/MC4: release/<version>/):
#   release/<v>/MC5-Bridge-<v>.apk        release-signed installer (neutral icon, no logging library, no game files, no Gameloft data)
#   release/<v>/MC5-Bridge-<v>-src.zip    source of the bridge, server, patches, tools and documentation (no server/data, no binaries)
#   release/<v>/INSTALL.txt, RELEASE_NOTES.md (release description, cache checksum filled in), SHA256SUMS
#   release/cache/                         the cache archive for players, hosted elsewhere (too big for GitHub): MC5-cache-6.0.12a.zip
#       (game packs, chapters, consent, server data; tools/mk_cache_zip.py), README.md, SHA256SUMS
# The game's own files are the player's and are never part of a release.
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh
VER=$(grep -o 'versionName="[^"]*"' bridge/AndroidManifest.xml | head -1 | cut -d'"' -f2)
OUT=release/$VER
CACHE=release/cache
rm -rf "$OUT" "$CACHE" release/extra-data; mkdir -p "$OUT" "$CACHE"
tools/build_mc5trace.sh >/dev/null
RELEASE=1 bridge/build_apk.sh > /dev/null
mv "bridge/MC5-Bridge-$VER.apk" "$OUT/"
rm -f "bridge/MC5-Bridge-$VER.apk.idsig"
APK="$OUT/MC5-Bridge-$VER.apk"
# the APK must not contain the debug library, the game's artwork or Gameloft's data
if unzip -l "$APK" | grep -q "libmc5trace"; then echo "release APK has the debug library" >&2; exit 1; fi
if unzip -p "$APK" assets/serverroot.zip | python3 -c "import io,sys,zipfile; n=zipfile.ZipFile(io.BytesIO(sys.stdin.buffer.read())).namelist(); sys.exit(0 if any('/data/' in x for x in n) else 1)"; then
    echo "release APK has server data (Gameloft) inside serverroot.zip" >&2; exit 1
fi
python3 - "$OUT/MC5-Bridge-$VER-src.zip" "MC5-Bridge-$VER" <<'PY'
import os, sys, zipfile
out, prefix = sys.argv[1], sys.argv[2]
roots = ["bridge", "server", "mc5trace", "tools", "documentation", "README.md", "CHANGELOG.md", "LICENSE", "NOTICE.md", ".gitignore",
         ".gitattributes", "env.sh"]
skip = ("bridge/build", "bridge/MC5-Bridge", "server/__pycache__", "server/data")
def elf(p):
    with open(p, "rb") as f:
        return f.read(4) == b"\x7fELF"
with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
    for r in roots:
        if os.path.isfile(r):
            z.write(r, prefix + "/" + r); continue
        for base, dirs, files in os.walk(r):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in sorted(files):
                p = os.path.join(base, f)
                if p.startswith(skip) or f.endswith((".apk", ".so", ".idsig", ".keystore", ".key", ".pyc")) or elf(p) or os.path.getsize(p) > 20 * 1024 * 1024:
                    continue
                z.write(p, prefix + "/" + p)
PY
cp tools/release_install.txt "$OUT/INSTALL.txt"

# cache archive for players (documentation/architecture.md): packs, chapters, consent, server data in one zip; made from a snapshot of a
# Play install (CACHE_PRIVATE = copy of /data/data/<pkg>, CACHE_EXTERNAL = copy of Android/data/<pkg>/files, CACHE_EXTRA = another copy of it)
G=gamebin/latest-from-google-play-6.0.12a; P=com.gameloft.android.ANMP.GloftM5HM
CACHE_PRIVATE=${CACHE_PRIVATE:-$G/device_data/data/$P}; CACHE_EXTERNAL=${CACHE_EXTERNAL:-$G/device_data3/external/$P/files}; CACHE_EXTRA=${CACHE_EXTRA:-$G/external_files}
if [ -f server/data/ah/crm.json ] && [ -d "$CACHE_PRIVATE/files/assetpacks" ] && [ -d "$CACHE_EXTERNAL/bald" ]; then
    python3 tools/mk_cache_zip.py --private "$CACHE_PRIVATE" --external "$CACHE_EXTERNAL" --extra "$CACHE_EXTRA" --server-data server/data \
        "$CACHE/MC5-cache-6.0.12a.zip"
    cp tools/release_cache_readme.md "$CACHE/README.md"
    (cd "$CACHE" && sha256sum MC5-cache-6.0.12a.zip README.md > SHA256SUMS)
else
    echo "no server/data or no Play snapshot: release/cache not made" >&2
fi
# release description (GitHub release body) with the cache archive's checksum; SHA256SUMS of the files attached to the release
CACHE_SHA=$(cut -d' ' -f1 "$CACHE/SHA256SUMS" 2>/dev/null | head -1)
sed "s/@CACHE_SHA256@/${CACHE_SHA:-see release\/cache\/SHA256SUMS}/" tools/release_notes.md > "$OUT/RELEASE_NOTES.md"
(cd "$OUT" && sha256sum MC5-Bridge-* INSTALL.txt > SHA256SUMS)
ls -la "$OUT" "$CACHE"
