package com.jamescrumble.mc5bridge;

import android.content.Context;

import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.Enumeration;
import java.util.zip.ZipEntry;
import java.util.zip.ZipFile;

/**
 * First start of the combined APK (B): the player's game data goes to the places the game reads (A cannot write into the private folder
 * of B, B does it itself). Sources in {@code BridgeGames/<package>/} (documentation/architecture.md):
 * <ul>
 * <li>the cache archive: any {@code .zip} with top folders {@code internal/}, {@code external/}, {@code server-data/} (the name does not matter);
 *     it is unpacked straight to the places, no intermediate copy;</li>
 * <li>or the folders {@code internal/} (= the game's private folder: files/, shared_prefs/ ...) and {@code external/} (= Android/data/&lt;package&gt;/files).</li>
 * </ul>
 * {@code server-data/} goes to the private {@code files/server-data} of the bridge (the server's reference data, {@link Backend#serverData}).
 * A marker file in files/ keeps the import from running twice; the data is not touched afterwards.
 */
final class DataImport {
    interface Progress {
        void bytes(long done, long total);
    }

    static final String INTERNAL = "internal/", EXTERNAL = "external/", SERVER_DATA = "server-data/";

    private DataImport() {}

    static File marker(Context c) {
        return new File(c.getFilesDir(), ".bridge_data_imported");
    }

    /** The server data unpacked from the cache archive (private). */
    static File privateServerData(Context c) {
        return new File(c.getFilesDir(), "server-data");
    }

    /** The cache archive in the folder: the largest .zip that has internal/, external/ or server-data/ at its top, or null. */
    static File cacheZip(File folder) {
        File[] files = folder == null ? null : folder.listFiles();
        File best = null;
        if (files == null) return null;
        for (File f : files) {
            if (!f.isFile() || !f.getName().toLowerCase(java.util.Locale.ROOT).endsWith(".zip")) continue;
            if (!hasTop(f, INTERNAL) && !hasTop(f, EXTERNAL) && !hasTop(f, SERVER_DATA)) continue;
            if (best == null || f.length() > best.length()) best = f;
        }
        return best;
    }

    /** Does the archive have entries under this top folder? */
    static boolean hasTop(File zip, String top) {
        try (ZipFile z = new ZipFile(zip)) {
            Enumeration<? extends ZipEntry> en = z.entries();
            while (en.hasMoreElements()) if (en.nextElement().getName().startsWith(top)) return true;
        } catch (IOException | RuntimeException e) {
            return false;
        }
        return false;
    }

    /**
     * Why no game cache was found, for the player and mc5.log: every entry of the folder, its name in quotes (so stray spaces and double
     * extensions like "….zip.zip" show), and why it was or was not taken.
     */
    static String explain(File folder) {
        File[] files = folder == null ? null : folder.listFiles();
        if (files == null) return "Папка " + q(String.valueOf(folder)) + " не читается.";
        if (files.length == 0) return "Папка " + q(folder.getPath()) + " пуста.";
        java.util.Arrays.sort(files);
        StringBuilder sb = new StringBuilder("Содержимое папки " + q(folder.getPath()) + ":");
        for (File f : files) sb.append("\n• ").append(q(f.getName())).append(" — ").append(verdict(f));
        return sb.toString();
    }

    private static String verdict(File f) {
        String name = f.getName(), low = name.toLowerCase(java.util.Locale.ROOT);
        if (f.isDirectory()) {
            if (name.equals("internal") || name.equals("external")) return "папка с данными игры вместо архива: берётся при первом запуске";
            if (name.equals("server-data")) {
                return new File(f, "ah/crm.json").isFile() || new File(f, "server-data/ah/crm.json").isFile()
                        ? "папка с данными сервера вместо архива: берётся" : "папка server-data, но в ней нет \"ah/crm.json\": не берётся";
            }
            return "папка, не используется";
        }
        String size = f.length() + " байт";
        if (!low.endsWith(".zip")) {
            return "файл, " + size + ": не архив кэша" + (low.contains(".zip") ? " (имя не заканчивается на \".zip\" — скачивание не закончено или файл переименован)" : "");
        }
        return "zip, " + size + ": " + problem(f);
    }

