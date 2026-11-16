/* mc5trace: LD_PRELOAD library for the MC5 client (loaded by lib/arm64-v8a/wrap.sh in the debuggable build, no root).
 * Logs to logcat (tag mc5trace) and to $MC5TRACE_FILE: name lookups, connects, the start of plain HTTP traffic,
 * files the client fails to open, and the Gaia config logger [IRISCfgProvider] (which has no sink in release).
 * Build: tools/build_mc5trace.sh (NDK in ./ndk). Pieces are in mc5trace/ and concatenated into work/mc5trace/mc5trace.c. */
#define _GNU_SOURCE
#include <android/log.h>
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <link.h>
#include <netdb.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

static int g_log_fd = -1;
static void try_iris_hook(void);
static void udp_prepare(int fd, const struct sockaddr *sa);
static int sock_is_dgram(int fd);
static int tcp_tunnel(int fd, const char *host, int port);
static void dgram_log(const char *what, int fd, const struct sockaddr *sa, size_t len);
static int env_port(const char *name, int def);
static int redirect_on(void);
static volatile int t_busy;   /* plain global: __thread (emutls on this Android 9 target) deadlocks when the library is preloaded */   /* set while we log, so our own calls are not traced */

static volatile int g_ready;   /* set at the end of the constructor: libc of Android 16 calls access() inside malloc init, before this library is initialised;
                                  logging there needs malloc -> recursion -> SIGSEGV in app_process64 (OnePlus, 25.10) */

static void tlog(const char *fmt, ...)
{
    char buf[1024];
#ifdef MC5_QUIET
    (void)fmt;      /* the product build (libmc5net.so) logs nothing */
    return;
#endif
    if (!g_ready) return;
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(buf, sizeof buf, fmt, ap);
    va_end(ap);
    if (n < 0) return;
    if (n >= (int)sizeof buf) n = sizeof buf - 1;
    t_busy++;
    __android_log_write(ANDROID_LOG_INFO, "mc5trace", buf);
    if (g_log_fd >= 0) {
        struct timespec ts;
        char line[1100];
        clock_gettime(CLOCK_REALTIME, &ts);
        int m = snprintf(line, sizeof line, "%ld.%03ld %d %s\n", (long)ts.tv_sec, ts.tv_nsec / 1000000, (int)syscall(SYS_gettid), buf);
        if (m > 0) syscall(SYS_write, g_log_fd, line, m < (int)sizeof line ? m : (int)sizeof line - 1);
    }
    t_busy--;
}

/* printable copy of the first bytes of a buffer (HTTP request/response lines) */
static void preview(char *out, size_t outsz, const void *data, size_t len)
{
    const unsigned char *p = data;
    size_t j = 0;
    for (size_t i = 0; i < len && j + 4 < outsz; i++) {
        unsigned char c = p[i];
        if (c == '\r') continue;
        if (c == '\n') { out[j++] = '|'; continue; }
        out[j++] = (c >= 32 && c < 127) ? c : '.';
    }
    out[j] = 0;
}

#define REAL(name) static __typeof__(name) *real_##name; if (!real_##name) real_##name = dlsym(RTLD_NEXT, #name)
