package com.jamescrumble.mc5bridge;

import android.content.Context;
import android.system.Os;

import java.io.File;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.net.Socket;
import java.util.List;

/**
 * What runs for the game (documentation/architecture.md): in "local server" mode the embedded Python server on the game's ports; in "server at address" mode the
 * forwarders. The interpreter starts once per process, so a changed server configuration restarts the process ({@link #restartProcess}).
 */
final class Backend {
    static final int HTTP_PORT = 18080;
    private static String runningKey;
    private static Forwarder forwarder;
    private static String error = "";

    private Backend() {}

    static synchronized boolean started() { return runningKey != null; }

    static synchronized String key() { return runningKey; }

    static synchronized String error() { return error; }

    /** Starts (or confirms) the backend for these settings. Returns null, or what went wrong. */
    static synchronized String start(Context c, Settings s) {
        String key = s.backendKey();
        if (runningKey != null && !runningKey.equals(key)) return "restart";           // the caller restarts the process
        if (runningKey != null) return null;
        error = "";
        BridgeLog.session(c, "игра");
        BridgeLog.i(c, "Запуск: " + (s.custom() ? "подключение к серверу " + s.get(Settings.SERVER_ADDR) : "встроенный сервер" + (s.on(Settings.SERVER_LAN) ? ", доступ из локальной сети" : "")));
        try {
            if (s.custom()) {
                if (!Settings.validIpv4(s.get(Settings.SERVER_ADDR))) return error = "Введите IPv4-адрес сервера";
                forwarder = new Forwarder(s.get(Settings.SERVER_ADDR));
                List<Integer> failed = forwarder.start();
                if (!failed.isEmpty()) {
                    forwarder.stop();
                    forwarder = null;
                    BridgeLog.i(c, "Порты заняты: " + failed);
                    return error = "Порты заняты другим приложением (adb reverse?): " + failed;
                }
            } else {
                startPython(c, s);
            }
            runningKey = key;
            return null;
        } catch (NoDataException e) {
            BridgeLog.i(c, e.getMessage());
            return error = e.getMessage();
        } catch (Throwable t) {
            BridgeLog.e(c, "Не удалось запустить сервер", t);
            return error = "Не удалось запустить сервер: " + t;
        }
    }

    private static void startPython(Context c, Settings s) throws Exception {
        File root = Storage.privateDir(c);
        PyHost.unpack(c, "python.zip", root, "python", BuildInfo.STAMP);
        PyHost.unpack(c, "serverroot.zip", root, "serverroot", BuildInfo.STAMP);
        File sroot = new File(root, "serverroot");
        File data = new File(root, "serverdata");
        data.mkdirs();
        File script = new File(c.getCacheDir(), "server_main.py");
        try (InputStream in = c.getAssets().open("server_main.py"); OutputStream out = new java.io.FileOutputStream(script)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
        }
        Os.setenv("MC5_SERVERROOT", sroot.getPath(), true);
        Os.setenv("MC5_LOGFILE", BridgeLog.serverFile(c).getPath(), true);   // BridgeGames/<game>/server.log (or the private one)
        Os.setenv("MC5_UVICORN_LOG", s.on(Settings.SERVER_DEBUG) ? "debug" : "warning", true);
        String tls = new File(sroot, "server/tls").getPath();
        File shared = Storage.sharedOrNull(c);
        // saved progress moved from another server (PC): BridgeGames/<bridge>/mc5_state.json is taken over once, when the bridge has no state of its own
        File state = new File(data, "mc5_state.json");
        if (!state.isFile() && shared != null && new File(shared, "mc5_state.json").isFile()) {
            try (InputStream in = new java.io.FileInputStream(new File(shared, "mc5_state.json")); OutputStream out = new java.io.FileOutputStream(state)) {
                byte[] buf = new byte[8192];
                int n;
                while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            }
        }
        Os.setenv("MC5_STATE_MIRROR", shared != null ? new File(shared, "mc5_state.json").getPath() : "", true);
        String bald = baldDir(c, shared, data).getPath();
        File gameData = serverData(shared, DataImport.privateServerData(c), sroot);
        if (gameData == null && DataImport.extractServerData(c) != null) gameData = serverData(shared, DataImport.privateServerData(c), sroot);
        if (gameData == null) throw new NoDataException(shared);
        BridgeLog.i(c, "Данные сервера: " + gameData.getPath() + "; главы: " + bald);
        PyHost.start(c, new File(root, "python"), script.getPath(),
                "--host", s.on(Settings.SERVER_LAN) ? "0.0.0.0" : "127.0.0.1",
                "--tls-cert", tls + "/self.pem", "--tls-key", tls + "/self.key",
                "--state", new File(data, "mc5_state.json").getPath(), "--bald", bald, "--data", gameData.getPath());
    }

