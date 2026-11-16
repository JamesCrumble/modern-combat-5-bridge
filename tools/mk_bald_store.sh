#!/usr/bin/env bash
# BALD store for the server on a PC (chapters of the campaign, served by Iris; the bridge uses the game's own folder instead):
# work/bald6012/ = symlinks to the BALD files of the Google Play build 6.0.12a under their server-side names (no copy).
#   tools/mk_bald_store.sh <folder bald/ of the game>   e.g. a copy of /sdcard/Android/data/com.gameloft.android.ANMP.GloftM5HM/files/bald
# `temp_` files are finished downloads the game had not renamed yet; they are used when no file of the final name exists.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC=${1:?usage: tools/mk_bald_store.sh <bald folder of the game>}
OUT=work/bald6012
rm -rf "$OUT"; mkdir -p "$OUT"
for f in "$SRC"/*; do
    n=$(basename "$f")
    case "$n" in
        temp_*) [ -e "$OUT/${n#temp_}" ] || ln -s "$(realpath "$f")" "$OUT/${n#temp_}" ;;
        *) ln -sf "$(realpath "$f")" "$OUT/$n" ;;
    esac
done
echo "$(ls "$OUT" | wc -l) files in $OUT"
