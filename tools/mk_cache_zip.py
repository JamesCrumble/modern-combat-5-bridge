#!/usr/bin/env python3
"""The cache archive for players (documentation/architecture.md): everything the game and the server need besides the two APKs, in one zip
the bridge unpacks itself (DataImport). Clean: no account, no saves, no device-specific files.

  internal/files/assetpacks/...            the game's asset packs (Play Asset Delivery, ~1.4 GB)
  internal/files/didomi_*                   consent SDK config cache (since dex/didomi.spec not required; kept: the tested set)
  internal/shared_prefs/<consent>.xml       consent given (DIDOMI_*, FORBID_DIDOMI_*, <package>_preferences.xml: Didomi/IAB keys only)
  external/bald/...                         chapters of the campaign (~0.8 GB)
  external/{iris_*_cache.bin, compliancy.bin, dcsbin, InsTime}   cached Iris answers, compliance flags, installer state
  server-data/...                           the server's reference data (server/data)

Sources: a snapshot of a Google Play install 6.0.12a (`--game`: data/<pkg>/ of the private folder and external/<pkg>/files of
Android/data, as `adb shell run-as`/root copies them) and the server data. Entries are STORED (the packs and chapters are compressed already).

Run: python3 tools/mk_cache_zip.py --private <data/<pkg>> --external <Android/data/<pkg>/files> [--extra <dir>] --server-data server/data OUT.zip
"""
import argparse
import os
import sys
import zipfile

PKG = "com.gameloft.android.ANMP.GloftM5HM"
PREFS = ["DIDOMI_USER_HAS_CONSENTED_SPC.xml", "FORBID_DIDOMI_Spec.xml", "FORBID_DIDOMI_FILLED_Spec.xml", PKG + "_preferences.xml"]
EXTERNAL_FILES = ["iris_behavioral_cache.bin", "iris_compliancy_cache.bin", "compliancy.bin", "dcsbin", "InsTime"]
# keys of <package>_preferences.xml that may go into the archive (consent only); anything else in that file stops the build
PREF_KEYS = ("IABTCF_", "IABGPP_", "Didomi_", "bg_startup_tracing")


def add_tree(z, src, arc):
    n = 0
    for base, dirs, files in os.walk(src):
        dirs.sort()
        for f in sorted(files):
            p = os.path.join(base, f)
            z.write(p, arc + "/" + os.path.relpath(p, src).replace(os.sep, "/"), zipfile.ZIP_STORED)
            n += 1
    return n


def find(name, *dirs):
    for d in dirs:
        if d and os.path.isfile(os.path.join(d, name)):
            return os.path.join(d, name)
    sys.exit("missing %s in %s" % (name, ", ".join(d for d in dirs if d)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--private", required=True, help="copy of /data/data/<package> (files/, shared_prefs/)")
    ap.add_argument("--external", required=True, help="copy of /sdcard/Android/data/<package>/files (bald/, ...)")
    ap.add_argument("--extra", help="another copy of the external folder to take the small files from (e.g. dcsbin)")
    ap.add_argument("--server-data", required=True)
    ap.add_argument("out")
    a = ap.parse_args()
    files_dir, prefs_dir = os.path.join(a.private, "files"), os.path.join(a.private, "shared_prefs")
    prefs = open(os.path.join(prefs_dir, PKG + "_preferences.xml"), encoding="utf-8").read()
    import re
    other = [k for k in re.findall(r'name="([^"]+)"', prefs) if not k.startswith(PREF_KEYS)]
    if other:
        sys.exit("unexpected keys in %s_preferences.xml (not consent): %s" % (PKG, other))
    tmp = a.out + ".part"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED, allowZip64=True) as z:
        n = add_tree(z, os.path.join(files_dir, "assetpacks"), "internal/files/assetpacks")
        for f in sorted(os.listdir(files_dir)):
            if f.startswith("didomi_"):
                z.write(os.path.join(files_dir, f), "internal/files/" + f); n += 1
        for f in PREFS:
            z.write(find(f, prefs_dir), "internal/shared_prefs/" + f); n += 1
        bald = os.path.join(a.external, "bald")
        for f in sorted(os.listdir(bald)):
            if f.startswith("temp_"):
                sys.exit("unfinished download in bald/: " + f)
        n += add_tree(z, bald, "external/bald")
        for f in EXTERNAL_FILES:
            z.write(find(f, a.external, a.extra), "external/" + f); n += 1
        n += add_tree(z, a.server_data, "server-data")
    os.replace(tmp, a.out)
    print("%s: %d files, %.0f MB" % (a.out, n, os.path.getsize(a.out) / 2 ** 20))


if __name__ == "__main__":
    main()
