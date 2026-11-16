
/* ---- network ---- */
static void addr_str(const struct sockaddr *sa, char *out, size_t n)
{
    char ip[64] = "?";
    int port = 0;
    if (!sa) { snprintf(out, n, "(null)"); return; }
    if (sa->sa_family == AF_INET) {
        const struct sockaddr_in *s = (const void *)sa;
        inet_ntop(AF_INET, &s->sin_addr, ip, sizeof ip); port = ntohs(s->sin_port);
    } else if (sa->sa_family == AF_INET6) {
        const struct sockaddr_in6 *s = (const void *)sa;
        inet_ntop(AF_INET6, &s->sin6_addr, ip, sizeof ip); port = ntohs(s->sin6_port);
    } else if (sa->sa_family == AF_UNIX) {
        snprintf(out, n, "unix:%s", ((const char *)sa) + 2); return;
    }
    snprintf(out, n, "%s:%d", ip, port);
}

/* MC5_REDIRECT=1: nothing leaves the phone. Any non-loopback TCP connect is sent to the PC server through `adb reverse`:
 * port 443 -> MC5_PORT_TLS (18443), port 80 -> MC5_PORT_HTTP (18080), other ports (controller, alert) unchanged on 127.0.0.1.
 * Replaces the iptables DNAT of the root diagnostics. IPv6 sockets get the IPv4-mapped loopback. */
static int redirect_on(void)
{
    static int v = -1;
    if (v < 0) { const char *e = getenv("MC5_REDIRECT"); v = e && *e == '1'; }
    return v;
}

/* The bridge's forwarders (threads fwd-conn-*, documentation/architecture.md) run in the game process and must reach the real server address. */
static int bridge_thread(void)
{
    char n[20] = "";
    prctl(PR_GET_NAME, n, 0, 0, 0);
    return !strncmp(n, "fwd-conn-", 9);
}

static int env_port(const char *name, int def)
{
    const char *e = getenv(name);
    return e && atoi(e) > 0 ? atoi(e) : def;
}

int getaddrinfo(const char *node, const char *service, const struct addrinfo *hints, struct addrinfo **res)
{
    REAL(getaddrinfo);
    try_iris_hook();
    static int started; if (!started) { started = 1; tlog("mc5trace start pid=%d", (int)getpid()); }
    char fk[32];
    if (redirect_on() && node && strstr(node, "gameloft")) {
        uint32_t ip = fake_ip(node);
        snprintf(fk, sizeof fk, "%u.%u.%u.%u", ip >> 24, (ip >> 16) & 255, (ip >> 8) & 255, ip & 255);
        tlog("resolve %s -> %s", node, fk);
        node = fk;
    }
    int r = real_getaddrinfo(node, service, hints, res);
    if (!t_busy) {
        char first[80] = "-";
        if (r == 0 && res && *res) addr_str((*res)->ai_addr, first, sizeof first);
        tlog("getaddrinfo %s:%s -> %d %s", node ? node : "(null)", service ? service : "", r, first);
    }
    return r;
}

struct hostent *gethostbyname(const char *name)
{
    REAL(gethostbyname);
    if (redirect_on() && name && strstr(name, "gameloft")) {
        static struct in_addr lo; static char *lst[2]; static char *alias[1]; static struct hostent he;
        uint32_t ip = fake_ip(name);
        lo.s_addr = htonl(ip); lst[0] = (char *)&lo; lst[1] = NULL; alias[0] = NULL;
        he.h_name = (char *)name; he.h_aliases = alias; he.h_addrtype = AF_INET; he.h_length = 4; he.h_addr_list = lst;
        tlog("resolve %s -> %u.%u.%u.%u (gethostbyname)", name, ip >> 24, (ip >> 16) & 255, (ip >> 8) & 255, ip & 255);
        return &he;
    }
    struct hostent *h = real_gethostbyname(name);
    if (!t_busy) {
        char ip[64] = "-";
        if (h && h->h_addr_list[0]) inet_ntop(h->h_addrtype, h->h_addr_list[0], ip, sizeof ip);
        tlog("gethostbyname %s -> %s", name ? name : "(null)", ip);
    }
    return h;
}

