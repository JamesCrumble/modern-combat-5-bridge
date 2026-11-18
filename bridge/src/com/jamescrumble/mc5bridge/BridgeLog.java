package com.jamescrumble.mc5bridge;

import android.content.Context;
import android.os.Build;
import android.util.Log;

import java.io.File;
import java.io.FileOutputStream;
import java.io.PrintWriter;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

/**
 * The player's logs, to attach to a bug report, side by side in BridgeGames/<game package>/: mc5.log is the bridge's own (the installer A
 * and the bridge inside the game B: steps, mode, data, errors, Java crashes), server.log the server's (bridge/python/server_main.py,
 * MC5_LOGFILE). Without access to the folder both are in files/serverdata/ of the private folder. Each is one file of at most {@link #MAX}
 * bytes: over it, the older half is dropped (at a line start) and writing goes on (the server does the same).
 */
final class BridgeLog {
    private static final String TAG = "mc5bridge";
    static final long MAX = 5L * 1024 * 1024;
    private static boolean crashHook;

    private BridgeLog() {}

    /** The bridge's log (mc5.log). */
    static File file(Context c) { return logFile(c, "mc5.log"); }

    /** The server's log (server.log). */
    static File serverFile(Context c) { return logFile(c, "server.log"); }

    private static File logFile(Context c, String name) {
        File shared = Storage.sharedOrNull(c);
        if (shared != null) return new File(shared, name);
        File d = new File(Storage.privateDir(c), "serverdata");
        d.mkdirs();
        return new File(d, name);
    }

    static void i(Context c, String m) {
        Log.i(TAG, m);
        append(c, m);
    }

    static void e(Context c, String m, Throwable t) {
        Log.e(TAG, m, t);
        StringWriter sw = new StringWriter();
        if (t != null) t.printStackTrace(new PrintWriter(sw));
        append(c, m + (t == null ? "" : "\n" + sw.toString().trim()));
    }

    /** First line of a session: what runs where (version, Android, device). */
    static void session(Context c, String who) {
        i(c, "==== " + who + " · мост " + BuildInfo.VERSION + " · Android " + Build.VERSION.RELEASE + " (API " + Build.VERSION.SDK_INT + ") · "
                + Build.MANUFACTURER + " " + Build.MODEL);
    }

    /** Java crashes of this process end up in the log too (native crashes of the game do not: see logcat). */
    static synchronized void hookCrashes(Context c) {
        if (crashHook) return;
        crashHook = true;
        final Context app = c.getApplicationContext();
        final Thread.UncaughtExceptionHandler prev = Thread.getDefaultUncaughtExceptionHandler();
        Thread.setDefaultUncaughtExceptionHandler((th, ex) -> {
            try { e(app, "Сбой (поток " + th.getName() + ")", ex); } catch (Throwable ignored) { }
            if (prev != null) prev.uncaughtException(th, ex);
        });
    }

    /** Keeps the newer half of the file, from the first line start in it. */
    static void trim(File f) {
        try (java.io.RandomAccessFile r = new java.io.RandomAccessFile(f, "r")) {
            long len = r.length(), from = len / 2;
            byte[] b = new byte[(int) (len - from)];
            r.seek(from);
            r.readFully(b);
            int nl = 0;
            while (nl < b.length && b[nl] != '\n') nl++;
            File tmp = new File(f.getPath() + ".tmp");
            try (FileOutputStream out = new FileOutputStream(tmp)) {
                if (nl < b.length) out.write(b, nl + 1, b.length - nl - 1);
            }
            if (!tmp.renameTo(f)) tmp.delete();
        } catch (Exception ignored) { }
    }

    private static synchronized void append(Context c, String m) {
        try {
            File f = file(c);
            if (f.length() > MAX) trim(f);
            String line = new SimpleDateFormat("HH:mm:ss", Locale.ROOT).format(new Date()) + " [bridge] " + m + "\n";
            try (FileOutputStream out = new FileOutputStream(f, true)) {
                out.write(line.getBytes(StandardCharsets.UTF_8));
            }
        } catch (Exception ignored) {
            // the log must never break the bridge
        }
    }
}
