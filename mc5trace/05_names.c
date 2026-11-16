/* ---- fake addresses for Gameloft host names (MC5_REDIRECT=1) ----
 * Every name containing "gameloft" resolves to its own loopback address 127.10.<hi>.<lo>, so a later connect/sendto tells which real
 * host the client means, even when the address came from inside a binary protocol (lobby -> match controller). Port 443/80 still go to
 * the PC server (18443/18080); any other port is tunnelled with the real name (mc5trace/15_udp.c: TCP 33698, UDP 33699). */
static char *fk_names[4096];
static int fk_n;
static pthread_mutex_t fk_mx = PTHREAD_MUTEX_INITIALIZER;

static uint32_t fake_ip(const char *name)   /* host byte order */
{
    pthread_mutex_lock(&fk_mx);
    int i;
    for (i = 0; i < fk_n; i++) if (!strcmp(fk_names[i], name)) break;
    if (i == fk_n && fk_n < 4095) fk_names[fk_n++] = strdup(name);
    pthread_mutex_unlock(&fk_mx);
    i += 1;
    return (127u << 24) | (10u << 16) | ((uint32_t)(i >> 8) << 8) | (uint32_t)(i & 255);
}

static const char *fake_name(uint32_t ip)    /* host byte order; NULL if not one of ours */
{
    if ((ip >> 16) != ((127u << 8) | 10u)) return NULL;
    int i = (int)(ip & 0xffff) - 1;
    pthread_mutex_lock(&fk_mx);
    const char *n = (i >= 0 && i < fk_n) ? fk_names[i] : NULL;
    pthread_mutex_unlock(&fk_mx);
    return n;
}

/* IPv4 address of a sockaddr (also v4-mapped IPv6), host byte order; 0 if none */
static uint32_t sa_ip4(const struct sockaddr *sa)
{
    if (!sa) return 0;
    if (sa->sa_family == AF_INET) return ntohl(((const struct sockaddr_in *)sa)->sin_addr.s_addr);
    if (sa->sa_family == AF_INET6) {
        const struct sockaddr_in6 *s = (const void *)sa;
        if (IN6_IS_ADDR_V4MAPPED(&s->sin6_addr)) { uint32_t v; memcpy(&v, &s->sin6_addr.s6_addr[12], 4); return ntohl(v); }
    }
    return 0;
}
