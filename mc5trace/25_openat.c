#ifndef MC5_QUIET

/* bionic's fortified and *at variants (Java's libcore and FORTIFY builds use them instead of open) */
int openat(int dirfd, const char *path, int flags, ...)
{
    REAL(openat);
    mode_t mode = 0;
    if (flags & (O_CREAT | O_TMPFILE)) {
        va_list ap;
        va_start(ap, flags);
        mode = va_arg(ap, int);
        va_end(ap);
    }
    int fd = real_openat(dirfd, path, flags, mode);
    if (want_path(path, fd < 0)) {
        int e = errno;
        tlog("openat %s 0x%x -> %d %s", path, flags, fd, fd < 0 ? strerror(e) : "");
        errno = e;
    }
    return fd;
}

int __open_2(const char *path, int flags);
int __open_2(const char *path, int flags)
{
    REAL(__open_2);
    int fd = real___open_2(path, flags);
    if (want_path(path, fd < 0)) {
        int e = errno;
        tlog("open2 %s 0x%x -> %d %s", path, flags, fd, fd < 0 ? strerror(e) : "");
        errno = e;
    }
    return fd;
}

int __openat_2(int dirfd, const char *path, int flags);
int __openat_2(int dirfd, const char *path, int flags)
{
    REAL(__openat_2);
    int fd = real___openat_2(dirfd, path, flags);
    if (want_path(path, fd < 0)) {
        int e = errno;
        tlog("openat2 %s 0x%x -> %d %s", path, flags, fd, fd < 0 ? strerror(e) : "");
        errno = e;
    }
    return fd;
}
#endif /* MC5_QUIET */
