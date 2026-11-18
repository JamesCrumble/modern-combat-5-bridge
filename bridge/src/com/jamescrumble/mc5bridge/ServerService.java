package com.jamescrumble.mc5bridge;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.net.wifi.WifiManager;
import android.os.Build;
import android.os.IBinder;
import android.os.PowerManager;

import java.net.Inet4Address;
import java.net.InetAddress;
import java.net.NetworkInterface;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * Keeps the server (or the forwarders) alive while the game runs in the foreground: Android freezes the processes of a cached app. A foreground
 * service with an ongoing notification; with "access from the local network" also a wake lock and a Wi-Fi lock (as in the EW3 bridge).
 */
public final class ServerService extends Service {
    static final String EXTRA_LAN = "lan";
    static final String EXTRA_CUSTOM = "custom";
    private static final String CHANNEL = "mc5_server";
    private static final int ID = 1;

    private boolean lan;
    private String custom = "";
    private volatile Thread watcher;
    private PowerManager.WakeLock wake;
    private WifiManager.WifiLock wifi;

    static void start(Context c, Settings s) {
        try {
            c.startForegroundService(new Intent(c, ServerService.class).putExtra(EXTRA_LAN, s.on(Settings.SERVER_LAN) && !s.custom())
                    .putExtra(EXTRA_CUSTOM, s.custom() ? s.get(Settings.SERVER_ADDR) : ""));
        } catch (RuntimeException e) {
            // Not allowed from the background: the backend still runs, only without the notification.
        }
    }

    static void stop(Context c) {
        c.stopService(new Intent(c, ServerService.class));
    }

    static boolean notificationsAllowed(Context c) {
        return c.getSystemService(NotificationManager.class).areNotificationsEnabled();
    }

    /** Asks for what the app is missing and Android lets it ask for: notifications (13+) and local-network access (where that permission exists). */
    static void askNotifications(android.app.Activity a) {
        List<String> need = new ArrayList<>();
        if (Build.VERSION.SDK_INT >= 33
                && a.checkSelfPermission(android.Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            need.add(android.Manifest.permission.POST_NOTIFICATIONS);
        }
        final String local = "android.permission.ACCESS_LOCAL_NETWORK";
        if (Build.VERSION.SDK_INT >= 36 && a.checkSelfPermission(local) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            try {
                a.getPackageManager().getPermissionInfo(local, 0);
                need.add(local);
            } catch (android.content.pm.PackageManager.NameNotFoundException notOnThisAndroid) { }
        }
        if (!need.isEmpty()) a.requestPermissions(need.toArray(new String[0]), 3);
    }

    /** IPv4 addresses of this phone on Wi-Fi, Ethernet or its own hotspot (mobile data is left out). */
    static List<String> addresses() {
        List<String> out = new ArrayList<>();
        try {
            for (NetworkInterface ni : Collections.list(NetworkInterface.getNetworkInterfaces())) {
                String n = ni.getName();
                if (!ni.isUp() || ni.isLoopback() || !(n.startsWith("wlan") || n.startsWith("swlan") || n.startsWith("eth")
                        || n.startsWith("ap") || n.startsWith("softap"))) continue;
                for (InetAddress a : Collections.list(ni.getInetAddresses())) {
                    if (a instanceof Inet4Address && !a.isLoopbackAddress() && a.isSiteLocalAddress()) out.add(a.getHostAddress());
                }
            }
        } catch (Exception ignored) { }
        return out;
    }

    @Override public int onStartCommand(Intent intent, int flags, int startId) {
        boolean lan = intent != null && intent.getBooleanExtra(EXTRA_LAN, false);
        String custom = intent == null ? "" : intent.getStringExtra(EXTRA_CUSTOM);
        NotificationManager nm = getSystemService(NotificationManager.class);
        NotificationChannel ch = new NotificationChannel(CHANNEL, "Сервер игры", NotificationManager.IMPORTANCE_LOW);
        ch.setDescription("Состояние сервера Modern Combat 5: отвечает он или нет");
        nm.createNotificationChannel(ch);

        this.lan = lan;
        this.custom = custom == null ? "" : custom;
        Notification n = notification(null);
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(ID, n, android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        } else {
            startForeground(ID, n);
        }
        releaseLocks();
        startWatch();
        if (lan) {
            try {
                wake = getSystemService(PowerManager.class).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "mc5:server");
                wake.acquire();
                wifi = getSystemService(WifiManager.class).createWifiLock(
                        Build.VERSION.SDK_INT >= 29 ? WifiManager.WIFI_MODE_FULL_LOW_LATENCY : WifiManager.WIFI_MODE_FULL_HIGH_PERF, "mc5:server");
                wifi.acquire();
            } catch (RuntimeException ignored) { }
        }
        return START_NOT_STICKY;
    }

