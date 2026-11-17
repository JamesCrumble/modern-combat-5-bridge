package com.jamescrumble.mc5bridge.patch;

import com.android.apksig.ApkSigner;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Builds the combined APK B (documentation/architecture.md) from the original Play files: base.apk + the arm64 split + the parts of the bridge (dex, libraries, assets).
 * The same code runs on the PC (tools/build_full.sh through {@link PcMain}) and on the phone, so the two cannot drift apart. Steps:
 * 1. version check and native patches (native.spec), 2. manifest (clearString, extractNativeLibs, debuggable, manifest_add.txt),
 * 3. overlay dex from the game's classes4.dex (dex/*.spec), 4. one zip (dex shifted by one: the overlay goes first), 5. signature.
 */
public final class Patcher {
    /** The spec files (native.spec, manifest_add.txt, dex/*.spec) and where they come from: a folder on the PC, assets on the phone. */
    public interface Specs {
        String text(String name) throws IOException;
    }

    public interface Progress {
        void step(String message);
    }

    public static final class Options {
        /** Names for `if NAME` in native.spec. */
        public Set<String> flags = new HashSet<>(java.util.Arrays.asList("TLS_NOVERIFY", "IAP_NOVERIFY"));
        public Map<String, String> vars = new HashMap<>();
        /** dex spec files applied to classes4.dex. */
        public List<String> dexSpecs = new ArrayList<>(java.util.Arrays.asList("dex/net.spec", "dex/assets.spec", "dex/hosts.spec", "dex/iap.spec", "dex/didomi.spec"));
        /** The dex of the game that holds the patched classes. */
        public String patchedDex = "classes4.dex";
        /**
         * Redirect of the game's hosts (wrap.sh + preload library) from the bridge APK, "name in the bridge APK=name in the game" (lib/arm64-v8a/):
         * the product uses the quiet libmc5net.so, the debug build the logging libmc5trace.so.
         */
        public List<String> extraLibs = new ArrayList<>(java.util.Arrays.asList("libmc5net.so=libmc5net.so", "wrap-net.sh=wrap.sh"));
        public boolean debuggable = true;
        /** Entries of the game that are replaced by a transformed copy (regex on the entry name; the debug build puts a badge on the icon). */
        public String transformPattern = null;
        public java.util.function.BiFunction<String, byte[], byte[]> transform = null;
        public String manifestSpec = "manifest_add.txt";
    }

    private Patcher() {}

    public static Map<String, String> defaultVars(String gamePackage) {
        Map<String, String> v = new HashMap<>();
        v.put("EVE_URL", "http://127.0.0.1:18080");
        v.put("EVE_BASE", "http://127.0.0.1:18080");
        v.put("EVE_HOST", "127.0.0.1:18080");
        v.put("EVE_SCHEME", "http://");
        v.put("PKG_FILES", "/data/user/0/" + gamePackage + "/files/assetpacks/");
        return v;
    }

    private static boolean signatureFile(String n) {
        if (!n.startsWith("META-INF/") || n.indexOf('/', 9) >= 0) return false;
        String u = n.toUpperCase(java.util.Locale.ROOT);
        return u.endsWith(".SF") || u.endsWith(".RSA") || u.endsWith(".DSA") || u.endsWith(".EC") || u.equals("META-INF/MANIFEST.MF");
    }