    /** Folder with the server's Gameloft reference data (CRM, events, item catalogue, Iris pictures, campaign table). It is not part of the
     *  APK of a release (documentation/architecture.md): it comes in the cache archive (server-data/, unpacked to the private {@code unpacked}
     *  by {@link DataImport}) or as a folder {@code BridgeGames/<game>/server-data/}. Personal builds also carry it inside the APK
     *  (serverroot/server/data). Null = none found. */
    static File serverData(File shared, File unpacked, File sroot) {
        java.util.List<File> cand = new java.util.ArrayList<>();
        if (shared != null) {
            cand.add(new File(shared, "server-data"));
            cand.add(new File(shared, "server-data/server-data"));   // an archive of the folder unpacked into a folder of the same name
        }
        if (unpacked != null) cand.add(unpacked);
        if (sroot != null) cand.add(new File(sroot, "server/data"));
        for (File f : cand) if (new File(f, "ah/crm.json").isFile()) return f;
        return null;
    }

    static final class NoDataException extends Exception {
        NoDataException(File shared) {
            super("Нет данных сервера. Положите архив кэша игры (MC5-cache-….zip, ссылка в описании релиза) в "
                    + (shared != null ? shared.getPath() : "/sdcard/BridgeGames/<пакет игры>") + "/ и нажмите «Играть» ещё раз.");
        }
    }

    /** BALD store the server serves to the game (Iris `bald___index___` etc. and the chapter archives). The game keeps its downloaded BALD in its own
     *  external folder (`Android/data/<game>/files/bald`, filled from `BridgeGames/<game>/external/` by DataImport); with the game inside this app
     *  (combined APK B) that is our own external files dir. Without it the server answered 404 to `bald_android_astc_h___index` and the client offered
     *  PRELOAD for chapters it already had (16.11). First existing folder with the index wins. */
    static File baldDir(Context c, File shared, File data) {
        java.util.List<File> cand = new java.util.ArrayList<>();
        File ext = c.getExternalFilesDir(null);
        if (ext != null) cand.add(new File(ext, "bald"));
        if (shared != null) {
            cand.add(new File(shared, "external/bald"));
            cand.add(new File(shared, "bald"));
        }
        cand.add(new File(data, "bald"));
        for (File f : cand) if (new File(f, "bald___index___.txt").isFile()) return f;
        return cand.get(0);
    }

    /** Is the backend answering on the game's HTTP port? (local: the server's own check; custom: the remote one.) */
    static boolean ready(Settings s) {
        return ready(s.custom() ? s.get(Settings.SERVER_ADDR) : "127.0.0.1");
    }

    static boolean ready(String host) {
        try (Socket so = new Socket()) {
            so.connect(new InetSocketAddress("127.0.0.1", HTTP_PORT), 1500);
            so.setSoTimeout(3000);
            so.getOutputStream().write(("GET /_mc5/ready HTTP/1.0\r\nHost: " + host + "\r\n\r\n").getBytes("US-ASCII"));
            byte[] b = new byte[512];
            int n = so.getInputStream().read(b);
            return n > 0 && new String(b, 0, n, "US-ASCII").contains("200");
        } catch (Exception e) {
            return false;
        }
    }

    /** Copies the live state into the shared mirror at once: the server mirrors at most every 10 s, and the process is ended by a kill, which it cannot see. */
    static void flushMirror(Context c) {
        File shared = Storage.sharedOrNull(c);
        File state = new File(new File(Storage.privateDir(c), "serverdata"), "mc5_state.json");
        if (shared == null || !state.isFile()) {
            android.util.Log.i("mc5bridge", "flushMirror: nothing to do (shared=" + shared + ", state=" + state.isFile() + ")");
            return;
        }
        File dst = new File(shared, "mc5_state.json");
        File tmp = new File(shared, "mc5_state.json.tmp");
        if (copy(state, tmp) && tmp.renameTo(dst)) {
            BridgeLog.i(c, "Прогресс скопирован в mc5_state.json: " + dst.length() + " bytes");
            return;
        }
        // MediaProvider can refuse the rename on shared storage: write the mirror itself (a copy of 150 KB, so a tear is unlikely and the next save repairs it)
        tmp.delete();
        BridgeLog.i(c, "Прогресс: rename failed, direct copy " + copy(state, dst) + ", " + dst.length() + " bytes");
    }

    private static boolean copy(File from, File to) {
        try (InputStream in = new java.io.FileInputStream(from); OutputStream out = new java.io.FileOutputStream(to)) {
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) out.write(buf, 0, n);
            return true;
        } catch (java.io.IOException e) {
            return false;
        }
    }

    /** Ends this process after relaunching the settings screen: the way to apply a changed server configuration. */
    static void restartProcess(Context c) {
        flushMirror(c);
        android.content.Intent i = c.getPackageManager().getLaunchIntentForPackage(c.getPackageName());
        if (i != null) {
            i.addFlags(android.content.Intent.FLAG_ACTIVITY_NEW_TASK | android.content.Intent.FLAG_ACTIVITY_CLEAR_TASK);
            android.app.PendingIntent pi = android.app.PendingIntent.getActivity(c, 7, i, android.app.PendingIntent.FLAG_IMMUTABLE | android.app.PendingIntent.FLAG_CANCEL_CURRENT);
            android.app.AlarmManager am = c.getSystemService(android.app.AlarmManager.class);
            am.set(android.app.AlarmManager.RTC, System.currentTimeMillis() + 600, pi);
        }
        android.os.Process.killProcess(android.os.Process.myPid());
    }
}
