package com.jamescrumble.mc5bridge;

import android.content.Context;
import android.system.Os;

import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.util.zip.ZipEntry;
import java.util.zip.ZipInputStream;

/**
 * CPython inside this process (documentation/architecture.md): the standard library and the server files come from assets (python.zip, serverroot.zip) and are unpacked
 * into files/; the interpreter libraries are in lib/arm64-v8a. {@link #start} runs a script as __main__ on a background thread; the interpreter
 * can start only once per process, so stopping the server means ending the process.
 */
final class PyHost {
    static { System.loadLibrary("python3.14"); System.loadLibrary("pyhost"); }

    private static Thread thread;
    private static volatile int exitCode = -1;

    private PyHost() {}

    static native int run(String home, String[] args);

    static native void redirectStdio();

    static synchronized boolean running() { return thread != null && thread.isAlive(); }

    static int exitCode() { return exitCode; }

    /** Unpacks an asset zip into root (its entries start with `top/`) when its stamp (the app build) differs from the stored one; only `root/top` is replaced. */
    static void unpack(Context c, String asset, File root, String top, String stamp) throws IOException {
        File mark = new File(root, ".stamp_" + top);
        File dir = new File(root, top);
        if (dir.isDirectory() && mark.isFile() && stamp.equals(Storage.readText(mark))) return;
        Storage.deleteTree(dir);
        root.mkdirs();
        String base = root.getCanonicalPath() + File.separator;
        try (InputStream in = c.getAssets().open(asset); ZipInputStream z = new ZipInputStream(in)) {
            ZipEntry e;
            byte[] buf = new byte[65536];
            while ((e = z.getNextEntry()) != null) {
                File out = new File(root, e.getName());
                if (!out.getCanonicalPath().startsWith(base)) continue;
                if (e.isDirectory()) { out.mkdirs(); continue; }
                out.getParentFile().mkdirs();
                try (FileOutputStream fo = new FileOutputStream(out)) {
                    int n;
                    while ((n = z.read(buf)) > 0) fo.write(buf, 0, n);
                }
            }
        }
        Storage.writeText(mark, stamp);
    }

    /** Starts `script` (path) with the given arguments; returns at once. */
    static synchronized void start(Context c, File home, String script, String... args) throws Exception {
        if (running()) return;
        Os.setenv("TMPDIR", c.getCacheDir().getPath(), true);
        Os.setenv("HOME", c.getFilesDir().getPath(), true);
        Os.setenv("PYTHONDONTWRITEBYTECODE", "", true);
        Os.setenv("PYTHONUNBUFFERED", "1", true);
        redirectStdio();
        String[] argv = new String[args.length + 2];
        argv[0] = "";
        argv[1] = script;
        System.arraycopy(args, 0, argv, 2, args.length);
        final String h = home.getPath();
        thread = new Thread(() -> { exitCode = run(h, argv); }, "python");
        thread.start();
    }
}
