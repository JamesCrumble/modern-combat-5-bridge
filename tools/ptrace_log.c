/* ptrace_log: breakpoint logger for a running process on a ROOTED Android phone (no lldb, no network).
 * Puts `BRK #0` at addresses inside one shared library of the target and, every time one is hit, prints the std::string (libc++ layout) that a given
 * register points to; then the program goes on unchanged. Used to read the messages of the IAP library of the game (libMC5.so +0xc49c78 / +0xce6fc8, documentation/protocol.md).
 *
 * usage (as root, or via `run-as <pkg>` for a debuggable app):  ptrace_log <pid> <lib-name-substring> <offset>:<xreg>[:s|:p] ...  [> file]
 *   offset  = virtual address in the library (hex),  xreg = register number holding a `const std::string &` (x1 -> 1)
 *   suffix  :p additionally prints the register as a C string pointer instead of a std::string (char *), :s (default) = std::string,
 *           :x hex dump of 2048 bytes at the address in the register (tables in memory, e.g. the XP thresholds, documentation/protocol.md)
 * Stops with SIGINT/SIGTERM (breakpoints are removed, threads detached). If the tracer is killed hard the game gets SIGTRAP: stop it with SIGTERM.
 * Build: tools/build_ptrace_log.sh (NDK).  Threads started later are followed (PTRACE_O_TRACECLONE). A hit while another thread single-steps the same
 * address may be missed (the original instruction is put back for one step); good enough for reading logs.
 */
#define _GNU_SOURCE
#include <dirent.h>
#include <elf.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ptrace.h>
#include <sys/types.h>
#include <sys/uio.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#ifndef PTRACE_EVENT_STOP
#define PTRACE_EVENT_STOP 128
#endif

#define MAXBP 16
#define MAXTHR 4096

struct user_regs { uint64_t regs[31]; uint64_t sp, pc, pstate; };

static struct bp {
    uint64_t addr;
    int reg;
    int ptr;
    int hex;
    uint32_t orig;
    int armed;
} bps[MAXBP];
static int nbp;
static int memfd = -1;
static pid_t pid;
static volatile sig_atomic_t quit;
static pid_t threads[MAXTHR];
static int nthreads;
/* thread that single-steps over a restored breakpoint: tid -> breakpoint index */
static int stepping[MAXTHR];

static void on_sig(int s) { (void)s; quit = 1; }

/* Without root (run-as on a debuggable app) SELinux does not let us open /proc/<pid>/mem: then reads go through process_vm_readv and
 * writes through PTRACE_POKEDATA on a thread that is stopped right now (cur_tid). */
static pid_t cur_tid;

static int mem_read(uint64_t addr, void *buf, size_t n)
{
    if (memfd >= 0) {
        ssize_t r = pread(memfd, buf, n, (off_t)addr);
        return r == (ssize_t)n ? 0 : -1;
    }
    struct iovec l = { buf, n }, rm = { (void *)(uintptr_t)addr, n };
    return process_vm_readv(pid, &l, 1, &rm, 1, 0) == (ssize_t)n ? 0 : -1;
}

static int mem_write(uint64_t addr, const void *buf, size_t n)
{
    if (memfd >= 0) {
        ssize_t r = pwrite(memfd, buf, n, (off_t)addr);
        return r == (ssize_t)n ? 0 : -1;
    }
    if (n != 4 || !cur_tid) return -1;
    uint64_t word = addr & ~7ULL;
    errno = 0;
    long v = ptrace(PTRACE_PEEKDATA, cur_tid, (void *)(uintptr_t)word, 0);
    if (errno) return -1;
    memcpy((char *)&v + (addr - word), buf, 4);
    return ptrace(PTRACE_POKEDATA, cur_tid, (void *)(uintptr_t)word, (void *)v) == 0 ? 0 : -1;
}

/* stop the main thread so that mem_write can use it (no-root mode), or do nothing */
static void stop_main(void)
{
    int st;
    if (memfd >= 0) return;
    ptrace(PTRACE_INTERRUPT, pid, 0, 0);
    waitpid(pid, &st, __WALL);
    cur_tid = pid;
}

static void cont_main(void)
{
    if (memfd >= 0) return;
    ptrace(PTRACE_CONT, pid, 0, 0);
    cur_tid = 0;
}

