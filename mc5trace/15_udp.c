/* ---- UDP tunnel (MC5_REDIRECT=1) ----
 * adb reverse carries TCP only, the phone has no network. When the client sends UDP to 127.0.0.1:P (the game server address handed
 * out by the PC server is loopback), a helper thread inside this process binds 127.0.0.1:P itself, so the client's datagrams land
 * there and replies come back from the same address. The helper carries them to the PC over TCP 127.0.0.1:MC5_UDP_TUN (33699,
 * adb reverse): hello "MC5U" + u16 port, then frames u16 length + datagram in both directions. */
#include <poll.h>

static uint64_t udp_ports[64];   /* (ip << 16) | port of the helpers */
static int udp_nports;
static pthread_mutex_t udp_mx = PTHREAD_MUTEX_INITIALIZER;

struct udp_job { int us; int port; uint32_t ip; char name[128]; };

static int read_full(int fd, unsigned char *p, size_t n)
{
    REAL(recv);
    while (n) {
        ssize_t r = real_recv(fd, p, n, 0);
        if (r <= 0) return -1;
        p += r; n -= (size_t)r;
    }
    return 0;
}

static int write_full(int fd, const unsigned char *p, size_t n)
{
    REAL(send);
    while (n) {
        ssize_t r = real_send(fd, p, n, MSG_NOSIGNAL);
        if (r <= 0) return -1;
        p += r; n -= (size_t)r;
    }
    return 0;
}