int connect(int fd, const struct sockaddr *sa, socklen_t len)
{
    REAL(connect);
    try_iris_hook();
    union { struct sockaddr_in a4; struct sockaddr_in6 a6; } nw;
    if (redirect_on() && sa && !bridge_thread()) {
        int port = 0, loop = 0, fam = sa->sa_family;
        if (fam == AF_INET) {
            const struct sockaddr_in *s = (const void *)sa;
            port = ntohs(s->sin_port); loop = (ntohl(s->sin_addr.s_addr) >> 24) == 127;
        } else if (fam == AF_INET6) {
            const struct sockaddr_in6 *s = (const void *)sa;
            port = ntohs(s->sin6_port); loop = IN6_IS_ADDR_LOOPBACK(&s->sin6_addr);
        }
        const char *fname = fake_name(sa_ip4(sa));
        if (fname && port != 443 && port != 80 && !t_busy && !sock_is_dgram(fd)) {
            int r = tcp_tunnel(fd, fname, port);
            tlog("tunnel %s:%d -> %d", fname, port, r);
            return r;
        }
        if ((fam == AF_INET || fam == AF_INET6) && (!loop || fname || port == 443 || port == 80)) {
            int np = port == 443 ? env_port("MC5_PORT_TLS", 18443) : port == 80 ? env_port("MC5_PORT_HTTP", 18080) : port;
            char a[96];
            addr_str(sa, a, sizeof a);
            tlog("redirect %s -> 127.0.0.1:%d", a, np);
            memset(&nw, 0, sizeof nw);
            if (fam == AF_INET) {
                nw.a4.sin_family = AF_INET; nw.a4.sin_port = htons(np); nw.a4.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
                sa = (const void *)&nw.a4; len = sizeof nw.a4;
            } else {
                nw.a6.sin6_family = AF_INET6; nw.a6.sin6_port = htons(np);
                inet_pton(AF_INET6, "::ffff:127.0.0.1", &nw.a6.sin6_addr);
                sa = (const void *)&nw.a6; len = sizeof nw.a6;
            }
        }
    }
    udp_prepare(fd, sa);
    int r = real_connect(fd, sa, len);
    if (!t_busy && sa && sa->sa_family != AF_UNIX) {
        int e = errno;
        char a[96];
        addr_str(sa, a, sizeof a);
        tlog("connect fd=%d %s -> %d %s", fd, a, r, r ? strerror(e) : "");
        errno = e;
    }
    return r;
}

static void log_data(const char *what, int fd, const void *buf, ssize_t n)
{
    if (t_busy || n <= 0 || !buf) return;
    const unsigned char *p = buf;
    if (n >= 3 && p[0] == 0x16 && p[1] == 0x03) { tlog("%s fd=%d TLS handshake %zd bytes", what, fd, n); return; }
    if (n >= 4 && (!memcmp(p, "GET ", 4) || !memcmp(p, "POST", 4) || !memcmp(p, "HEAD", 4) || !memcmp(p, "PUT ", 4) ||
                   !memcmp(p, "HTTP", 4) || !memcmp(p, "DELE", 4))) {
        char pv[400];
        preview(pv, sizeof pv, buf, n < 600 ? (size_t)n : 600);
        tlog("%s fd=%d %zd: %s", what, fd, n, pv);
    }
}

ssize_t send(int fd, const void *buf, size_t len, int flags)
{
    REAL(send);
    ssize_t r = real_send(fd, buf, len, flags);
    log_data("send", fd, buf, r);
    return r;
}

ssize_t sendto(int fd, const void *buf, size_t len, int flags, const struct sockaddr *sa, socklen_t alen)
{
    REAL(sendto);
    if (sa && sock_is_dgram(fd)) dgram_log("sendto", fd, sa, len);
    union { struct sockaddr_in a4; struct sockaddr_in6 a6; } nw;
    if (redirect_on() && sa && sock_is_dgram(fd) && (sa->sa_family == AF_INET || sa->sa_family == AF_INET6)) {
        /* UDP to a real address (not loopback) stays on the phone: same port on 127.0.0.1, tunnelled by udp_prepare */
        int port = 0, loop = 1;
        if (sa->sa_family == AF_INET) {
            const struct sockaddr_in *s = (const void *)sa;
            port = ntohs(s->sin_port); loop = (ntohl(s->sin_addr.s_addr) >> 24) == 127;
        } else {
            const struct sockaddr_in6 *s = (const void *)sa;
            port = ntohs(s->sin6_port);
            loop = IN6_IS_ADDR_LOOPBACK(&s->sin6_addr) || (IN6_IS_ADDR_V4MAPPED(&s->sin6_addr) && s->sin6_addr.s6_addr[12] == 127);
        }
        if (!loop && port != 53) {
            char a[96];
            addr_str(sa, a, sizeof a);
            tlog("udp redirect %s -> 127.0.0.1:%d", a, port);
            memset(&nw, 0, sizeof nw);
            if (sa->sa_family == AF_INET) {
                nw.a4.sin_family = AF_INET; nw.a4.sin_port = htons(port); nw.a4.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
                sa = (const void *)&nw.a4; alen = sizeof nw.a4;
            } else {
                nw.a6.sin6_family = AF_INET6; nw.a6.sin6_port = htons(port);
                inet_pton(AF_INET6, "::ffff:127.0.0.1", &nw.a6.sin6_addr);
                sa = (const void *)&nw.a6; alen = sizeof nw.a6;
            }
        }
        udp_prepare(fd, sa);
    }
    ssize_t r = real_sendto(fd, buf, len, flags, sa, alen);
    log_data("sendto", fd, buf, r);
    return r;
}

ssize_t recv(int fd, void *buf, size_t len, int flags)
{
    REAL(recv);
    ssize_t r = real_recv(fd, buf, len, flags);
    log_data("recv", fd, buf, r);
    return r;
}

ssize_t recvfrom(int fd, void *buf, size_t len, int flags, struct sockaddr *sa, socklen_t *alen)
{
    REAL(recvfrom);
    ssize_t r = real_recvfrom(fd, buf, len, flags, sa, alen);
    log_data("recvfrom", fd, buf, r);
    return r;
}
