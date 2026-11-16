package com.jamescrumble.mc5bridge;

import android.app.Activity;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageInstaller;
import android.os.Build;

import java.io.File;
import java.io.FileInputStream;
import java.io.IOException;
import java.io.OutputStream;

/** Installs the combined APK through PackageInstaller (one system confirmation); the result comes back through {@link Listener}. */
final class Installer {
    interface Listener {
        void done(boolean ok, String message);
    }

    private static final String ACTION = "com.jamescrumble.mc5bridge.INSTALL_DONE";

    private Installer() {}

    static void install(final Activity a, File apk, final Listener l) throws IOException {
        final PackageInstaller pi = a.getPackageManager().getPackageInstaller();
        PackageInstaller.SessionParams sp = new PackageInstaller.SessionParams(PackageInstaller.SessionParams.MODE_FULL_INSTALL);
        sp.setAppPackageName(Storage.GAME_PACKAGE);
        final int id = pi.createSession(sp);
        try (PackageInstaller.Session s = pi.openSession(id)) {
            try (OutputStream out = s.openWrite("base.apk", 0, apk.length()); FileInputStream in = new FileInputStream(apk)) {
                byte[] buf = new byte[1 << 16];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
                s.fsync(out);
            }
            BroadcastReceiver rx = new BroadcastReceiver() {
                @Override public void onReceive(Context c, Intent i) {
                    int st = i.getIntExtra(PackageInstaller.EXTRA_STATUS, PackageInstaller.STATUS_FAILURE);
                    if (st == PackageInstaller.STATUS_PENDING_USER_ACTION) {
                        Intent confirm = i.getParcelableExtra(Intent.EXTRA_INTENT);
                        if (confirm != null) a.startActivity(confirm.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                        return;
                    }
                    try { a.unregisterReceiver(this); } catch (RuntimeException ignored) { }
                    l.done(st == PackageInstaller.STATUS_SUCCESS, i.getStringExtra(PackageInstaller.EXTRA_STATUS_MESSAGE));
                }
            };
            IntentFilter f = new IntentFilter(ACTION);
            if (Build.VERSION.SDK_INT >= 33) a.registerReceiver(rx, f, Context.RECEIVER_NOT_EXPORTED); else a.registerReceiver(rx, f);
            Intent cb = new Intent(ACTION).setPackage(a.getPackageName());
            PendingIntent pend = PendingIntent.getBroadcast(a, id, cb, PendingIntent.FLAG_MUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            s.commit(pend.getIntentSender());
        }
    }
}
