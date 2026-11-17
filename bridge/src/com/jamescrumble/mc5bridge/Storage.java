package com.jamescrumble.mc5bridge;

import android.Manifest;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * Files of the bridge. The player puts the original game files into the shared folder {@code /sdcard/BridgeGames/<game package>/}
 * (needs "access to all files"); the bridge's own state (settings, server state, the prepared game) lives in the private folder.
 * Pattern of the EW3 bridge's Storage, reduced to what the MC5 bridge needs.
 */
final class Storage {
    static final String ROOT_NAME = "BridgeGames";
    static final String GAME_PACKAGE = "com.gameloft.android.ANMP.GloftM5HM";

    private Storage() {}

    /** Is this the combined APK (bridge inside the game, package of the game, documentation/architecture.md)? */
    static boolean combined(Context c) {
        return GAME_PACKAGE.equals(c.getPackageName());
    }

    /** Can this app read and write the shared folder right now? (API 29 keeps scoped storage: no.) */
    static boolean hasAccess(Context c) {
        if (Build.VERSION.SDK_INT >= 30) return Environment.isExternalStorageManager();
        if (Build.VERSION.SDK_INT >= 29) return false;
        return c.checkSelfPermission(Manifest.permission.WRITE_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED;
    }

    static Intent accessIntent(Context c) {
        return new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION, Uri.parse("package:" + c.getPackageName()));
    }

    static void requestAccess(Activity a, int code) {
        if (Build.VERSION.SDK_INT >= 30) {
            try {
                a.startActivity(accessIntent(a));
            } catch (RuntimeException e) {
                a.startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
            }
        } else if (Build.VERSION.SDK_INT < 29) {
            a.requestPermissions(new String[] {Manifest.permission.READ_EXTERNAL_STORAGE, Manifest.permission.WRITE_EXTERNAL_STORAGE}, code);
        }
    }

    /** {@code /storage/emulated/0/BridgeGames/<package of the game>}: the same folder for the installer (A) and the combined APK (B); only meaningful with access. */
    static File shared(Context c) {
        return new File(new File(Environment.getExternalStorageDirectory(), ROOT_NAME), GAME_PACKAGE);
    }

    /** The shared folder (created) with access, else null. */
    static File sharedOrNull(Context c) {
        if (!hasAccess(c)) return null;
        File d = shared(c);
        d.mkdirs();
        return d.isDirectory() ? d : null;
    }

    /**
     * The original game APKs in the folder, found by content (the file names do not matter): {base, arm64 split}, missing ones null.
     * The split carries lib/arm64-v8a/libMC5.so, the base carries classes4.dex (the dex the patches change). Exact Play names win.
     */
    static File[] gameApks(File folder) {
        File base = new File(folder, "base.apk"), arm = new File(folder, "split_config.arm64_v8a.apk");
        File[] out = {base.isFile() ? base : null, arm.isFile() ? arm : null};
        File[] files = folder.listFiles();
        if (files == null) return out;
        for (File f : files) {
            if (!f.isFile() || !f.getName().toLowerCase(java.util.Locale.ROOT).endsWith(".apk")) continue;
            try (java.util.zip.ZipFile z = new java.util.zip.ZipFile(f)) {
                if (out[1] == null && z.getEntry("lib/arm64-v8a/libMC5.so") != null) out[1] = f;
                else if (out[0] == null && z.getEntry("classes4.dex") != null && z.getEntry("lib/arm64-v8a/libMC5.so") == null) out[0] = f;
            } catch (IOException ignored) { }
        }
        return out;
    }

    static File privateDir(Context c) {
        return c.getFilesDir();
    }

    static File settingsFile(Context c) {
        return new File(privateDir(c), "settings.txt");
    }

    static String readText(File f) throws IOException {
        try (FileInputStream in = new FileInputStream(f)) {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] b = new byte[4096];
            int n;
            while ((n = in.read(b)) > 0) out.write(b, 0, n);
            return out.toString("UTF-8");
        }
    }

    static void writeText(File f, String s) throws IOException {
        try (FileOutputStream out = new FileOutputStream(f)) { out.write(s.getBytes("UTF-8")); }
    }

    static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteTree(k);
        f.delete();
    }

    /** The last {@code max} lines of a text file, or "" when it does not exist. */
    static String tail(File f, int max) {
        if (!f.isFile()) return "";
        try {
            long len = f.length();
            try (java.io.RandomAccessFile r = new java.io.RandomAccessFile(f, "r")) {
                long from = Math.max(0, len - 64 * 1024);
                r.seek(from);
                byte[] b = new byte[(int) (len - from)];
                r.readFully(b);
                String[] lines = new String(b, "UTF-8").split("\n");
                StringBuilder sb = new StringBuilder();
                for (int i = Math.max(0, lines.length - max); i < lines.length; i++) sb.append(lines[i]).append('\n');
                return sb.toString();
            }
        } catch (IOException e) {
            return "";
        }
    }
}