    /**
     * @param base       base.apk of the game
     * @param arm64      split_config.arm64_v8a.apk
     * @param bridgeApk  the bridge's own APK: classes.dex, lib/arm64-v8a/*, assets/* go into B
     * @param out        the signed APK
     * @param work       scratch folder
     */
    public static void build(File base, File arm64, File bridgeApk, File out, File work, Keys keys, Specs specs, Options o, Progress p) throws IOException {
        work.mkdirs();
        try (Zip.Reader rb = new Zip.Reader(base); Zip.Reader ra = new Zip.Reader(arm64); Zip.Reader rg = new Zip.Reader(bridgeApk)) {
            // 1. native library
            p.step("Библиотека игры: проверка версии и правки");
            String nativeSpec = specs.text("native.spec");
            String libName = NativePatch.file(nativeSpec);
            if (libName == null || !ra.entries.containsKey(libName)) throw new IOException("в arm64-части нет " + libName);
            byte[] lib = ra.read(libName);
            NativePatch.apply(lib, nativeSpec, o.flags, o.vars);

            // 2. manifest
            p.step("Манифест");
            Axml x = Axml.parse(rb.read("AndroidManifest.xml"));
            x.clearString("base__abi,base__density");
            x.prepare();
            x.setAppBool(Axml.RID_EXTRACT, "extractNativeLibs", true);
            if (o.debuggable) x.setAppBool(Axml.RID_DEBUGGABLE, "debuggable", true);
            x.applySpec(specs.text(o.manifestSpec));
            byte[] manifest = x.toBytes();

            // 3. overlay dex
            p.step("Классы игры: правка из оригинала (smali)");
            List<String> dexSpecs = new ArrayList<>();
            for (String s : o.dexSpecs) dexSpecs.add(specs.text(s));
            File smaliDir = new File(work, "smali");
            File overlay = new File(work, "overlay.dex");
            List<String> patched = DexPatch.build(rb.read(o.patchedDex), dexSpecs, o.vars, smaliDir, overlay);
            p.step("Правлено классов: " + patched.size());

            // 4. zip
            p.step("Сборка APK");
            File unsigned = new File(work, "unsigned.apk");
            try (Zip.Writer w = new Zip.Writer(new FileOutputStream(unsigned))) {
                w.add("AndroidManifest.xml", manifest, false, 4);
                w.addFile("classes.dex", overlay, false, 4);
                List<String> dex = new ArrayList<>();
                for (String n : rb.entries.keySet()) if (n.matches("classes\\d*\\.dex")) dex.add(n);
                Collections.sort(dex, (a, b) -> Integer.compare(dexNo(a), dexNo(b)));
                int next = 2;
                for (String n : dex) w.copy(rb.entries.get(n), "classes" + next++ + ".dex", 4);
                for (Zip.Entry e : rb.entries.values()) {
                    String n = e.name;
                    if (n.equals("AndroidManifest.xml") || n.matches("classes\\d*\\.dex") || signatureFile(n) || n.endsWith("/")) continue;
                    if (o.transform != null && o.transformPattern != null && n.matches(o.transformPattern)) {
                        byte[] nd = o.transform.apply(n, rb.read(n));
                        if (nd != null) { w.add(n, nd, e.stored(), 4); continue; }
                    }
                    w.copy(e, n, e.stored() ? 4 : 1);
                }
                List<String> bdex = new ArrayList<>();
                for (String n : rg.entries.keySet()) if (n.matches("classes\\d*\\.dex")) bdex.add(n);
                Collections.sort(bdex, (a, b) -> Integer.compare(dexNo(a), dexNo(b)));
                for (String n : bdex) w.copy(rg.entries.get(n), "classes" + next++ + ".dex", 4);
                for (Zip.Entry e : ra.entries.values()) {
                    if (!e.name.startsWith("lib/arm64-v8a/") || e.name.endsWith("/")) continue;
                    if (e.name.equals(libName)) w.add(e.name, lib, true, 4096);
                    else w.copy(e, e.name, 4096);
                }
                Set<String> redirectSrc = new HashSet<>();
                for (String pair : o.extraLibs) {
                    String[] sd = pair.split("=");
                    redirectSrc.add("lib/arm64-v8a/" + sd[0]);
                    if (!rg.entries.containsKey("lib/arm64-v8a/" + sd[0])) throw new IOException("в мосте нет lib/arm64-v8a/" + sd[0]);
                    w.add("lib/arm64-v8a/" + sd[1], rg.read("lib/arm64-v8a/" + sd[0]), true, 4096);
                }
                for (Zip.Entry e : rg.entries.values()) {
                    boolean mine = e.name.startsWith("lib/arm64-v8a/") && !e.name.endsWith("/")
                            && !redirectSrc.contains(e.name) && !e.name.startsWith("lib/arm64-v8a/libmc5") && !e.name.startsWith("lib/arm64-v8a/wrap");
                    boolean asset = e.name.startsWith("assets/") && !e.name.endsWith("/");
                    if ((mine || asset) && !w.has(e.name)) w.copy(e, e.name, mine ? 4096 : 4);
                }
            }

            // 5. signature
            p.step("Подпись");
            ApkSigner.SignerConfig sc = new ApkSigner.SignerConfig.Builder("mc5", keys.key, Collections.singletonList(keys.cert)).build();
            new ApkSigner.Builder(Collections.singletonList(sc)).setInputApk(unsigned).setOutputApk(out)
                    .setMinSdkVersion(24).setV1SigningEnabled(false).setV2SigningEnabled(true).setV3SigningEnabled(true).build().sign();
            unsigned.delete();
            p.step("Готово: " + out.length() / (1024 * 1024) + " МБ");
        } catch (com.android.apksig.apk.ApkFormatException | java.security.GeneralSecurityException e) {
            throw new IOException(e);
        }
    }

    private static int dexNo(String n) {
        String d = n.substring(7, n.length() - 4);
        return d.isEmpty() ? 1 : Integer.parseInt(d);
    }
}
