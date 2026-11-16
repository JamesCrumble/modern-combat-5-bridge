package com.jamescrumble.mc5bridge;

import android.content.Context;

import java.io.File;
import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;

/** Bridge settings: KEY=VALUE per line in settings.txt (like the EW3 bridge). */
final class Settings {
    static final String SERVER_CUSTOM = "SERVER_CUSTOM";   // 1: the game talks to another server (ports of this phone forward to SERVER_ADDR)
    static final String SERVER_ADDR = "SERVER_ADDR";
    static final String SERVER_LAN = "SERVER_LAN";         // 1: the built-in server listens on the network (a second phone can use it)
    static final String SERVER_DEBUG = "SERVER_DEBUG";     // 1: verbose server log

    final Map<String, String> v = new LinkedHashMap<>();

    static Settings load(Context c) {
        Settings s = new Settings();
        File f = Storage.settingsFile(c);
        if (!f.isFile()) return s;
        try {
            for (String line : Storage.readText(f).split("\n")) {
                int eq = line.indexOf('=');
                if (eq > 0) s.v.put(line.substring(0, eq).trim(), line.substring(eq + 1).trim());
            }
        } catch (IOException ignored) { }
        return s;
    }

    boolean save(Context c) {
        StringBuilder sb = new StringBuilder();
        for (Map.Entry<String, String> e : v.entrySet()) sb.append(e.getKey()).append('=').append(e.getValue()).append('\n');
        try {
            Storage.writeText(Storage.settingsFile(c), sb.toString());
            return true;
        } catch (IOException e) {
            return false;
        }
    }

    boolean on(String key) { return "1".equals(v.get(key)); }

    String get(String key) { return v.containsKey(key) ? v.get(key) : ""; }

    boolean custom() { return on(SERVER_CUSTOM); }

    /** A dotted IPv4 address. */
    static boolean validIpv4(String a) {
        if (a == null || !a.matches("\\d{1,3}(\\.\\d{1,3}){3}")) return false;
        for (String part : a.split("\\.")) if (Integer.parseInt(part) > 255) return false;
        return true;
    }

    /** What decides whether a running backend must be restarted when the player presses Play. */
    String backendKey() {
        return (custom() ? "custom:" + get(SERVER_ADDR) : "local:" + (on(SERVER_LAN) ? "lan" : "loop")) + (on(SERVER_DEBUG) ? ":debug" : "");
    }
}
