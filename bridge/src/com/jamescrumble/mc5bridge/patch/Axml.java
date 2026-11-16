package com.jamescrumble.mc5bridge.patch;

import java.io.IOException;
import java.nio.ByteBuffer;
import java.nio.ByteOrder;
import java.util.ArrayList;
import java.util.List;

/**
 * Binary AndroidManifest.xml (AXML) editor for the combined APK (documentation/architecture.md): adds the bridge components, clears requiredSplitTypes,
 * sets debuggable. UTF-16 string pool, no style spans (as in the Play manifest).
 * Edits: {@link #clearString}, {@link #setBool}, {@link #unlauncher}, {@link #addPermission}, {@link #addComponent}, {@link #addProperty}.
 * Attributes are written sorted by resource id (the framework resolves them in that order); resource-mapped attribute names the pool
 * lacks are inserted at the end of the mapped prefix and every string index is shifted.
 */
public final class Axml {
    static final int NONE = -1;
    public static final int RID_NAME = 0x01010003, RID_LABEL = 0x01010001, RID_EXPORTED = 0x01010010, RID_ORIENT = 0x0101001e, RID_VALUE = 0x01010024,
            RID_MAXSDK = 0x01010271, RID_FGS = 0x01010599, RID_CLEARTEXT = 0x010104ec, RID_EXTRACT = 0x010104ea, RID_DEBUGGABLE = 0x0101000f;
    static final int T_STRING = 0x03, T_INT_DEC = 0x10, T_INT_HEX = 0x11, T_BOOL = 0x12;

    private final List<String> strs = new ArrayList<>();
    private final List<Integer> rid = new ArrayList<>();
    private final List<byte[]> nodes = new ArrayList<>();
    private int nsAndroid = NONE;

    private static final class Attr {
        int id, ns, name, raw, type, data;
    }

    // ------------------------------------------------------------------ parse / serialize
    public static Axml parse(byte[] b) throws IOException {
        ByteBuffer bb = ByteBuffer.wrap(b).order(ByteOrder.LITTLE_ENDIAN);
        if (b.length < 8 || (bb.getShort(0) & 0xffff) != 3) throw new IOException("not binary XML");
        Axml x = new Axml();
        int off = 8;
        while (off + 8 <= b.length) {
            int type = bb.getShort(off) & 0xffff, size = bb.getInt(off + 4);
            if (size < 8 || off + size > b.length) break;
            if (type == 1) {
                int count = bb.getInt(off + 8), styles = bb.getInt(off + 12), flags = bb.getInt(off + 16), start = bb.getInt(off + 20);
                if (styles != 0) throw new IOException("style spans are not supported");
                if ((flags & 0x100) != 0) throw new IOException("UTF-8 string pool is not supported");
                for (int i = 0; i < count; i++) {
                    int p = off + start + bb.getInt(off + 28 + 4 * i);
                    int len = bb.getShort(p) & 0xffff;
                    p += 2;
                    if ((len & 0x8000) != 0) { len = (len & 0x7fff) << 16 | (bb.getShort(p) & 0xffff); p += 2; }
                    char[] c = new char[len];
                    for (int k = 0; k < len; k++) c[k] = (char) (bb.getShort(p + 2 * k) & 0xffff);
                    x.strs.add(new String(c));
                }
            } else if (type == 0x180) {
                for (int i = 0; i < (size - 8) / 4; i++) x.rid.add(bb.getInt(off + 8 + 4 * i));
            } else if (type >= 0x100 && type <= 0x104) {
                byte[] d = new byte[size];
                System.arraycopy(b, off, d, 0, size);
                x.nodes.add(d);
            }
            off += size;
        }
        if (x.strs.isEmpty() || x.rid.isEmpty()) throw new IOException("no string pool / resource map");
        x.nsAndroid = x.strs.indexOf("http://schemas.android.com/apk/res/android");
        if (x.nsAndroid < 0) throw new IOException("no android namespace");
        return x;
    }

