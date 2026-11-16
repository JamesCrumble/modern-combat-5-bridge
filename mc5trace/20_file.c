#ifndef MC5_QUIET

/* ---- files: the game's own paths, and every failed open outside /proc and /sys ---- */
static int want_path(const char *p, int failed)
{
    if (t_busy || !p) return 0;
    if (!strncmp(p, "/proc/", 6) || !strncmp(p, "/sys/", 5) || !strncmp(p, "/dev/", 5)) return 0;
    if (strstr(p, "GloftM5HM")) {
        size_t n = strlen(p);
        /* successful reads of the big archives are not interesting, the lookups are */
        if (!failed && n > 5 && (!strcmp(p + n - 5, ".gla2") || strstr(p, "/bald/"))) return 0;
        return 1;
    }
    return failed;
}

FILE *fopen(const char *path, const char *mode)
{
    REAL(fopen);
    FILE *f = real_fopen(path, mode);
    if (want_path(path, f == NULL)) {
        int e = errno;
        tlog("fopen %s %s -> %s", path, mode, f ? "ok" : strerror(e));
        errno = e;
    }
    return f;
}

int open(const char *path, int flags, ...)
{
    REAL(open);
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    int fd = real_open(path, flags, mode);
    if (want_path(path, fd < 0)) {
        int e = errno;
        tlog("open %s 0x%x -> %d %s", path, flags, fd, fd < 0 ? strerror(e) : "");
        errno = e;
    }
    return fd;
}

int stat(const char *path, struct stat *st)
{
    REAL(stat);
    int r = real_stat(path, st);
    if (want_path(path, r != 0)) {
        int e = errno;
        tlog("stat %s -> %s", path, r ? strerror(e) : "ok");
        errno = e;
    }
    return r;
}

int access(const char *path, int amode)
{
    REAL(access);
    int r = real_access(path, amode);
    if (want_path(path, r != 0)) {
        int e = errno;
        tlog("access %s %d -> %s", path, amode, r ? strerror(e) : "ok");
        errno = e;
    }
    return r;
}
#endif /* MC5_QUIET */