    /** The notification states what was found, not what was asked for: `ok` is null while the first check is pending. */
    private Notification notification(Boolean ok) {
        boolean remote = !custom.isEmpty();
        String title;
        StringBuilder text = new StringBuilder();
        if (ok == null) {
            title = "Modern Combat 5: проверяю сервер";
            text.append(remote ? "Сервер " + custom : "Сервер на этом телефоне (127.0.0.1:18080)");
        } else if (remote) {
            title = ok ? "Modern Combat 5: сервер отвечает" : "Modern Combat 5: нет связи с сервером";
            text.append(ok ? "Игра подключена к серверу " + custom : "Сервер " + custom + " не отвечает на порту " + Backend.HTTP_PORT
                    + ". Проверьте адрес и что сервер запущен.");
        } else {
            title = ok ? "Modern Combat 5: сервер работает" : "Modern Combat 5: сервер не отвечает";
            text.append(ok ? "Сервер на этом телефоне (127.0.0.1:18080)" : "Встроенный сервер не отвечает. Что случилось — «Журнал сервера» ниже.");
            if (ok && lan) {
                List<String> ips = addresses();
                if (ips.isEmpty()) text.append("\nЛокальная сеть: нет подключения к Wi-Fi");
                for (String ip : ips) text.append("\nДругой телефон: сервер по адресу ").append(ip);
            }
        }
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, SettingsActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK
                | Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification.Builder b = new Notification.Builder(this, CHANNEL)
                .setSmallIcon(android.R.drawable.stat_notify_sync_noanim)
                .setContentTitle(title)
                .setContentText(text.toString().split("\n")[0])
                .setStyle(new Notification.BigTextStyle().bigText(text.toString()))
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .setCategory(Notification.CATEGORY_SERVICE);
        if (!remote) {   // the built-in server writes the log; with another server there is none on this phone
            PendingIntent log = PendingIntent.getActivity(this, 1, new Intent(this, LogActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK),
                    PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
            b.addAction(new Notification.Action.Builder(android.graphics.drawable.Icon.createWithResource("android",
                    android.R.drawable.ic_menu_info_details), "Журнал сервера", log).build());
        }
        return b.build();
    }

    /** Checks the server every few seconds and refreshes the notification when the answer changes. */
    private void startWatch() {
        stopWatch();
        final String host = custom.isEmpty() ? "127.0.0.1" : custom;
        final NotificationManager nm = getSystemService(NotificationManager.class);
        Thread t = new Thread(() -> {
            Boolean last = null;
            while (watcher == Thread.currentThread()) {
                boolean ok = Backend.ready(host);
                if (last == null || last != ok) {
                    last = ok;
                    nm.notify(ID, notification(ok));
                }
                try { Thread.sleep(ok ? 10000 : 3000); } catch (InterruptedException e) { return; }
            }
        }, "mc5-watch");
        t.setDaemon(true);
        watcher = t;
        t.start();
    }

    private void stopWatch() {
        Thread t = watcher;
        watcher = null;
        if (t != null) t.interrupt();
    }

    private void releaseLocks() {
        try { if (wake != null && wake.isHeld()) wake.release(); } catch (RuntimeException ignored) { }
        try { if (wifi != null && wifi.isHeld()) wifi.release(); } catch (RuntimeException ignored) { }
        wake = null;
        wifi = null;
    }

    @Override public void onDestroy() {
        stopWatch();
        releaseLocks();
        Backend.flushMirror(this);
        super.onDestroy();
    }

    @Override public IBinder onBind(Intent intent) {
        return null;
    }
}
