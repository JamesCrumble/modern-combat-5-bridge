/* Gameloft .gla2 / .dcmp reader.
 *
 * Layout: 16-byte header (magic d0 ee a8 9a), file data, then an index of big-endian records.
 *   A (Android 1.2.0, 24 bytes): hash32, offset, size, comp_size (0 = stored raw), unk (always 0), flags32
 *   B (iOS 6.0.21, 22 bytes):    hash64, offset, size, comp_size, flags16
 * flags: 0 raw, 1 encrypted, 8 LZ4 block. The file count is not in the header: the index start is the point where
 * 16 + sum(stored sizes of the records after it) == start and the records tile [16, start) without gaps.
 *
 *   gla check   <archive>...            index + LZ4 integrity of every archive
 *   gla list    <archive>               one line per file
 *   gla sums    <archive>...            archive, hash, size, crc32 of the unpacked data, flags (one line per file)
 *   gla extract <archive> <outdir>      write files (names from <archive>_def when present, else <hash>.bin)
 *
 * Flag 1 (encrypted) entries are extracted as-is, the cipher is not known yet.
 *
 * Build: cc -O2 -o work/gla tools/gla.c
 */
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <unistd.h>

#define RECA 24
#define RECB 22
#define HDR 16

typedef struct {
    uint64_t hash;
    uint32_t off, size, comp, unk, flags;
    const char *name; /* from _def, may be NULL */
} Rec;

typedef struct {
    const uint8_t *buf;
    size_t len;
    size_t idx;  /* index start */
    Rec *r;
    size_t n;
    int fmt;  /* 'A' or 'B' */
} Gla;

static uint32_t be32(const uint8_t *p) { return (uint32_t)p[0] << 24 | p[1] << 16 | p[2] << 8 | p[3]; }

static int open_map(const char *path, const uint8_t **buf, size_t *len) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    struct stat st;
    if (fstat(fd, &st) < 0 || st.st_size == 0) { close(fd); return -1; }
    void *m = mmap(NULL, st.st_size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (m == MAP_FAILED) return -1;
    *buf = m;
    *len = st.st_size;
    return 0;
}

static size_t stored(const Rec *r) { return r->comp ? r->comp : r->size; }

static int by_off(const void *a, const void *b) {
    uint32_t x = ((const Rec *)a)->off, y = ((const Rec *)b)->off;
    return x < y ? -1 : x > y;
}

static uint64_t be64(const uint8_t *p) { return (uint64_t)be32(p) << 32 | be32(p + 4); }

static void parse_rec(Rec *r, const uint8_t *p, int fmt) {
    if (fmt == 'A') {
        r->hash = be32(p); r->off = be32(p + 4); r->size = be32(p + 8);
        r->comp = be32(p + 12); r->unk = be32(p + 16); r->flags = be32(p + 20);
    } else {
        r->hash = be64(p); r->off = be32(p + 8); r->size = be32(p + 12);
        r->comp = be32(p + 16); r->unk = 0; r->flags = p[20] << 8 | p[21];
    }
}

/* Walks back from EOF for one record format; returns the record count of the largest consistent tiling, 0 if none. */
static size_t find_index(Gla *g, int fmt) {
    size_t rec = fmt == 'A' ? RECA : RECB, pos = g->len, k = 0, best = 0;
    uint64_t sum = 0;
    while (pos - rec >= HDR) {
        Rec r;
        parse_rec(&r, g->buf + pos - rec, fmt);
        uint64_t end = (uint64_t)r.off + (r.comp ? r.comp : r.size);
        if ((fmt == 'A' && r.unk != 0) || r.off < HDR || end > pos - rec) break;
        pos -= rec;
        k++;
        sum += r.comp ? r.comp : r.size;
        if (HDR + sum == pos) best = k;
    }
    return best;
}

