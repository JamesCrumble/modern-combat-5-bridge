#!/usr/bin/env bash
# Release bundle (files to attach to a release; documentation/architecture.md), like the other bridges (MC3/MC4: release/<version>/):
#   release/<v>/MC5-Bridge-<v>.apk        release-signed installer (neutral icon, no logging library, no game files, no Gameloft data)
#   release/<v>/MC5-Bridge-<v>-src.zip    source of the bridge, server, patches, tools and documentation (no server/data, no binaries)
#   release/<v>/INSTALL.txt, RELEASE_NOTES.md, SHA256SUMS
#   release/extra-data/                    the server's Gameloft reference data as a separate download (hosted elsewhere):
#       server-data/ (folder), MC5-server-data-<v>.zip (same, one top folder server-data/), README.md, SHA256SUMS
# The game's own files are the player's and are never part of a release.
set -euo pipefail
cd "$(dirname "$0")/.."
source env.sh
VER=$(grep -o 'versionName="[^"]*"' bridge/AndroidManifest.xml | head -1 | cut -d'"' -f2)
OUT=release/$VER
EXTRA=release/extra-data
rm -rf "$OUT" "$EXTRA"; mkdir -p "$OUT" "$EXTRA"
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
cp tools/release_notes.md "$OUT/RELEASE_NOTES.md"
(cd "$OUT" && sha256sum * | grep -v SHA256SUMS > SHA256SUMS)

# server data: a separate download (documentation/architecture.md); without server/data (fresh checkout) it is skipped
if [ -f server/data/ah/crm.json ]; then
    cp -r server/data "$EXTRA/server-data"
    find "$EXTRA/server-data" -name __pycache__ -type d -prune -exec rm -rf {} +
    (cd "$EXTRA" && python3 -c "
import os, sys, zipfile
with zipfile.ZipFile(sys.argv[1], 'w', zipfile.ZIP_DEFLATED) as z:
    for base, dirs, files in os.walk('server-data'):
        dirs.sort()
        for f in sorted(files):
            z.write(os.path.join(base, f))
" "MC5-server-data-$VER.zip")
    cp tools/release_extra_readme.md "$EXTRA/README.md"
    (cd "$EXTRA" && sha256sum "MC5-server-data-$VER.zip" README.md > SHA256SUMS)
else
    echo "server/data missing: release/extra-data not made (put the server-data download there)" >&2
fi
ls -la "$OUT" "$EXTRA"
