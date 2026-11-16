import com.jamescrumble.mc5bridge.patch.Keys;
import com.jamescrumble.mc5bridge.patch.Patcher;

import java.awt.Color;
import java.awt.Font;
import java.awt.Graphics2D;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.nio.file.Files;
import java.util.Arrays;
import javax.imageio.ImageIO;

/**
 * PC front of the patcher (tools/build_full.sh, tools/build_debug.sh): the same code as on the phone, specs from bridge/patch.
 * usage: PcMain <base.apk> <arm64.apk> <bridge.apk> <out.apk> <work dir> <key file (created when missing)> <spec dir> [debug]
 * "debug": the build "MC5 Debug" (debuggable game + the logging libmc5trace.so, trace hooks, name and icon of its own).
 */
public final class PcMain {
    /** The launcher icon with a red "DEBUG" band across the lower part. */
    static byte[] badge(String name, byte[] png) {
        try {
            BufferedImage in = ImageIO.read(new ByteArrayInputStream(png));
            BufferedImage out = new BufferedImage(in.getWidth(), in.getHeight(), BufferedImage.TYPE_INT_ARGB);
            Graphics2D g = out.createGraphics();
            g.drawImage(in, 0, 0, null);
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            int w = in.getWidth(), h = in.getHeight(), bh = Math.max(8, h / 5), y = h * 2 / 3 - bh / 2;
            g.setColor(new Color(0xE5, 0x39, 0x35, 235));
            g.fillRect(0, y, w, bh);
            g.setColor(Color.WHITE);
            g.setFont(new Font(Font.SANS_SERIF, Font.BOLD, Math.max(6, bh * 3 / 4)));
            java.awt.FontMetrics fm = g.getFontMetrics();
            g.drawString("DEBUG", (w - fm.stringWidth("DEBUG")) / 2, y + (bh + fm.getAscent() - fm.getDescent()) / 2);
            g.dispose();
            ByteArrayOutputStream bo = new ByteArrayOutputStream();
            ImageIO.write(out, "png", bo);
            return bo.toByteArray();
        } catch (Exception e) {
            return null;
        }
    }

    public static void main(String[] a) throws Exception {
        File keyFile = new File(a[5]);
        Keys keys;
        if (keyFile.exists()) keys = Keys.load(keyFile);
        else { keys = Keys.create(a.length > 7 ? "MC5 Debug" : "MC5 Bridge"); keys.save(keyFile); }
        final File specDir = new File(a[6]);
        Patcher.Options o = new Patcher.Options();
        o.vars = Patcher.defaultVars("com.gameloft.android.ANMP.GloftM5HM");
        if (a.length > 7 && a[7].equals("debug")) {
            o.dexSpecs.add("dex/trace.spec");
            o.extraLibs = Arrays.asList("libmc5trace.so=libmc5trace.so", "wrap-trace.sh=wrap.sh");
            o.manifestSpec = "manifest_debug.txt";
            o.transformPattern = "res/mipmap[^/]*/ic_launcher(_foreground)?\\.png";
            o.transform = PcMain::badge;
        }
        long t = System.currentTimeMillis();
        Patcher.build(new File(a[0]), new File(a[1]), new File(a[2]), new File(a[3]), new File(a[4]), keys,
                name -> new String(Files.readAllBytes(new File(specDir, name).toPath()), "UTF-8"), o, m -> System.out.println("[patcher] " + m));
        System.out.println("[patcher] " + (System.currentTimeMillis() - t) / 1000 + " с");
    }
}