    public byte[] toBytes() {
        int poolData = 0;
        for (String s : strs) poolData += (s.length() >= 0x8000 ? 4 : 2) + 2 * s.length() + 2;
        int poolHdr = 28 + 4 * strs.size(), poolSize = poolHdr + ((poolData + 3) & ~3);
        int rmSize = 8 + 4 * rid.size(), nodesSize = 0;
        for (byte[] n : nodes) nodesSize += n.length;
        int total = 8 + poolSize + rmSize + nodesSize;
        ByteBuffer o = ByteBuffer.allocate(total).order(ByteOrder.LITTLE_ENDIAN);
        o.putShort((short) 3).putShort((short) 8).putInt(total);
        int pool = o.position();
        o.putShort((short) 1).putShort((short) 28).putInt(poolSize).putInt(strs.size()).putInt(0).putInt(0).putInt(poolHdr).putInt(0);
        int cur = 0;
        for (String s : strs) {
            o.putInt(cur);
            cur += (s.length() >= 0x8000 ? 4 : 2) + 2 * s.length() + 2;
        }
        for (String s : strs) {
            int l = s.length();
            if (l >= 0x8000) { o.putShort((short) (0x8000 | (l >> 16))).putShort((short) (l & 0xffff)); } else o.putShort((short) l);
            for (int k = 0; k < l; k++) o.putShort((short) s.charAt(k));
            o.putShort((short) 0);
        }
        o.position(pool + poolSize);
        o.putShort((short) 0x180).putShort((short) 8).putInt(rmSize);
        for (int id : rid) o.putInt(id);
        for (byte[] n : nodes) o.put(n);
        return o.array();
    }

    // ------------------------------------------------------------------ helpers
    private static int u16(byte[] d, int o) { return (d[o] & 0xff) | (d[o + 1] & 0xff) << 8; }
    private static int i32(byte[] d, int o) { return u16(d, o) | u16(d, o + 2) << 16; }
    private static void p16(byte[] d, int o, int v) { d[o] = (byte) v; d[o + 1] = (byte) (v >> 8); }
    private static void p32(byte[] d, int o, int v) { p16(d, o, v); p16(d, o + 2, v >> 16); }

    private int find(String s) { return strs.indexOf(s); }

    private int get(String s) {                      // a string without resource id: after the mapped prefix
        for (int i = rid.size(); i < strs.size(); i++) if (strs.get(i).equals(s)) return i;
        strs.add(s);
        return strs.size() - 1;
    }

    private int remap(int v) { return v != NONE && v >= rid.size() ? v + 1 : v; }

    /** The string index of a resource-mapped attribute name (inserted when missing; all indices shift). */
    private int attrName(int id, String name) {
        int at = rid.indexOf(id);
        if (at >= 0) return at;
        at = rid.size();
        strs.add(at, name);
        for (byte[] d : nodes) {
            int t = u16(d, 0);
            if (t == 0x100 || t == 0x101 || t == 0x103) { p32(d, 16, remap(i32(d, 16))); p32(d, 20, remap(i32(d, 20))); }
            else if (t == 0x102) {
                p32(d, 16, remap(i32(d, 16))); p32(d, 20, remap(i32(d, 20)));
                int as = u16(d, 24), sz = u16(d, 26), cnt = u16(d, 28);
                for (int i = 0; i < cnt; i++) {
                    int a = 16 + as + i * sz;
                    p32(d, a, remap(i32(d, a))); p32(d, a + 4, remap(i32(d, a + 4))); p32(d, a + 8, remap(i32(d, a + 8)));
                    if ((d[a + 15] & 0xff) == T_STRING) p32(d, a + 16, remap(i32(d, a + 16)));
                }
            } else if (t == 0x104) p32(d, 16, remap(i32(d, 16)));
        }
        rid.add(id);
        if (nsAndroid != NONE) nsAndroid = remap(nsAndroid);
        return at;
    }

    private Attr aStr(int id, String nm, String v) {
        int s = get(v);
        Attr a = new Attr();
        a.id = id; a.ns = nsAndroid; a.name = attrName(id, nm); a.raw = s; a.type = T_STRING; a.data = s;
        return a;
    }

    private Attr aVal(int id, String nm, int type, int v) {
        Attr a = new Attr();
        a.id = id; a.ns = nsAndroid; a.name = attrName(id, nm); a.raw = NONE; a.type = type; a.data = v;
        return a;
    }