static void *udp_helper(void *arg)
{
    struct udp_job job = *(struct udp_job *)arg;
    free(arg);
    REAL(connect);
    REAL(sendto);
    REAL(recvfrom);
    int ts = socket(AF_INET, SOCK_STREAM | SOCK_CLOEXEC, 0);
    struct sockaddr_in pc = { .sin_family = AF_INET, .sin_port = htons(env_port("MC5_UDP_TUN", 33699)),
                              .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
    if (ts < 0 || real_connect(ts, (const void *)&pc, sizeof pc) != 0) {
        tlog("udp %d: tunnel connect failed: %s", job.port, strerror(errno));
        goto out;
    }
    /* hello: "MC5U", u16 port, u8 name length, name (empty: the PC uses the last game server host) */
    unsigned char hello[6 + 1 + 128];
    size_t nl = strlen(job.name);
    memcpy(hello, "MC5U", 4); hello[4] = (unsigned char)(job.port >> 8); hello[5] = (unsigned char)job.port;
    hello[6] = (unsigned char)nl; memcpy(hello + 7, job.name, nl);
    if (write_full(ts, hello, 7 + nl)) goto out;
    tlog("udp %d: tunnel up", job.port);
    static unsigned char buf[65536 + 2];
    struct sockaddr_storage peer;
    socklen_t plen = 0;
    long up = 0, down = 0;
    for (;;) {
        struct pollfd pf[2] = { { job.us, POLLIN, 0 }, { ts, POLLIN, 0 } };
        if (poll(pf, 2, -1) < 0) { if (errno == EINTR) continue; break; }
        if (pf[0].revents & POLLIN) {
            socklen_t l = sizeof peer;
            ssize_t n = real_recvfrom(job.us, buf + 2, 65536, 0, (struct sockaddr *)&peer, &l);
            if (n < 0) break;
            plen = l;
            buf[0] = (unsigned char)(n >> 8); buf[1] = (unsigned char)n;
            if (write_full(ts, buf, (size_t)n + 2)) break;
            if (++up <= 3) tlog("udp %d: c2s %zd bytes", job.port, n);
        }
        if (pf[1].revents & (POLLIN | POLLHUP | POLLERR)) {
            unsigned char h[2];
            if (read_full(ts, h, 2)) break;
            size_t n = ((size_t)h[0] << 8) | h[1];
            if (read_full(ts, buf, n)) break;
            if (plen) real_sendto(job.us, buf, n, 0, (const struct sockaddr *)&peer, plen);
            if (++down <= 3) tlog("udp %d: s2c %zu bytes", job.port, n);
        }
    }
    tlog("udp %d: tunnel closed (%ld up, %ld down)", job.port, up, down);
out:
    if (ts >= 0) close(ts);
    close(job.us);
    pthread_mutex_lock(&udp_mx);
    uint64_t key = ((uint64_t)job.ip << 16) | (uint64_t)job.port;
    for (int i = 0; i < udp_nports; i++) if (udp_ports[i] == key) udp_ports[i] = udp_ports[--udp_nports];
    pthread_mutex_unlock(&udp_mx);
    return NULL;
}

/* TCP connect to a Gameloft host on a port the PC server does not serve: connect fd (blocking, local) to 127.0.0.1:MC5_TCP_TUN (33698,
 * adb reverse) and send "MC5T", u8 name length, name, u16 port. The PC relays to the real host through the proxy. For a non-blocking
 * socket the connect completes at once (loopback), which is a valid result of connect(). */
static int tcp_tunnel(int fd, const char *host, int port)
{
    REAL(connect);
    int fl = fcntl(fd, F_GETFL);
    if (fl >= 0) fcntl(fd, F_SETFL, fl & ~O_NONBLOCK);
    int r;
    struct sockaddr_storage ss;
    socklen_t sl = sizeof ss;
    int fam = AF_INET;
    if (getsockname(fd, (struct sockaddr *)&ss, &sl) == 0 && ss.ss_family == AF_INET6) fam = AF_INET6;
    if (fam == AF_INET6) {
        struct sockaddr_in6 a = { .sin6_family = AF_INET6, .sin6_port = htons(env_port("MC5_TCP_TUN", 33698)) };
        inet_pton(AF_INET6, "::ffff:127.0.0.1", &a.sin6_addr);
        r = real_connect(fd, (const void *)&a, sizeof a);
    } else {
        struct sockaddr_in a = { .sin_family = AF_INET, .sin_port = htons(env_port("MC5_TCP_TUN", 33698)), .sin_addr.s_addr = htonl(INADDR_LOOPBACK) };
        r = real_connect(fd, (const void *)&a, sizeof a);
    }
    if (r == 0) {
        unsigned char h[4 + 1 + 255 + 2];
        size_t nl = strlen(host);
        if (nl > 255) nl = 255;
        memcpy(h, "MC5T", 4); h[4] = (unsigned char)nl; memcpy(h + 5, host, nl);
        h[5 + nl] = (unsigned char)(port >> 8); h[6 + nl] = (unsigned char)port;
        if (write_full(fd, h, 7 + nl)) r = -1;
    }
    int e = errno;
    if (fl >= 0) fcntl(fd, F_SETFL, fl);
    errno = e;
    return r;
}

static int sock_is_dgram(int fd)
{
    int t = 0;
    socklen_t l = sizeof t;
    return getsockopt(fd, SOL_SOCKET, SO_TYPE, &t, &l) == 0 && t == SOCK_DGRAM;
}

/* called before a UDP connect/sendto: dest must already be loopback (connect redirects non-loopback) */
static void udp_prepare(int fd, const struct sockaddr *sa)
{
    if (!redirect_on() || !sa || t_busy) return;
    int port = 0;
    uint32_t ip = sa_ip4(sa);
    if (sa->sa_family == AF_INET) port = ntohs(((const struct sockaddr_in *)sa)->sin_port);
    else if (sa->sa_family == AF_INET6) {
        const struct sockaddr_in6 *s = (const void *)sa;
        port = ntohs(s->sin6_port);
        if (IN6_IS_ADDR_LOOPBACK(&s->sin6_addr)) ip = INADDR_LOOPBACK;
    } else return;
    if ((ip >> 24) != 127 || port == 0 || port == 53 || !sock_is_dgram(fd)) return;
    uint64_t key = ((uint64_t)ip << 16) | (uint64_t)port;
    pthread_mutex_lock(&udp_mx);
    for (int i = 0; i < udp_nports; i++) if (udp_ports[i] == key) { pthread_mutex_unlock(&udp_mx); return; }
    if (udp_nports >= 64) { pthread_mutex_unlock(&udp_mx); return; }
    int us = socket(AF_INET, SOCK_DGRAM | SOCK_CLOEXEC, 0);
    struct sockaddr_in me = { .sin_family = AF_INET, .sin_port = htons(port), .sin_addr.s_addr = htonl(ip) };
    if (us < 0 || bind(us, (const void *)&me, sizeof me) != 0) {
        int e = errno;
        pthread_mutex_unlock(&udp_mx);
        if (us >= 0) close(us);
        tlog("udp %d: bind failed: %s", port, strerror(e));
        return;
    }
    udp_ports[udp_nports++] = key;
    pthread_mutex_unlock(&udp_mx);
    struct udp_job *job = calloc(1, sizeof *job);
    job->us = us; job->port = port; job->ip = ip;
    const char *fn = fake_name(ip);
    if (fn) snprintf(job->name, sizeof job->name, "%s", fn);
    pthread_t th;
    if (pthread_create(&th, NULL, udp_helper, job) == 0) pthread_detach(th);
    tlog("udp %d: helper bound %u.%u.%u.%u:%d (%s)", port, ip >> 24, (ip >> 16) & 255, (ip >> 8) & 255, ip & 255, port, fn ? fn : "-");
}

/* asio sends UDP with sendmsg (msg_name = destination): same rule as sendto */
ssize_t sendmsg(int fd, const struct msghdr *msg, int flags)
{
    REAL(sendmsg);
    if (msg && msg->msg_name && sock_is_dgram(fd)) {
        size_t tot = 0;
        for (size_t i = 0; i < msg->msg_iovlen; i++) tot += msg->msg_iov[i].iov_len;
        dgram_log("sendmsg", fd, msg->msg_name, tot);
    }
    if (redirect_on() && msg && msg->msg_name && !t_busy && sock_is_dgram(fd)) {
        const struct sockaddr *sa = msg->msg_name;
        union { struct sockaddr_in a4; struct sockaddr_in6 a6; } nw;
        struct msghdr m = *msg;
        uint32_t ip = sa_ip4(sa);
        int port = sa->sa_family == AF_INET ? ntohs(((const struct sockaddr_in *)sa)->sin_port)
                 : sa->sa_family == AF_INET6 ? ntohs(((const struct sockaddr_in6 *)sa)->sin6_port) : 0;
        int loop = (ip >> 24) == 127 || (sa->sa_family == AF_INET6 && IN6_IS_ADDR_LOOPBACK(&((const struct sockaddr_in6 *)sa)->sin6_addr));
        if (port && port != 53 && !loop && (sa->sa_family == AF_INET || sa->sa_family == AF_INET6)) {
            char a[96];
            addr_str(sa, a, sizeof a);
            tlog("udp redirect (sendmsg) %s -> 127.0.0.1:%d", a, port);
            memset(&nw, 0, sizeof nw);
            if (sa->sa_family == AF_INET) {
                nw.a4.sin_family = AF_INET; nw.a4.sin_port = htons(port); nw.a4.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
                m.msg_name = &nw.a4; m.msg_namelen = sizeof nw.a4;
            } else {
                nw.a6.sin6_family = AF_INET6; nw.a6.sin6_port = htons(port);
                inet_pton(AF_INET6, "::ffff:127.0.0.1", &nw.a6.sin6_addr);
                m.msg_name = &nw.a6; m.msg_namelen = sizeof nw.a6;
            }
            udp_prepare(fd, m.msg_name);
            return real_sendmsg(fd, &m, flags);
        }
        udp_prepare(fd, sa);
    }
    return real_sendmsg(fd, msg, flags);
}

/* diagnostics: every non-stream socket and the first sends on it (UDP, ICMP ping sockets) */
int socket(int domain, int type, int protocol)
{
    REAL(socket);
    int fd = real_socket(domain, type, protocol);
    int base = type & 0xf;
    if (!t_busy && (domain == AF_INET || domain == AF_INET6) && base != SOCK_STREAM)
        tlog("socket fd=%d domain=%d type=%d proto=%d", fd, domain, base, protocol);
    return fd;
}

static void dgram_log(const char *what, int fd, const struct sockaddr *sa, size_t len)
{
    static int count;
    if (t_busy || count > 200 || !sa) return;
    count++;
    char a[96];
    addr_str(sa, a, sizeof a);
    const char *fn = fake_name(sa_ip4(sa));
    tlog("%s fd=%d -> %s (%s) %zu bytes", what, fd, a, fn ? fn : "-", len);
}
