package com.jamescrumble.mc5bridge.patch;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Map;
import java.util.Set;

/**
 * Byte patches of the game's native library by a spec file (bridge/patch/native.spec): the game version is checked by the SHA-256 of the original,
 * every `bytes` patch checks the old bytes, every `string` patch must find the string. Format: see the spec file.
 */
public final class NativePatch {
    private NativePatch() {}

    /** Name of the library the spec patches (the `file` line), or null. */
    public static String file(String spec) {
        for (String line : lines(spec)) if (line.startsWith("file ")) return line.split("\\s+")[1];
        return null;
    }

    private static String[] lines(String spec) {
        java.util.List<String> out = new java.util.ArrayList<>();
        for (String raw : spec.split("\n")) {
            String s = raw.contains("#") ? raw.substring(0, raw.indexOf('#')) : raw;
            s = s.trim();
            if (!s.isEmpty()) out.add(s);
        }
        return out.toArray(new String[0]);
    }

    public static String sha256(byte[] b) throws IOException {
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(b);
            StringBuilder sb = new StringBuilder();
            for (byte x : d) sb.append(String.format("%02x", x & 0xff));
            return sb.toString();
        } catch (java.security.NoSuchAlgorithmException e) {
            throw new IOException(e);
        }
    }

    private static byte[] hex(String s) {
        byte[] b = new byte[s.length() / 2];
        for (int i = 0; i < b.length; i++) b[i] = (byte) Integer.parseInt(s.substring(2 * i, 2 * i + 2), 16);
        return b;
    }

    private static int indexOf(byte[] h, byte[] n, int from) {
        outer:
        for (int i = from; i + n.length <= h.length; i++) {
            for (int k = 0; k < n.length; k++) if (h[i + k] != n[k]) continue outer;
            return i;
        }
        return -1;
    }

    /** Patches the library in place. `options`: names switched on for `if NAME`; `vars`: ${NAME} of the spec. */
    public static void apply(byte[] lib, String spec, Set<String> options, Map<String, String> vars) throws IOException {
        boolean on = true;
        for (String line : lines(spec)) {
            if (line.startsWith("file ")) {
                String[] p = line.split("\\s+");
                if (p.length >= 4 && p[2].equals("sha256")) {
                    String h = sha256(lib);
                    if (!h.equals(p[3])) throw new IOException("unsupported game version: " + p[1] + " sha256 " + h + " (expected " + p[3] + ")");
                }
            } else if (line.startsWith("if ")) {
                on = options.contains(line.substring(3).trim());
            } else if (!on) {
                continue;
            } else if (line.startsWith("string ")) {
                String[] ab = line.substring(7).split("=>", 2);
                String a = ab[0].trim(), b = subst(ab[1].trim(), vars);
                byte[] old = a.getBytes(StandardCharsets.UTF_8), nw = b.getBytes(StandardCharsets.UTF_8);
                if (nw.length > old.length) throw new IOException("new string is longer than the old: " + a + " -> " + b);
                int n = 0;
                for (int i = indexOf(lib, old, 0); i >= 0; i = indexOf(lib, old, i + old.length)) {
                    java.util.Arrays.fill(lib, i, i + old.length, (byte) 0);
                    System.arraycopy(nw, 0, lib, i, nw.length);
                    n++;
                }
                if (n == 0) throw new IOException("string not found: " + a);
            } else if (line.startsWith("bytes ")) {
                String[] p = line.substring(6).split("=>", 2);
                String[] left = p[0].trim().split("\\s+");
                int off = (int) Long.parseLong(left[0], 16);
                byte[] old = hex(left[1]), nw = hex(p[1].trim());
                if (old.length != nw.length) throw new IOException("bytes: lengths differ at " + left[0]);
                for (int k = 0; k < old.length; k++)
                    if (lib[off + k] != old[k]) throw new IOException("bytes at 0x" + left[0] + " are not as expected (game version?)");
                System.arraycopy(nw, 0, lib, off, nw.length);
            } else {
                throw new IOException("unknown native.spec directive: " + line);
            }
        }
    }

    private static String subst(String s, Map<String, String> vars) throws IOException {
        java.util.regex.Matcher m = java.util.regex.Pattern.compile("\\$\\{([A-Z_0-9]+)\\}").matcher(s);
        StringBuffer sb = new StringBuffer();
        while (m.find()) {
            String v = vars.get(m.group(1));
            if (v == null) throw new IOException("undefined variable ${" + m.group(1) + "}");
            m.appendReplacement(sb, java.util.regex.Matcher.quoteReplacement(v));
        }
        m.appendTail(sb);
        return sb.toString();
    }
}