    private static byte[] start(int name, List<Attr> at) {
        at.sort((x, y) -> Integer.compareUnsigned(x.id, y.id));
        int sz = 36 + 20 * at.size();
        byte[] d = new byte[sz];
        p16(d, 0, 0x102); p16(d, 2, 16); p32(d, 4, sz); p32(d, 8, 1); p32(d, 12, NONE);
        p32(d, 16, NONE); p32(d, 20, name);
        p16(d, 24, 20); p16(d, 26, 20); p16(d, 28, at.size());
        for (int i = 0; i < at.size(); i++) {
            Attr a = at.get(i);
            int o = 36 + 20 * i;
            p32(d, o, a.ns); p32(d, o + 4, a.name); p32(d, o + 8, a.raw); p16(d, o + 12, 8); d[o + 14] = 0; d[o + 15] = (byte) a.type; p32(d, o + 16, a.data);
        }
        return d;
    }

    private static byte[] end(int name) {
        byte[] d = new byte[24];
        p16(d, 0, 0x103); p16(d, 2, 16); p32(d, 4, 24); p32(d, 8, 1); p32(d, 12, NONE);
        p32(d, 16, NONE); p32(d, 20, name);
        return d;
    }

    private int findStart(int name, int from) {
        for (int k = from; k < nodes.size(); k++) if (u16(nodes.get(k), 0) == 0x102 && i32(nodes.get(k), 20) == name) return k;
        return NONE;
    }

    private int findEnd(int name) {
        for (int k = nodes.size() - 1; k >= 0; k--) if (u16(nodes.get(k), 0) == 0x103 && i32(nodes.get(k), 20) == name) return k;
        return NONE;
    }

    private int attrString(byte[] d, int resid) {
        int as = u16(d, 24), sz = u16(d, 26), cnt = u16(d, 28);
        for (int i = 0; i < cnt; i++) {
            int a = 16 + as + i * sz, nm = i32(d, a + 4);
            if (nm >= 0 && nm < rid.size() && rid.get(nm) == resid && (d[a + 15] & 0xff) == T_STRING) return i32(d, a + 16);
        }
        return NONE;
    }

    // ------------------------------------------------------------------ edits
    /** Make a string of the pool empty (drops requiredSplitTypes: a merged APK installs without splits). */
    public void clearString(String s) throws IOException {
        int i = find(s);
        if (i < 0) throw new IOException("string not found: " + s);
        strs.set(i, "");
    }

    /** Set a boolean attribute of `<application>` (inserted in resource-id order when it is absent). */
    public void setAppBool(int id, String name, boolean value) {
        attrName(id, name);
        int k = findStart(find("application"), 0);
        byte[] d = nodes.get(k);
        int nameIdx = rid.indexOf(id);
        int as = u16(d, 24), sz = u16(d, 26), cnt = u16(d, 28);
        for (int i = 0; i < cnt; i++) {
            int a = 16 + as + i * sz;
            if (i32(d, a + 4) == nameIdx) { d[a + 15] = (byte) T_BOOL; p32(d, a + 8, NONE); p32(d, a + 16, value ? NONE : 0); return; }
        }
        int at = 0;
        while (at < cnt) {
            int nm = i32(d, 16 + as + at * sz + 4);
            int aid = nm >= 0 && nm < rid.size() ? rid.get(nm) : -1;
            if (Integer.compareUnsigned(aid, id) > 0) break;
            at++;
        }
        int head = 16 + as + at * sz;
        byte[] nd = new byte[d.length + 20];
        System.arraycopy(d, 0, nd, 0, head);
        p32(nd, head, nsAndroid); p32(nd, head + 4, nameIdx); p32(nd, head + 8, NONE); p16(nd, head + 12, 8); nd[head + 14] = 0;
        nd[head + 15] = (byte) T_BOOL; p32(nd, head + 16, value ? NONE : 0);
        System.arraycopy(d, head, nd, head + 20, d.length - head);
        p32(nd, 4, nd.length); p16(nd, 28, cnt + 1);
        nodes.set(k, nd);
    }

