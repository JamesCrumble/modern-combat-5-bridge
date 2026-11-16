
/* ---- start ---- */
__attribute__((constructor)) static void mc5trace_init(void)
{
    const char *f = getenv("MC5TRACE_FILE");
    if (f && *f) g_log_fd = (int)syscall(SYS_openat, AT_FDCWD, f, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0666);
    g_ready = 1;
    /* no tlog here: liblog connects to logd, which goes through our connect hook and dlsym, and the linker lock is held in constructors */
}