/* 0 on success; fills g->r sorted by offset. */
static int gla_open(Gla *g, const char *path) {
    memset(g, 0, sizeof *g);
    if (open_map(path, &g->buf, &g->len) < 0) return -1;
    if (g->len < HDR + RECB || memcmp(g->buf, "\xd0\xee\xa8\x9a", 4)) return -2;
    int fmts[2] = {'A', 'B'};
    for (int f = 0; f < 2; f++) {
        int fmt = fmts[f];
        size_t n = find_index(g, fmt), rec = fmt == 'A' ? RECA : RECB;
        if (!n) continue;
        Rec *r = calloc(n, sizeof(Rec));
        size_t start = g->len - n * rec;
        for (size_t i = 0; i < n; i++) parse_rec(&r[i], g->buf + start + i * rec, fmt);
        qsort(r, n, sizeof(Rec), by_off);
        uint64_t cur = HDR;
        size_t i;
        for (i = 0; i < n; i++) {
            if (r[i].off != cur) break;
            cur += stored(&r[i]);
        }
        if (i == n && cur == start) {
            g->r = r; g->n = n; g->idx = start; g->fmt = fmt;
            return 0;
        }
        free(r);
    }
    return -3;
}

/* Plain LZ4 block. Returns 0 when exactly out_size bytes were produced. */
static int lz4_block(const uint8_t *src, size_t n, uint8_t *out, size_t out_size) {
    size_t i = 0, o = 0;
    while (i < n) {
        unsigned tok = src[i++];
        size_t lit = tok >> 4;
        if (lit == 15) {
            unsigned b;
            do { if (i >= n) return -1; b = src[i++]; lit += b; } while (b == 255);
        }
        if (i + lit > n || o + lit > out_size) return -1;
        memcpy(out + o, src + i, lit);
        i += lit; o += lit;
        if (i >= n) break;
        if (i + 2 > n) return -1;
        size_t off = src[i] | src[i + 1] << 8;
        i += 2;
        size_t ml = tok & 15;
        if (ml == 15) {
            unsigned b;
            do { if (i >= n) return -1; b = src[i++]; ml += b; } while (b == 255);
        }
        ml += 4;
        if (off == 0 || off > o || o + ml > out_size) return -1;
        for (size_t k = 0; k < ml; k++, o++) out[o] = out[o - off];
    }
    return o == out_size ? 0 : -1;
}

/* _def blocks: "File N", full Windows path, lower-case name, "File Size = ", "Compressed Size = ", "File offset = X", "Hash = H".
 * The path (below "data\\" when present) becomes the output name; the buffer is kept alive for the process lifetime. */
static void load_def(Gla *g, const char *path) {
    const uint8_t *b;
    size_t len;
    if (open_map(path, &b, &len) < 0) return;
    char *txt = strndup((const char *)b, len), *save = NULL, *fpath = NULL;
    munmap((void *)b, len);
    int expect_path = 0;
    for (char *line = strtok_r(txt, "\r\n", &save); line; line = strtok_r(NULL, "\r\n", &save)) {
        if (!strncmp(line, "File ", 5) && line[5] >= '0' && line[5] <= '9') { expect_path = 1; continue; }
        if (expect_path) {
            char *d = strstr(line, "\\data\\");
            fpath = d ? d + 6 : line;
            for (char *c = fpath; *c; c++) if (*c == '\\') *c = '/';
            expect_path = 0;
        } else if (!strncmp(line, "File offset = ", 14) && fpath) {
            unsigned long long off = strtoull(line + 14, NULL, 10);
            for (size_t i = 0; i < g->n; i++)
                if (g->r[i].off == off) { g->r[i].name = fpath; break; }
        }
    }
}

static int mkdirs(char *path) {
    for (char *p = path + 1; *p; p++) {
        if (*p != '/') continue;
        *p = 0;
        mkdir(path, 0777);
        *p = '/';
    }
    return 0;
}

static int cmd_check(const char *path) {
    Gla g;
    int rc = gla_open(&g, path);
    if (rc) { printf("%s: not a gla archive (%d)\n", path, rc); return 1; }
    size_t lz = 0, enc = 0, raw = 0, bad = 0;
    for (size_t i = 0; i < g.n; i++) {
        Rec *r = &g.r[i];
        if (r->flags == 1) { enc++; continue; }
        if (r->flags == 8 && r->comp) {
            uint8_t *tmp = malloc(r->size ? r->size : 1);
            if (lz4_block(g.buf + r->off, r->comp, tmp, r->size)) { bad++; fprintf(stderr, "%s: bad LZ4 %08" PRIx64 "\n", path, r->hash); }
            else lz++;
            free(tmp);
        } else raw++;
    }
    printf("%s: fmt=%c n=%zu index@%zx lz4=%zu raw=%zu enc=%zu bad=%zu\n", path, g.fmt, g.n, g.idx, lz, raw, enc, bad);
    return bad != 0;
}

static uint32_t crc_tab[256];