static void arm(int i)
{
    static const uint32_t brk = 0xD4200000;   /* BRK #0 */
    if (mem_write(bps[i].addr, &brk, 4) == 0) bps[i].armed = 1;
}

static void disarm(int i)
{
    mem_write(bps[i].addr, &bps[i].orig, 4);
    bps[i].armed = 0;
}

static int thr_index(pid_t t)
{
    for (int i = 0; i < nthreads; i++) if (threads[i] == t) return i;
    if (nthreads < MAXTHR) { threads[nthreads] = t; stepping[nthreads] = -1; return nthreads++; }
    return -1;
}

static void print_string(uint64_t sp, int as_ptr)
{
    char out[600];
    size_t n = 0;
    if (as_ptr) {
        if (mem_read(sp, out, 1) != 0) { printf("<unreadable %llx>", (unsigned long long)sp); return; }
        for (; n < sizeof out - 1; n++) { if (mem_read(sp + n, &out[n], 1) != 0 || !out[n]) break; }
    } else {
        uint8_t b0;
        uint64_t data, len;
        if (mem_read(sp, &b0, 1) != 0) { printf("<unreadable %llx>", (unsigned long long)sp); return; }
        if (b0 & 1) {
            if (mem_read(sp + 8, &len, 8) != 0 || mem_read(sp + 16, &data, 8) != 0) { printf("<bad long string>"); return; }
        } else { len = b0 >> 1; data = sp + 1; }
        if (len > sizeof out - 1) len = sizeof out - 1;
        if (mem_read(data, out, len) != 0) { printf("<unreadable data %llx>", (unsigned long long)data); return; }
        n = len;
    }
    for (size_t i = 0; i < n; i++) putchar(out[i] >= 32 && out[i] < 127 ? out[i] : (out[i] == '\n' ? '|' : '.'));
}

static uint64_t lib_base(const char *name)
{
    char path[64], line[512];
    snprintf(path, sizeof path, "/proc/%d/maps", pid);
    FILE *f = fopen(path, "r");
    if (!f) return 0;
    uint64_t base = 0;
    while (fgets(line, sizeof line, f)) {
        unsigned long long lo, off;
        if (strstr(line, name) && sscanf(line, "%llx-%*llx %*4s %llx", &lo, &off) == 2 && off == 0) { base = lo; break; }
    }
    fclose(f);
    return base;
}

static void seize_all(void)
{
    char path[64];
    snprintf(path, sizeof path, "/proc/%d/task", pid);
    DIR *d = opendir(path);
    struct dirent *e;
    while (d && (e = readdir(d))) {
        pid_t t = atoi(e->d_name);
        if (t <= 0) continue;
        if (ptrace(PTRACE_SEIZE, t, 0, PTRACE_O_TRACECLONE) == 0) thr_index(t);
    }
    if (d) closedir(d);
}

static void cleanup(void)
{
    stop_main();
    for (int i = 0; i < nbp; i++) if (bps[i].armed) disarm(i);
    for (int i = 0; i < nthreads; i++) {
        kill(threads[i], SIGSTOP);              /* make the detach clean for running threads */
        int st;
        waitpid(threads[i], &st, __WALL | WNOHANG);
        ptrace(PTRACE_DETACH, threads[i], 0, 0);
    }
    kill(pid, SIGCONT);                         /* a SIGSTOP that was not consumed before the detach must not leave the game stopped */
}

