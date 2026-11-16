package com.jamescrumble.mc5bridge;

import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;

/**
 * First start of the combined APK (B): the player's game data from {@code BridgeGames/<package>/} goes to the places the game reads
 * (A cannot write into the private folder of B, B does it itself). Layout of the folder:
 * {@code internal/} = the game's private folder (files/, shared_prefs/, databases/ ...), {@code external/} = Android/data/&lt;package&gt;/files.
 * A marker file in files/ keeps it from running twice; the data is not touched afterwards.
 */
final class DataImport {
    interface Progress {
        void bytes(long done, long total);
    }

    private DataImport() {}

    static File marker(Context c) {
        return new File(c.getFilesDir(), ".bridge_data_imported");
    }

    /** Is there something to import and has it not been imported yet? */
    static boolean pending(Context c) {
        File folder = Storage.sharedOrNull(c);
        if (folder == null || marker(c).exists()) return false;
        return new File(folder, "internal").isDirectory() || new File(folder, "external").isDirectory();
    }

    static void run(Context c, Progress p) throws IOException {
        File folder = Storage.sharedOrNull(c);
        if (folder == null) throw new IOException("нет доступа ко всем файлам");
        File in = new File(folder, "internal"), ex = new File(folder, "external");
        long total = size(in) + size(ex);
        long[] done = {0};
        if (in.isDirectory()) copyTree(in, c.getDataDir(), done, total, p);
        File extDir = c.getExternalFilesDir(null);
        if (ex.isDirectory() && extDir != null) copyTree(ex, extDir, done, total, p);
        Storage.writeText(marker(c), String.valueOf(System.currentTimeMillis()));
    }

    private static long size(File f) {
        if (f.isFile()) return f.length();
        long n = 0;
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) n += size(k);
        return n;
    }

    private static void copyTree(File src, File dst, long[] done, long total, Progress p) throws IOException {
        if (src.isDirectory()) {
            dst.mkdirs();
            File[] kids = src.listFiles();
            if (kids != null) for (File k : kids) copyTree(k, new File(dst, k.getName()), done, total, p);
            return;
        }
        byte[] buf = new byte[1 << 17];
        try (FileInputStream i = new FileInputStream(src); FileOutputStream o = new FileOutputStream(dst)) {
            int n;
            while ((n = i.read(buf)) > 0) {
                o.write(buf, 0, n);
                done[0] += n;
                if (p != null) p.bytes(done[0], total);
            }
        }
    }
}