static void crc_init(void) {
    for (uint32_t i = 0; i < 256; i++) {
        uint32_t c = i;
        for (int k = 0; k < 8; k++) c = c & 1 ? 0xedb88320u ^ (c >> 1) : c >> 1;
        crc_tab[i] = c;
    }
}

static uint32_t crc32_of(const uint8_t *p, size_t n) {
    uint32_t c = 0xffffffffu;
    while (n--) c = crc_tab[(c ^ *p++) & 255] ^ (c >> 8);
    return ~c;
}

static const char *base_name(const char *path) {
    const char *s = strrchr(path, '/');
    return s ? s + 1 : path;
}

static int cmd_sums(const char *path) {
    Gla g;
    int rc = gla_open(&g, path);
    if (rc) { fprintf(stderr, "%s: not a gla archive (%d)\n", path, rc); return 1; }
    for (size_t i = 0; i < g.n; i++) {
        Rec *r = &g.r[i];
        uint32_t crc;
        if (r->flags == 8 && r->comp) {
            uint8_t *tmp = malloc(r->size ? r->size : 1);
            if (lz4_block(g.buf + r->off, r->comp, tmp, r->size)) { free(tmp); fprintf(stderr, "%s: bad LZ4\n", path); continue; }
            crc = crc32_of(tmp, r->size);
            free(tmp);
        } else crc = crc32_of(g.buf + r->off, r->size);
        printf("%s %016" PRIx64 " %u %08x %u\n", base_name(path), r->hash, r->size, crc, r->flags);
    }
    return 0;
}

static int cmd_list(const char *path) {
    Gla g;
    int rc = gla_open(&g, path);
    if (rc) { fprintf(stderr, "%s: not a gla archive (%d)\n", path, rc); return 1; }
    for (size_t i = 0; i < g.n; i++) {
        Rec *r = &g.r[i];
        printf(g.fmt == 'A' ? "%08" PRIx64 " %10u %10u flags=%u off=%u\n" : "%016" PRIx64 " %10u %10u flags=%u off=%u\n", r->hash, r->size, r->comp, r->flags, r->off);
    }
    return 0;
}

static int cmd_extract(const char *path, const char *outdir) {
    Gla g;
    int rc = gla_open(&g, path);
    if (rc) { fprintf(stderr, "%s: not a gla archive (%d)\n", path, rc); return 1; }
    char *def = NULL;
    if (asprintf(&def, "%s_def", path) > 0) load_def(&g, def);
    mkdir(outdir, 0777);
    for (size_t i = 0; i < g.n; i++) {
        Rec *r = &g.r[i];
        char fn[4096];
        if (r->name && !strstr(r->name, "..")) snprintf(fn, sizeof fn, "%s/%s", outdir, r->name);
        else snprintf(fn, sizeof fn, "%s/%08" PRIx64 ".bin", outdir, r->hash);
        uint8_t *out = NULL;
        const uint8_t *data = g.buf + r->off;
        size_t n = r->size;
        if (r->flags == 8 && r->comp) {
            out = malloc(r->size ? r->size : 1);
            if (lz4_block(data, r->comp, out, r->size)) { fprintf(stderr, "bad LZ4 %08" PRIx64 "\n", r->hash); free(out); continue; }
            data = out;
        }
        mkdirs(fn);
        FILE *f = fopen(fn, "wb");
        if (!f) { fprintf(stderr, "%s: %s\n", fn, strerror(errno)); free(out); continue; }
        fwrite(data, 1, n, f);
        fclose(f);
        free(out);
    }
    return 0;
}

int main(int argc, char **argv) {
    if (argc >= 3 && !strcmp(argv[1], "check")) {
        int bad = 0;
        for (int i = 2; i < argc; i++) bad |= cmd_check(argv[i]);
        return bad;
    }
    if (argc >= 3 && !strcmp(argv[1], "sums")) {
        crc_init();
        int bad = 0;
        for (int i = 2; i < argc; i++) bad |= cmd_sums(argv[i]);
        return bad;
    }
    if (argc == 3 && !strcmp(argv[1], "list")) return cmd_list(argv[2]);
    if (argc == 4 && !strcmp(argv[1], "extract")) return cmd_extract(argv[2], argv[3]);
    fprintf(stderr, "usage: gla check <archive>... | sums <archive>... | list <archive> | extract <archive> <outdir>\n");
    return 2;
}