int main(int argc, char **argv)
{
    if (argc < 4) { fprintf(stderr, "usage: %s <pid> <lib-substring> <hexoffset>:<xreg>[:p] ...\n", argv[0]); return 2; }
    pid = atoi(argv[1]);
    uint64_t base = lib_base(argv[2]);
    if (!base) { fprintf(stderr, "library %s not found in /proc/%d/maps\n", argv[2], pid); return 1; }
    for (int i = 3; i < argc && nbp < MAXBP; i++) {
        unsigned long long off; int reg = 1; char mode = 's';
        if (sscanf(argv[i], "%llx:%d:%c", &off, &reg, &mode) < 2) { fprintf(stderr, "bad breakpoint %s\n", argv[i]); return 2; }
        bps[nbp].addr = base + off; bps[nbp].reg = reg; bps[nbp].ptr = (mode == 'p'); bps[nbp].hex = (mode == 'x'); nbp++;
    }
    char path[64];
    snprintf(path, sizeof path, "/proc/%d/mem", pid);
    signal(SIGINT, on_sig); signal(SIGTERM, on_sig);
    seize_all();                                /* attach first: without root (run-as on a debuggable app) /proc/<pid>/mem opens only for a tracer */
    memfd = open(path, O_RDWR);
    if (memfd < 0) fprintf(stderr, "ptrace_log: /proc/%d/mem not available (%s), using process_vm_readv + PTRACE_POKEDATA\n", pid, strerror(errno));
    stop_main();
    for (int i = 0; i < nbp; i++) {
        if (mem_read(bps[i].addr, &bps[i].orig, 4) != 0) { fprintf(stderr, "cannot read %llx\n", (unsigned long long)bps[i].addr); cleanup(); return 1; }
        arm(i);
        if (!bps[i].armed) { fprintf(stderr, "cannot write %llx\n", (unsigned long long)bps[i].addr); cont_main(); cleanup(); return 1; }
    }
    cont_main();
    setvbuf(stdout, NULL, _IOLBF, 0);
    fprintf(stderr, "ptrace_log: pid %d, %s base %llx, %d breakpoint(s), %d thread(s)\n", pid, argv[2], (unsigned long long)base, nbp, nthreads);

    while (!quit) {
        int st;
        pid_t t = waitpid(-1, &st, __WALL | WNOHANG);
        if (t < 0) { if (errno == EINTR) continue; break; }
        if (t == 0) { usleep(2000); continue; }
        int ti = thr_index(t);
        cur_tid = t;
        if (WIFEXITED(st) || WIFSIGNALED(st)) { if (t == pid) break; continue; }
        if (!WIFSTOPPED(st)) continue;
        int sig = WSTOPSIG(st), ev = st >> 16, deliver = 0;
        if (ev) {                                   /* ptrace event (clone, stop ...) */
            if (ev == PTRACE_EVENT_CLONE) {
                unsigned long nt = 0;
                ptrace(PTRACE_GETEVENTMSG, t, 0, &nt);
                thr_index((pid_t)nt);
            }
            ptrace(PTRACE_CONT, t, 0, 0);
            continue;
        }
        if (sig == SIGTRAP) {
            struct user_regs r;
            struct iovec iov = { &r, sizeof r };
            if (ptrace(PTRACE_GETREGSET, t, (void *)NT_PRSTATUS, &iov) == 0) {
                int hit = -1;
                for (int i = 0; i < nbp; i++) if (bps[i].addr == r.pc && bps[i].armed) hit = i;
                if (hit >= 0) {
                    struct timespec ts;
                    clock_gettime(CLOCK_REALTIME, &ts);
                    printf("%ld.%03ld %d bp%d ", (long)ts.tv_sec, ts.tv_nsec / 1000000, (int)t, hit);
                    if (bps[hit].hex) {
                        uint8_t buf[2048];
                        if (mem_read(r.regs[bps[hit].reg], buf, sizeof buf) == 0) for (size_t i = 0; i < sizeof buf; i++) printf("%02x", buf[i]);
                        else printf("<unreadable>");
                    } else print_string(r.regs[bps[hit].reg], bps[hit].ptr);
                    putchar('\n');
                    disarm(hit);
                    if (ti >= 0) stepping[ti] = hit;
                    ptrace(PTRACE_SINGLESTEP, t, 0, 0);
                    continue;
                }
                if (ti >= 0 && stepping[ti] >= 0) {  /* the single step over the restored instruction is done */
                    arm(stepping[ti]);
                    stepping[ti] = -1;
                    ptrace(PTRACE_CONT, t, 0, 0);
                    continue;
                }
            }
            ptrace(PTRACE_CONT, t, 0, 0);
            continue;
        }
        deliver = (sig == SIGSTOP || sig == SIGTSTP || sig == SIGTTIN || sig == SIGTTOU) ? 0 : sig;
        ptrace(PTRACE_CONT, t, 0, deliver);
    }
    cleanup();
    return 0;
}