    /** The LAUNCHER category of an existing activity becomes DEFAULT (the game's own icon goes away). */
    public void unlauncher(String activity) throws IOException {
        int want = find(activity), lc = find("android.intent.category.LAUNCHER"), df = get("android.intent.category.DEFAULT");
        int sAct = find("activity"), sCat = find("category");
        if (want < 0 || lc < 0) throw new IOException("unlauncher: unknown activity or no LAUNCHER: " + activity);
        for (int k = findStart(sAct, 0); k != NONE; k = findStart(sAct, k + 1)) {
            if (attrString(nodes.get(k), RID_NAME) != want) continue;
            int done = 0;
            for (int j = k + 1; j < nodes.size() && !(u16(nodes.get(j), 0) == 0x103 && i32(nodes.get(j), 20) == sAct); j++) {
                byte[] d = nodes.get(j);
                if (u16(d, 0) == 0x102 && i32(d, 20) == sCat && attrString(d, RID_NAME) == lc) {
                    int as = u16(d, 24), sz = u16(d, 26), cnt = u16(d, 28);
                    for (int i = 0; i < cnt; i++) {
                        int a = 16 + as + i * sz, nm = i32(d, a + 4);
                        if (nm >= 0 && nm < rid.size() && rid.get(nm) == RID_NAME) { p32(d, a + 8, df); p32(d, a + 16, df); done++; }
                    }
                }
            }
            if (done == 0) throw new IOException("unlauncher: LAUNCHER category not found in " + activity);
            return;
        }
        throw new IOException("unlauncher: activity not found: " + activity);
    }

    private boolean hasPermission(String name) {
        int up = find("uses-permission");
        for (byte[] d : nodes) {
            if (u16(d, 0) == 0x102 && i32(d, 20) == up) {
                int v = attrString(d, RID_NAME);
                if (v != NONE && strs.get(v).equals(name)) return true;
            }
        }
        return false;
    }

    /** `<uses-permission>` before `<application>`; maxSdk 0 = none; false when it was already there. */
    public boolean addPermission(String name, int maxSdk) {
        if (hasPermission(name)) return false;
        List<Attr> at = new ArrayList<>();
        at.add(aStr(RID_NAME, "name", name));
        if (maxSdk > 0) at.add(aVal(RID_MAXSDK, "maxSdkVersion", T_INT_DEC, maxSdk));
        int perm = get("uses-permission"), pos = findStart(find("application"), 0);
        nodes.add(pos, start(perm, at));
        nodes.add(pos + 1, end(perm));
        return true;
    }

    private int lastComponentEnd = NONE;

    /** `<service>` or `<activity>` at the end of `<application>`; options: exported, fgs, orient; launcher adds MAIN + LAUNCHER. */
    public void addComponent(boolean service, String name, Boolean exported, Integer fgs, Integer orient, boolean launcher, String label) {
        List<Attr> at = new ArrayList<>();
        at.add(aStr(RID_NAME, "name", name));
        if (label != null) at.add(aStr(RID_LABEL, "label", label));
        if (exported != null) at.add(aVal(RID_EXPORTED, "exported", T_BOOL, exported ? NONE : 0));
        if (fgs != null) at.add(aVal(RID_FGS, "foregroundServiceType", T_INT_HEX, fgs));
        if (orient != null) at.add(aVal(RID_ORIENT, "screenOrientation", T_INT_DEC, orient));
        int comp = get(service ? "service" : "activity"), filter = get("intent-filter"), action = get("action"), cat = get("category");
        List<Attr> aA = new ArrayList<>(), aC = new ArrayList<>();
        if (launcher) {
            aA.add(aStr(RID_NAME, "name", "android.intent.action.MAIN"));
            aC.add(aStr(RID_NAME, "name", "android.intent.category.LAUNCHER"));
        }
        int pos = findEnd(find("application"));
        nodes.add(pos++, start(comp, at));
        if (launcher) {
            nodes.add(pos++, start(filter, new ArrayList<>()));
            nodes.add(pos++, start(action, aA)); nodes.add(pos++, end(action));
            nodes.add(pos++, start(cat, aC)); nodes.add(pos++, end(cat));
            nodes.add(pos++, end(filter));
        }
        lastComponentEnd = pos;
        nodes.add(pos, end(comp));
    }

