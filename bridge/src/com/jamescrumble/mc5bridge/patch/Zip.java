package com.jamescrumble.mc5bridge.patch;

import java.io.Closeable;
import java.io.File;
import java.io.IOException;
import java.io.OutputStream;
import java.io.RandomAccessFile;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.zip.CRC32;
import java.util.zip.Deflater;

/**
 * Minimal zip reader/writer for building the combined APK (documentation/architecture.md): entries are copied raw (no recompression of the 160 MB),
 * STORED entries are aligned the way zipalign does it (resources.arsc and the libraries must be stored and aligned for Android 11+).
 * No ZIP64 (an APK stays below 4 GB / 65535 entries).
 */
public final class Zip {
    private Zip() {}

    public static final class Entry {
        public String name;
        public int method, flags, time, date;
        public long crc, csize, size, localOffset;
        public byte[] extra = new byte[0];
        Reader owner;
        public boolean stored() { return method == 0; }
    }

    /** A zip file read through its central directory. */
    public static final class Reader implements Closeable {
        private final RandomAccessFile f;
        public final Map<String, Entry> entries = new LinkedHashMap<>();

        public Reader(File file) throws IOException {
            f = new RandomAccessFile(file, "r");
            long len = f.length();
            int max = (int) Math.min(len, 65557);
            byte[] tail = new byte[max];
            f.seek(len - max);
            f.readFully(tail);
            int eocd = -1;
            for (int i = max - 22; i >= 0; i--) if (u32(tail, i) == 0x06054b50L) { eocd = i; break; }
            if (eocd < 0) throw new IOException("not a zip: " + file);
            int count = u16(tail, eocd + 10);
            long cdSize = u32(tail, eocd + 12), cdOff = u32(tail, eocd + 16);
            byte[] cd = new byte[(int) cdSize];
            f.seek(cdOff);
            f.readFully(cd);
            int p = 0;
            for (int i = 0; i < count; i++) {
                if (u32(cd, p) != 0x02014b50L) throw new IOException("bad central directory");
                Entry e = new Entry();
                e.owner = this;
                e.flags = u16(cd, p + 8);
                e.method = u16(cd, p + 10);
                e.time = u16(cd, p + 12);
                e.date = u16(cd, p + 14);
                e.crc = u32(cd, p + 16);
                e.csize = u32(cd, p + 20);
                e.size = u32(cd, p + 24);
                int nl = u16(cd, p + 28), xl = u16(cd, p + 30), cl = u16(cd, p + 32);
                e.localOffset = u32(cd, p + 42);
                e.name = new String(cd, p + 46, nl, StandardCharsets.UTF_8);
                entries.put(e.name, e);
                p += 46 + nl + xl + cl;
            }
        }

        /** Raw (compressed) bytes of an entry. */
        void copyRaw(Entry e, OutputStream out) throws IOException {
            byte[] h = new byte[30];
            f.seek(e.localOffset);
            f.readFully(h);
            long dataOff = e.localOffset + 30 + u16(h, 26) + u16(h, 28);
            f.seek(dataOff);
            byte[] buf = new byte[1 << 16];
            long left = e.csize;
            while (left > 0) {
                int n = f.read(buf, 0, (int) Math.min(buf.length, left));
                if (n < 0) throw new IOException("unexpected end of zip");
                out.write(buf, 0, n);
                left -= n;
            }
        }

        /** Uncompressed bytes of an entry (small entries only: manifest, dex that is patched). */
        public byte[] read(String name) throws IOException {
            Entry e = entries.get(name);
            if (e == null) throw new IOException("no entry " + name);
            java.io.ByteArrayOutputStream raw = new java.io.ByteArrayOutputStream((int) e.csize);
            copyRaw(e, raw);
            if (e.method == 0) return raw.toByteArray();
            java.util.zip.Inflater inf = new java.util.zip.Inflater(true);
            inf.setInput(raw.toByteArray());
            byte[] out = new byte[(int) e.size];
            try {
                int n = 0;
                while (n < out.length && !inf.finished()) {
                    int r = inf.inflate(out, n, out.length - n);
                    if (r == 0 && (inf.needsInput() || inf.needsDictionary())) break;
                    n += r;
                }
                if (n != out.length) throw new IOException("short inflate of " + name);
            } catch (java.util.zip.DataFormatException ex) {
                throw new IOException(ex);
            } finally {
                inf.end();
            }
            return out;
        }

        @Override public void close() throws IOException { f.close(); }
    }

    /** A zip writer: entries copied from a {@link Reader} or added from memory / files. */
    public static final class Writer implements Closeable {
        private final OutputStream out;
        private long pos;
        private final List<Entry> done = new ArrayList<>();

        public Writer(OutputStream out) { this.out = out; }

        private void put(byte[] b, int off, int len) throws IOException { out.write(b, off, len); pos += len; }
        private void put(byte[] b) throws IOException { put(b, 0, b.length); }

