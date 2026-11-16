package com.jamescrumble.mc5bridge.patch;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.IOException;
import java.math.BigInteger;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.KeyPair;
import java.security.KeyPairGenerator;
import java.security.PrivateKey;
import java.security.SecureRandom;
import java.security.Signature;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import java.util.Base64;
import java.util.Date;

/**
 * The signing key of the combined APK (documentation/architecture.md): created on the device (RSA 2048, self-signed certificate written as DER by hand: Android has no
 * sun.security.x509) and kept in `BridgeGames/<package>/patched-apk.key` (two Base64 lines: PKCS#8 private key, X.509 certificate).
 */
public final class Keys {
    public final PrivateKey key;
    public final X509Certificate cert;

    private Keys(PrivateKey k, X509Certificate c) { key = k; cert = c; }

    public static Keys create(String commonName) throws IOException {
        try {
            KeyPairGenerator g = KeyPairGenerator.getInstance("RSA");
            g.initialize(2048);
            KeyPair kp = g.generateKeyPair();
            byte[] sigAlg = seq(oid(new int[] {1, 2, 840, 113549, 1, 1, 11}), new byte[] {5, 0});
            byte[] name = seq(set(seq(oid(new int[] {2, 5, 4, 3}), tlv(0x0c, commonName.getBytes(StandardCharsets.UTF_8)))));
            long now = System.currentTimeMillis();
            byte[] validity = seq(utc(now - 86400000L), utc(now + 8000L * 86400000L));
            byte[] serial = new BigInteger(63, new SecureRandom()).add(BigInteger.ONE).toByteArray();
            byte[] tbs = seq(tlv(0xa0, tlv(0x02, new byte[] {2})), tlv(0x02, serial), sigAlg, name, validity, name, kp.getPublic().getEncoded());
            Signature s = Signature.getInstance("SHA256withRSA");
            s.initSign(kp.getPrivate());
            s.update(tbs);
            byte[] sig = s.sign();
            byte[] bits = new byte[sig.length + 1];
            System.arraycopy(sig, 0, bits, 1, sig.length);
            byte[] der = seq(tbs, sigAlg, tlv(0x03, bits));
            X509Certificate c = (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(new java.io.ByteArrayInputStream(der));
            return new Keys(kp.getPrivate(), c);
        } catch (java.security.GeneralSecurityException e) {
            throw new IOException(e);
        }
    }

    public void save(File f) throws IOException {
        try {
            String text = Base64.getEncoder().encodeToString(key.getEncoded()) + "\n" + Base64.getEncoder().encodeToString(cert.getEncoded()) + "\n";
            java.nio.file.Files.write(f.toPath(), text.getBytes(StandardCharsets.US_ASCII));
        } catch (java.security.cert.CertificateEncodingException e) {
            throw new IOException(e);
        }
    }

    public static Keys load(File f) throws IOException {
        try {
            String[] l = new String(java.nio.file.Files.readAllBytes(f.toPath()), StandardCharsets.US_ASCII).trim().split("\\s+");
            if (l.length != 2) throw new IOException("bad key file: " + f);
            PrivateKey k = KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(Base64.getDecoder().decode(l[0])));
            X509Certificate c = (X509Certificate) CertificateFactory.getInstance("X.509").generateCertificate(new java.io.ByteArrayInputStream(Base64.getDecoder().decode(l[1])));
            return new Keys(k, c);
        } catch (java.security.GeneralSecurityException | IllegalArgumentException e) {
            throw new IOException("bad key file: " + f, e);
        }
    }

    // ---- DER
    private static byte[] tlv(int tag, byte[] v) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        o.write(tag);
        if (v.length < 128) o.write(v.length);
        else if (v.length < 256) { o.write(0x81); o.write(v.length); }
        else { o.write(0x82); o.write(v.length >> 8); o.write(v.length & 0xff); }
        o.write(v, 0, v.length);
        return o.toByteArray();
    }

    private static byte[] cat(byte[]... p) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        for (byte[] b : p) o.write(b, 0, b.length);
        return o.toByteArray();
    }

    private static byte[] seq(byte[]... p) { return tlv(0x30, cat(p)); }
    private static byte[] set(byte[]... p) { return tlv(0x31, cat(p)); }

    private static byte[] oid(int[] a) {
        ByteArrayOutputStream o = new ByteArrayOutputStream();
        o.write(a[0] * 40 + a[1]);
        for (int i = 2; i < a.length; i++) {
            int v = a[i];
            byte[] t = new byte[5];
            int n = 0;
            t[n++] = (byte) (v & 0x7f);
            while ((v >>= 7) > 0) t[n++] = (byte) (0x80 | (v & 0x7f));
            for (int k = n - 1; k >= 0; k--) o.write(t[k]);
        }
        return tlv(0x06, o.toByteArray());
    }

    private static byte[] utc(long ms) {
        java.text.SimpleDateFormat f = new java.text.SimpleDateFormat("yyMMddHHmmss'Z'", java.util.Locale.US);
        f.setTimeZone(java.util.TimeZone.getTimeZone("UTC"));
        return tlv(0x17, f.format(new Date(ms)).getBytes(StandardCharsets.US_ASCII));
    }
}