    /** `<property>` child of the component added last. */
    public void addProperty(String name, String value) throws IOException {
        if (lastComponentEnd == NONE) throw new IOException("property without a component");
        int prop = get("property");
        List<Attr> at = new ArrayList<>();
        at.add(aStr(RID_NAME, "name", name));
        at.add(aStr(RID_VALUE, "value", value));
        nodes.add(lastComponentEnd++, start(prop, at));
        nodes.add(lastComponentEnd++, end(prop));
    }

    /** All attribute names the spec may need, inserted first so that cached element-name indices stay valid. */
    public void prepare() {
        attrName(RID_NAME, "name"); attrName(RID_LABEL, "label"); attrName(RID_EXPORTED, "exported"); attrName(RID_ORIENT, "screenOrientation");
        attrName(RID_VALUE, "value"); attrName(RID_MAXSDK, "maxSdkVersion"); attrName(RID_FGS, "foregroundServiceType");
        attrName(RID_CLEARTEXT, "usesCleartextTraffic"); attrName(RID_EXTRACT, "extractNativeLibs"); attrName(RID_DEBUGGABLE, "debuggable");
    }

    /**
     * Applies a manifest spec (bridge/manifest_add.txt): `perm NAME [max=N]`, `app-bool cleartext|extract|debuggable 0|1`,
     * `service|activity NAME [exported=0|1] [fgs=0xNN] [orient=N] [launcher] [label="Text"]`, `property NAME VALUE...`, `unlauncher NAME`.
     */
    public void applySpec(String spec) throws IOException {
        prepare();
        for (String raw : spec.split("\n")) {
            String line = raw.contains("#") ? raw.substring(0, raw.indexOf('#')) : raw;
            line = line.trim();
            if (line.isEmpty()) continue;
            String[] t = line.split("\\s+", 3);
            switch (t[0]) {
                case "perm": {
                    String[] p = line.split("\\s+");
                    int max = p.length > 2 && p[2].startsWith("max=") ? Integer.parseInt(p[2].substring(4)) : 0;
                    addPermission(p[1], max);
                    break;
                }
                case "app-bool": {
                    String[] p = line.split("\\s+");
                    boolean v = !p[2].equals("0");
                    switch (p[1]) {
                        case "cleartext": setAppBool(RID_CLEARTEXT, "usesCleartextTraffic", v); break;
                        case "extract": setAppBool(RID_EXTRACT, "extractNativeLibs", v); break;
                        case "debuggable": setAppBool(RID_DEBUGGABLE, "debuggable", v); break;
                        default: throw new IOException("app-bool: unknown attribute " + p[1]);
                    }
                    break;
                }
                case "service":
                case "activity": {
                    String label = null;
                    java.util.regex.Matcher lm = java.util.regex.Pattern.compile(" label=\"([^\"]*)\"").matcher(line);
                    if (lm.find()) { label = lm.group(1); line = line.substring(0, lm.start()) + line.substring(lm.end()); }
                    String[] p = line.split("\\s+");
                    Boolean exp = null; Integer fgs = null, orient = null; boolean launcher = false;
                    for (int i = 2; i < p.length; i++) {
                        if (p[i].startsWith("exported=")) exp = !p[i].endsWith("=0");
                        else if (p[i].startsWith("fgs=")) fgs = (int) Long.decode(p[i].substring(4)).longValue();
                        else if (p[i].startsWith("orient=")) orient = Integer.parseInt(p[i].substring(7));
                        else if (p[i].equals("launcher")) launcher = true;
                        else throw new IOException("component: unknown option " + p[i]);
                    }
                    addComponent(t[0].equals("service"), p[1], exp, fgs, orient, launcher, label);
                    break;
                }
                case "property": {
                    if (t.length < 3) throw new IOException("property: name and value");
                    addProperty(t[1], t[2]);
                    break;
                }
                case "unlauncher": unlauncher(t[1]); break;
                default: throw new IOException("unknown manifest directive: " + t[0]);
            }
        }
    }
}
