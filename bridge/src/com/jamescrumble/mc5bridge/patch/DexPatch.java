package com.jamescrumble.mc5bridge.patch;

import com.android.tools.smali.baksmali.Adaptors.ClassDefinition;
import com.android.tools.smali.baksmali.BaksmaliOptions;
import com.android.tools.smali.baksmali.formatter.BaksmaliWriter;
import com.android.tools.smali.dexlib2.Opcodes;
import com.android.tools.smali.dexlib2.dexbacked.DexBackedDexFile;
import com.android.tools.smali.dexlib2.iface.ClassDef;
import com.android.tools.smali.smali.Smali;
import com.android.tools.smali.smali.SmaliOptions;

import java.io.File;
import java.io.IOException;
import java.io.StringWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Builds the overlay dex of the combined APK (documentation/architecture.md): the classes of the game that the patches change are disassembled from the game's own
 * dex (baksmali), changed as text by the spec files (bridge/patch/dex/*.spec) and assembled again (smali) into a small dex that goes first in the APK.
 * Nothing of the game's code is stored in the bridge: the patch is applied from scratch to the original files every time.
 *
 * Spec format (one logic for the PC build and the phone):
 * <pre>
 * @class pkg/Name                  smali class (path without .smali); all directives below apply to it
 * @method sig                      replace the body of the method (modifiers stay as they are); body lines up to @end
 * @replace / @with / @count N / @end   replace the text between @replace and @with by the text up to @count (or @end), exactly N times (default 1)
 * @insert-after / @with / @end    insert the @with text right after the anchor text (must occur exactly once)
 * @newclass pkg/Name ... @end      a class that is not in the game (debug helpers): the text is assembled as it is
 * </pre>
 * `${NAME}` in the text is replaced from the variables. Lines starting with `#` outside a block are comments.
 */
public final class DexPatch {
    private static final int API = 34;      // dex 039: smali 3.0.10 writes a broken header for the 041 container format of API 35

    private DexPatch() {}

    private static final class Op {
        String kind, sig, a, b;
        int count = 1;
    }

    /** Parses specs into operations grouped by class (smali path without extension), in file order. */
    static Map<String, List<Op>> parse(List<String> specs, Map<String, String> vars) throws IOException {
        Map<String, List<Op>> out = new LinkedHashMap<>();
        for (String spec : specs) {
            String cls = null;
            Op op = null;
            StringBuilder cur = null;
            String part = null;
            for (String raw : spec.split("\n", -1)) {
                String line = raw.endsWith("\r") ? raw.substring(0, raw.length() - 1) : raw;
                if (op == null) {
                    if (line.isEmpty() || line.startsWith("#")) continue;
                    if (line.startsWith("@class ")) { cls = line.substring(7).trim(); continue; }
                    if (line.startsWith("@newclass ")) {          // a class that is not in the game: the smali text up to @end is taken as it is
                        cls = line.substring(10).trim();
                        op = new Op();
                        op.kind = "newclass";
                        cur = new StringBuilder();
                        continue;
                    }
                    if (cls == null) throw new IOException("directive before @class: " + line);
                    op = new Op();
                    cur = new StringBuilder();
                    if (line.startsWith("@method ")) { op.kind = "method"; op.sig = line.substring(8).trim(); part = "a"; }
                    else if (line.equals("@replace")) { op.kind = "replace"; part = "a"; }
                    else if (line.equals("@insert-after")) { op.kind = "insert"; part = "a"; }
                    else throw new IOException("unknown directive: " + line);
                    continue;
                }
                if (line.equals("@with") && !op.kind.equals("method")) { op.a = cur.toString(); cur = new StringBuilder(); part = "b"; continue; }
                if (line.startsWith("@count ")) { op.count = Integer.parseInt(line.substring(7).trim()); continue; }
                if (line.equals("@end")) {
                    String text = cur.toString();
                    op.b = text;
                    if (op.kind.equals("method") || op.kind.equals("newclass")) op.a = null;
                    op.a = op.a == null ? null : subst(trimNl(op.a), vars);
                    op.b = subst(trimNl(op.b), vars);
                    out.computeIfAbsent(cls, k -> new ArrayList<>()).add(op);
                    op = null;
                    continue;
                }
                cur.append(line).append('\n');
            }
            if (op != null) throw new IOException("unterminated block (missing @end)");
        }
        return out;
    }

    private static String trimNl(String s) {
        return s.endsWith("\n") ? s.substring(0, s.length() - 1) : s;
    }

    private static String subst(String s, Map<String, String> vars) throws IOException {
        Matcher m = Pattern.compile("\\$\\{([A-Z_0-9]+)\\}").matcher(s);
        StringBuffer sb = new StringBuffer();
        while (m.find()) {
            String v = vars.get(m.group(1));
            if (v == null) throw new IOException("undefined variable ${" + m.group(1) + "}");
            m.appendReplacement(sb, Matcher.quoteReplacement(v));
        }
        m.appendTail(sb);
        return sb.toString();
    }

    private static int count(String s, String sub) {
        int n = 0;
        for (int i = s.indexOf(sub); i >= 0; i = s.indexOf(sub, i + sub.length())) n++;
        return n;
    }

    static String apply(String cls, String smali, List<Op> ops) throws IOException {
        for (Op op : ops) {
            switch (op.kind) {
                case "method": {
                    Pattern p = Pattern.compile("(?m)^\\.method((?: [a-z\\-]+)*) " + Pattern.quote(op.sig) + "\\n.*?^\\.end method\\n", Pattern.DOTALL);
                    Matcher m = p.matcher(smali);
                    if (!m.find()) throw new IOException(cls + ": method not found: " + op.sig);
                    String body = ".method" + m.group(1) + " " + op.sig + "\n" + op.b + "\n.end method\n";
                    smali = smali.substring(0, m.start()) + body + smali.substring(m.end());
                    break;
                }
                case "replace": {
                    int n = count(smali, op.a);
                    if (n != op.count) throw new IOException(cls + ": expected " + op.count + " x [" + op.a + "], found " + n);
                    smali = smali.replace(op.a, op.b);
                    break;
                }
                case "insert": {
                    int n = count(smali, op.a);
                    if (n != 1) throw new IOException(cls + ": anchor expected once, found " + n + ": " + op.a);
                    int at = smali.indexOf(op.a) + op.a.length();
                    smali = smali.substring(0, at) + "\n" + op.b + smali.substring(at);
                    break;
                }
                default:
                    throw new IOException("bad op " + op.kind);
            }
        }
        return smali;
    }

    /** The smali text of one class of the dex, or null when it is not there. */
    public static String disassemble(DexBackedDexFile dex, String cls) throws IOException {
        String type = "L" + cls + ";";
        for (ClassDef cd : dex.getClasses()) {
            if (!cd.getType().equals(type)) continue;
            StringWriter sw = new StringWriter();
            BaksmaliWriter w = new BaksmaliWriter(sw, null);
            BaksmaliOptions bo = new BaksmaliOptions();
            bo.localsDirective = true;        // `.locals N` as in the specs (apktool's default)
            new ClassDefinition(bo, cd).writeTo(w);
            w.flush();
            return sw.toString();
        }
        return null;
    }

    /**
     * @param dexBytes the game's dex that holds the classes (classes4.dex of 6.0.12a)
     * @param specs    texts of the spec files
     * @param vars     variables of the specs
     * @param work     scratch folder (smali files)
     * @param out      the overlay dex to write
     * @return the classes that were patched
     */
    public static List<String> build(byte[] dexBytes, List<String> specs, Map<String, String> vars, File work, File out) throws IOException {
        Map<String, List<Op>> ops = parse(specs, vars);
        DexBackedDexFile dex = new DexBackedDexFile(Opcodes.forApi(API), dexBytes);
        List<String> done = new ArrayList<>();
        for (Map.Entry<String, List<Op>> e : ops.entrySet()) {
            String smali;
            if (e.getValue().size() == 1 && e.getValue().get(0).kind.equals("newclass")) {
                smali = e.getValue().get(0).b + "\n";
            } else {
                smali = disassemble(dex, e.getKey());
                if (smali == null) throw new IOException("class not in the dex: " + e.getKey());
                smali = apply(e.getKey(), smali, e.getValue());
            }
            File f = new File(work, e.getKey() + ".smali");
            f.getParentFile().mkdirs();
            Files.write(f.toPath(), smali.getBytes(StandardCharsets.UTF_8));
            done.add(e.getKey());
        }
        SmaliOptions so = new SmaliOptions();
        so.apiLevel = API;
        so.outputDexFile = out.getPath();
        if (!Smali.assemble(so, work.getPath())) throw new IOException("smali: assembling the patched classes failed");
        return done;
    }
}