        private void header(Entry e, String name, boolean stored, int align) throws IOException {
            byte[] nb = name.getBytes(StandardCharsets.UTF_8);
            int pad = 0;
            if (stored && align > 1) {
                long dataStart = pos + 30 + nb.length;
                pad = (int) ((align - (dataStart % align)) % align);
            }
            byte[] extra = new byte[pad];
            byte[] h = new byte[30];
            w32(h, 0, 0x04034b50L);
            w16(h, 4, 20);
            w16(h, 6, e.flags & 0x0800);
            w16(h, 8, e.method);
            w16(h, 10, e.time);
            w16(h, 12, e.date);
            w32(h, 14, e.crc);
            w32(h, 18, e.csize);
            w32(h, 22, e.size);
            w16(h, 26, nb.length);
            w16(h, 28, extra.length);
            e.localOffset = pos;
            e.name = name;
            e.extra = extra;
            e.flags &= 0x0800;
            put(h);
            put(nb);
            put(extra);
        }

        /** Copy an entry as it is under a new name (STORED entries are aligned to `align`, 4 for everything, 4096 for libraries). */
        public void copy(Entry src, String name, int align) throws IOException {
            Entry e = new Entry();
            e.method = src.method; e.flags = src.flags; e.time = src.time; e.date = src.date;
            e.crc = src.crc; e.csize = src.csize; e.size = src.size;
            header(e, name, src.stored(), align);
            src.owner.copyRaw(src, new OutputStream() {
                @Override public void write(int b) throws IOException { out.write(b); pos++; }
                @Override public void write(byte[] b, int o, int l) throws IOException { out.write(b, o, l); pos += l; }
            });
            done.add(e);
        }

        /** Add bytes: STORED (aligned) or DEFLATED. */
        public void add(String name, byte[] data, boolean store, int align) throws IOException {
            Entry e = new Entry();
            CRC32 crc = new CRC32();
            crc.update(data);
            e.crc = crc.getValue();
            e.size = data.length;
            e.time = 0; e.date = 0x21;      // 1980-01-01, as the Play APK
            byte[] body = data;
            if (store) {
                e.method = 0;
            } else {
                Deflater d = new Deflater(9, true);
                d.setInput(data);
                d.finish();
                java.io.ByteArrayOutputStream bo = new java.io.ByteArrayOutputStream(data.length / 2 + 64);
                byte[] buf = new byte[1 << 16];
                while (!d.finished()) bo.write(buf, 0, d.deflate(buf));
                d.end();
                body = bo.toByteArray();
                e.method = 8;
            }
            e.csize = body.length;
            header(e, name, store, align);
            put(body);
            done.add(e);
        }

        /** Add a file (STORED: streamed, needs the CRC first). */
        public void addFile(String name, File file, boolean store, int align) throws IOException {
            if (!store) { add(name, java.nio.file.Files.readAllBytes(file.toPath()), false, align); return; }
            Entry e = new Entry();
            CRC32 crc = new CRC32();
            byte[] buf = new byte[1 << 16];
            try (java.io.FileInputStream in = new java.io.FileInputStream(file)) {
                int n;
                while ((n = in.read(buf)) > 0) crc.update(buf, 0, n);
            }
            e.crc = crc.getValue(); e.size = e.csize = file.length(); e.method = 0; e.time = 0; e.date = 0x21;
            header(e, name, true, align);
            try (java.io.FileInputStream in = new java.io.FileInputStream(file)) {
                int n;
                while ((n = in.read(buf)) > 0) put(buf, 0, n);
            }
            done.add(e);
        }

        public boolean has(String name) {
            for (Entry e : done) if (e.name.equals(name)) return true;
            return false;
        }

        @Override public void close() throws IOException {
            long cdStart = pos;
            for (Entry e : done) {
                byte[] nb = e.name.getBytes(StandardCharsets.UTF_8);
                byte[] c = new byte[46];
                w32(c, 0, 0x02014b50L);
                w16(c, 4, 20); w16(c, 6, 20);
                w16(c, 8, e.flags & 0x0800);
                w16(c, 10, e.method); w16(c, 12, e.time); w16(c, 14, e.date);
                w32(c, 16, e.crc); w32(c, 20, e.csize); w32(c, 24, e.size);
                w16(c, 28, nb.length);
                w32(c, 42, e.localOffset);
                put(c);
                put(nb);
            }
            long cdSize = pos - cdStart;
            byte[] t = new byte[22];
            w32(t, 0, 0x06054b50L);
            w16(t, 8, done.size()); w16(t, 10, done.size());
            w32(t, 12, cdSize); w32(t, 16, cdStart);
            put(t);
            out.close();
        }
    }

    static int u16(byte[] b, int o) { return (b[o] & 0xff) | (b[o + 1] & 0xff) << 8; }
    static long u32(byte[] b, int o) { return u16(b, o) | (long) u16(b, o + 2) << 16; }
    static void w16(byte[] b, int o, long v) { b[o] = (byte) v; b[o + 1] = (byte) (v >> 8); }
    static void w32(byte[] b, int o, long v) { w16(b, o, v); w16(b, o + 2, v >> 16); }
}
