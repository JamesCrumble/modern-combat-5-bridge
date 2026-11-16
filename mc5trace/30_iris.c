#ifndef MC5_QUIET

/* ---- [IRISCfgProvider] logger of libMC5.so 6.0.12a (arm64) ----
 * 0x1386098 (this, const std::string &msg): prefixes "[IRISCfgProvider] " and calls the sink at this+0x18, which is NULL in release.
 * Its entry is replaced by a jump to iris_log. The code page is copied to anonymous memory, patched and moved over the original with
 * mremap, so the APK file mapping is not written (apps may not use execmod on it). */
#define IRIS_LOG_OFF 0x1386098UL
static const unsigned char IRIS_LOG_ORIG[16] = {0xff, 0x03, 0x01, 0xd1, 0xf3, 0x13, 0x00, 0xf9, 0xfd, 0x7b, 0x03, 0xa9, 0xfd, 0xc3, 0x00, 0x91};

static void iris_log(void *self, const unsigned char *s)
{
    (void)self;
    const char *data; size_t n;
    if (s[0] & 1) { n = *(const size_t *)(s + 8); data = *(const char *const *)(s + 16); }   /* libc++ long string */
    else { n = s[0] >> 1; data = (const char *)s + 1; }                                       /* short string */
    tlog("[IRISCfgProvider] %.*s", (int)(n > 900 ? 900 : n), data);
}

static int patch_jump(uintptr_t at, const unsigned char *orig, void *to)
{
    if (memcmp((void *)at, orig, 16)) return -1;
    long pg = sysconf(_SC_PAGESIZE);
    uintptr_t start = at & ~(uintptr_t)(pg - 1);
    size_t len = ((at + 16 - start) + pg - 1) & ~(size_t)(pg - 1);
    unsigned char *copy = mmap(NULL, len, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANONYMOUS, -1, 0);
    if (copy == MAP_FAILED) return -2;
    memcpy(copy, (void *)start, len);
    uint32_t code[2] = {0x58000050, 0xd61f0200};   /* ldr x16, #8 ; br x16 */
    uint64_t target = (uint64_t)(uintptr_t)to;
    memcpy(copy + (at - start), code, 8);
    memcpy(copy + (at - start) + 8, &target, 8);
    __builtin___clear_cache((char *)copy, (char *)copy + len);
    if (mprotect(copy, len, PROT_READ | PROT_EXEC)) { munmap(copy, len); return -3; }
    if (mremap(copy, len, len, MREMAP_MAYMOVE | MREMAP_FIXED, (void *)start) == MAP_FAILED) { munmap(copy, len); return -4; }
    return 0;
}

static uintptr_t g_mc5_base;
static int find_mc5(struct dl_phdr_info *info, size_t size, void *arg)
{
    (void)size; (void)arg;
    if (info->dlpi_name && strstr(info->dlpi_name, "libMC5.so")) { g_mc5_base = info->dlpi_addr; return 1; }
    return 0;
}

/* Installed lazily, once, from the first network/file hook that runs after libMC5.so is mapped (no helper thread: a thread started
 * from the constructor hung every process that had the library preloaded). */
static void try_iris_hook(void)
{
    static int done;
    if (done || t_busy) return;
    t_busy++;
    dl_iterate_phdr(find_mc5, NULL);
    if (g_mc5_base) {
        done = 1;
        int r = patch_jump(g_mc5_base + IRIS_LOG_OFF, IRIS_LOG_ORIG, (void *)iris_log);
        t_busy--;
        tlog("libMC5.so at 0x%lx, IRIS logger hook %s (%d)", (unsigned long)g_mc5_base, r ? "FAILED" : "on", r);
        return;
    }
    t_busy--;
}
#else
static void try_iris_hook(void) {}
#endif /* MC5_QUIET */