    /** What is wrong with this .zip as the cache archive ("подходит" when nothing). */
    private static String problem(File zip) {
        java.util.Set<String> tops = new java.util.TreeSet<>();
        boolean crm = false;
        try (ZipFile z = new ZipFile(zip)) {
            for (Enumeration<? extends ZipEntry> en = z.entries(); en.hasMoreElements(); ) {
                String n = en.nextElement().getName();
                int i = n.indexOf('/');
                tops.add(i < 0 ? n : n.substring(0, i + 1));
                crm |= n.equals(SERVER_DATA + "ah/crm.json");
            }
        } catch (IOException | RuntimeException e) {
            return "не открывается как zip (" + e + ") — скачан не полностью или повреждён, скачайте заново.";
        }
        java.util.List<String> missing = new java.util.ArrayList<>();
        for (String t : new String[] {INTERNAL, EXTERNAL, SERVER_DATA}) if (!tops.contains(t)) missing.add(q(t));
        if (missing.isEmpty()) return crm ? "подходит" : "в \"server-data/\" нет \"ah/crm.json\" — архив неполный, скачайте заново.";
        java.util.List<String> seen = new java.util.ArrayList<>();
        for (String t : tops) seen.add(q(t));
        String list = seen.size() <= 8 ? String.join(", ", seen) : String.join(", ", seen.subList(0, 8)) + " и ещё " + (seen.size() - 8);
        return "в корне архива нет " + String.join(", ", missing) + "; в корне: " + list
                + ". Папки \"internal/\", \"external/\", \"server-data/\" должны лежать прямо в корне архива, без папки над ними.";
    }

    private static String q(String s) {
        return "\"" + s + "\"";
    }

    /** Is there something to import and has it not been imported yet? */
    static boolean pending(Context c) {
        File folder = Storage.sharedOrNull(c);
        if (folder == null || marker(c).exists()) return false;
        return new File(folder, "internal").isDirectory() || new File(folder, "external").isDirectory() || cacheZip(folder) != null;
    }

    static void run(Context c, Progress p) throws IOException {
        File folder = Storage.sharedOrNull(c);
        if (folder == null) throw new IOException("нет доступа ко всем файлам");
        File extDir = c.getExternalFilesDir(null);
        File zip = cacheZip(folder);
        if (zip != null) {
            unzip(zip, c.getDataDir(), extDir, privateServerData(c), p);
        } else {
            File in = new File(folder, "internal"), ex = new File(folder, "external");
            long total = size(in) + size(ex);
            long[] done = {0};
            if (in.isDirectory()) copyTree(in, c.getDataDir(), done, total, p);
            if (ex.isDirectory() && extDir != null) copyTree(ex, extDir, done, total, p);
        }
        Storage.writeText(marker(c), String.valueOf(System.currentTimeMillis()));
    }

    /** Only the server data of the cache archive (it was put there after the game data had been imported). Returns the folder or null. */
    static File extractServerData(Context c) throws IOException {
        File zip = cacheZip(Storage.sharedOrNull(c));
        if (zip == null || !hasTop(zip, SERVER_DATA)) return null;
        File dst = privateServerData(c);
        Storage.deleteTree(dst);
        unzip(zip, null, null, dst, null);
        return dst;
    }

    /** Unpacks internal/ -> data, external/ -> ext, server-data/ -> sd (a null target skips that part); entries outside a target are refused. */
    private static void unzip(File zip, File data, File ext, File sd, Progress p) throws IOException {
        try (ZipFile z = new ZipFile(zip)) {
            long total = 0, done = 0;
            for (Enumeration<? extends ZipEntry> en = z.entries(); en.hasMoreElements(); ) {
                ZipEntry e = en.nextElement();
                if (target(e.getName(), data, ext, sd) != null && !e.isDirectory()) total += Math.max(0, e.getSize());
            }
            byte[] buf = new byte[1 << 17];
            for (Enumeration<? extends ZipEntry> en = z.entries(); en.hasMoreElements(); ) {
                ZipEntry e = en.nextElement();
                File out = target(e.getName(), data, ext, sd);
                if (out == null) continue;
                if (e.isDirectory()) { out.mkdirs(); continue; }
                out.getParentFile().mkdirs();
                try (InputStream i = z.getInputStream(e); FileOutputStream o = new FileOutputStream(out)) {
                    int n;
                    while ((n = i.read(buf)) > 0) {
                        o.write(buf, 0, n);
                        done += n;
                        if (p != null) p.bytes(done, total);
                    }
                }
            }
        }
    }

    private static File target(String name, File data, File ext, File sd) throws IOException {
        File root;
        String rest;
        if (name.startsWith(INTERNAL) && data != null) { root = data; rest = name.substring(INTERNAL.length()); }
        else if (name.startsWith(EXTERNAL) && ext != null) { root = ext; rest = name.substring(EXTERNAL.length()); }
        else if (name.startsWith(SERVER_DATA) && sd != null) { root = sd; rest = name.substring(SERVER_DATA.length()); }
        else return null;
        if (rest.isEmpty()) return null;
        File out = new File(root, rest);
        if (!out.getCanonicalPath().startsWith(root.getCanonicalPath() + File.separator)) return null;   // zip-slip
        return out;
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
