"""Record mode of mc5server (MC5_UPSTREAM=1): learn the real Gaia answers from the live servers, then implement them locally.

HTTP(S): a request whose Host is a real name (the phone's HTTPS to port 443 is redirected to our TLS server for the test) is sent to
https://<Host> and the pair request/answer is appended to work/real/trace/http.jsonl. The answer goes back to the client unchanged,
except the addresses of raw-socket services, which are replaced by our relays:
  game-server controller (Federation POST /sessions/... "launch game", Anubis quick_join_ah):
      controller_host + controller_tcp_port/_port, _http_port, _https_port -> 127.0.0.1:AH_PORT, +1, +2 (raw relays)
  Pandora locate alert  host:port                           -> 127.0.0.1:ALERT_PORT    (relay to the real alert, TLS on both sides)
The relays run in the HTTP instance; the real targets are passed through work/real/trace/relays.json (the instances are two processes).
Raw streams are logged as hex to work/real/trace/tcp.jsonl.
Everything to the real servers goes through the SOCKS5 proxy MC5_SOCKS (host:port; required in record mode).
"""
import asyncio
import json
import os
import ssl
import time

import httpx

HERE = os.path.dirname(os.path.abspath(__file__))
TRACE = os.environ.get("MC5_TRACE") or os.path.join(os.path.dirname(HERE), "work", "real", "trace")
ENABLED = os.environ.get("MC5_UPSTREAM") == "1"
LOCAL_HOSTS = ("127.0.0.1", "localhost")
DROP_REQ = {"host", "content-length", "connection", "accept-encoding"}
DROP_RESP = {"content-length", "content-encoding", "transfer-encoding", "connection"}
GROUPCHAT_PORT = 33700  # chat socket (HTTP over TLS, ChatLibv2): relayed like alert
SOCKS = os.environ.get("MC5_SOCKS", "")  # SOCKS5 proxy host:port for the traffic to the real servers
if ENABLED and ":" not in SOCKS:
    raise SystemExit("record mode (MC5_UPSTREAM=1) needs MC5_SOCKS=host:port of a SOCKS5 proxy")


async def socks_connect(host, port, ctx=None):
    """TCP to host:port through the SOCKS5 proxy (no auth, the name is resolved by the proxy), TLS on top if ctx is given."""
    sh, sp = SOCKS.rsplit(":", 1)
    reader, writer = await asyncio.open_connection(sh, int(sp))
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    if await reader.readexactly(2) != b"\x05\x00":
        raise OSError("socks: no-auth refused")
    name = host.encode()
    writer.write(b"\x05\x01\x00\x03" + bytes([len(name)]) + name + int(port).to_bytes(2, "big"))
    await writer.drain()
    head = await reader.readexactly(4)
    if head[1] != 0:
        raise OSError("socks: connect failed, code %d" % head[1])
    alen = {1: 4, 4: 16}.get(head[3])
    await reader.readexactly(alen + 2 if alen else (await reader.readexactly(1))[0] + 2)
    if ctx is None:
        return reader, writer
    # TLS over the established tunnel (Python 3.8: no StreamWriter.start_tls)
    loop = asyncio.get_running_loop()
    transport = writer.transport
    protocol = transport.get_protocol()
    tls = await loop.start_tls(transport, protocol, ctx, server_hostname=host)
    writer._transport = tls
    reader._transport = tls
    return reader, writer


def _append(name, entry):
    os.makedirs(TRACE, exist_ok=True)
    with open(os.path.join(TRACE, name), "a") as f:
        f.write(json.dumps(entry) + "\n")


def _body(data: bytes):
    """Full body: inline (latin1, lossless) up to 1 MB, larger ones to trace/bodies/<sha256>.bin."""
    if len(data) <= 1 << 20:
        return data.decode("latin1")
    import hashlib
    h = hashlib.sha256(data).hexdigest()
    d = os.path.join(TRACE, "bodies")
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, h + ".bin")
    if not os.path.exists(path):
        open(path, "wb").write(data)
    return {"file": "bodies/%s.bin" % h, "size": len(data), "sha256": h}


def _relays():
    try:
        return json.load(open(os.path.join(TRACE, "relays.json")))
    except (OSError, ValueError):
        return {}


def _set_relay(kind, host, port):
    r = _relays()
    r[kind] = [host, int(port)]
    os.makedirs(TRACE, exist_ok=True)
    json.dump(r, open(os.path.join(TRACE, "relays.json"), "w"))


POOL = list(range(33710, 33810))   # local ports for raw services handed out by the real servers (tools/run_servers.sh reverses them)


def pool_port(kind: str, host: str, port: int) -> int:
    """Local port relaying to host:port (same target -> same port). The mapping lives in relays.json (key pool:<port>)."""
    r = _relays()
    now = time.time()
    for lp in POOL:
        v = r.get("pool:%d" % lp)
        if v and v[:3] == [host, int(port), kind]:
            v[3:] = [now]
            json.dump(r, open(os.path.join(TRACE, "relays.json"), "w"))
            return lp
    used = {int(k.split(":")[1]): (r[k][3] if len(r[k]) > 3 else 0) for k in r if k.startswith("pool:")}
    free = [lp for lp in POOL if lp not in used]
    lp = free[0] if free else min(used, key=used.get)   # full: the least recently used mapping is replaced
    r["pool:%d" % lp] = [host, int(port), kind, now]
    os.makedirs(TRACE, exist_ok=True)
    json.dump(r, open(os.path.join(TRACE, "relays.json"), "w"))
    return lp


_ROOM_PORTS = (("ah", "controller_tcp_port"), ("ah_http", "controller_http_port"), ("ah_https", "controller_https_port"),
               ("ah", "controller_port"), ("ah", "pport"), ("lobby", "lobby_tcp_port"), ("lobby", "lobby_port"), ("lobby_http", "lobby_http_port"))


def _rewrite_rooms(o) -> int:
    """Recursively give every room (dict with controller_host/lobby_host) local pool ports and host 127.0.0.1. Returns rooms rewritten."""
    n = 0
    if isinstance(o, list):
        for x in o:
            n += _rewrite_rooms(x)
    elif isinstance(o, dict):
        if "controller_host" in o or "lobby_host" in o:
            local = {}
            for kind, key in _ROOM_PORTS:
                if key in o and isinstance(o[key], int):
                    h = o.get("lobby_host") if kind.startswith("lobby") else o.get("controller_host")
                    if not h or h == "127.0.0.1":
                        continue
                    if (h, o[key]) not in local:
                        local[(h, o[key])] = pool_port(kind, h, o[key])
                    o[key] = local[(h, o[key])]
            for key in ("controller_host", "controller_public_host", "controller_private_host", "lobby_host"):
                if key in o:
                    o[key] = "127.0.0.1"
            n += 1
        for v in o.values():
            if isinstance(v, (list, dict)):
                n += _rewrite_rooms(v)
    return n


def is_upstream(host_header: str) -> bool:
    return ENABLED and host_header.split(":")[0] not in LOCAL_HOSTS and host_header != ""


# Routing by path for requests sent to OUR address (no DNAT, no root): our Eve/Pandora give the client local addresses, the
# account services behind them go to the real hosts. Eve, Pandora, Iris stay local, so the client never learns a real address.
ROUTES = [("/authorize", "janus.gold0033.gameloft.com"), ("/users/", "janus.gold0033.gameloft.com"),
          ("/encrypt_token", "janus.gold0033.gameloft.com"), ("/accounts/", "osiris.gold0033.gameloft.com"),
          ("/messages/", "hermes.gold0033.gameloft.com"), ("/sessions/", "fed.gold0033.gameloft.com"),
          ("/rooms/", "anubisfinder.gold0033.gameloft.com"), ("/assign_global_id/", "gdid.datalake.gameloft.com")]


def route(path: str):
    if not ENABLED:
        return None
    for prefix, host in ROUTES:
        if path.startswith(prefix):
            return host
    return None


async def forward(request, body: bytes, ah_port: int, alert_port: int, host: str = None):
    """Send the request to the real host, record it, rewrite raw-socket addresses, return (status, headers, content)."""
    host = host or request.headers["host"].split(":")[0]
    # the raw path as the client sent it: credentials in paths carry %2F/%2B, the decoded path is a different (404) resource
    raw = request.scope.get("raw_path") or request.url.path.encode()
    # keep the scheme the client used: plain-HTTP hosts (e.g. ingamenews) are not served over TLS by the real side
    scheme = "http" if request.url.scheme == "http" and not request.headers.get("host", "").startswith(("127.0.0.1", "localhost")) else "https"
    url = "%s://%s%s" % (scheme, host, raw.decode("latin1")) + ("?" + request.url.query if request.url.query else "")
    headers = {k: v for k, v in request.headers.items() if k.lower() not in DROP_REQ}
    headers["host"] = host
    r, err = None, None
    for attempt in range(3):          # the proxy/real servers sometimes drop a connection without an answer: retry
        try:
            async with httpx.AsyncClient(timeout=30, proxies="socks5://" + SOCKS) as c:
                r = await c.request(request.method, url, headers=headers, content=body)
            break
        except httpx.HTTPError as e:
            err = e
            await asyncio.sleep(0.5)
    if r is None:                     # no answer at all: a clean 502 instead of an exception (500) in the server
        _append("http.jsonl", {"t": round(time.time(), 3), "method": request.method, "url": url, "req_headers": dict(request.headers),
                               "req_body": _body(body), "status": 502, "error": repr(err)})
        return 502, {"content-type": "text/plain"}, b"upstream error"
    content = r.content
    entry = {"t": round(time.time(), 3), "method": request.method, "url": url, "req_headers": dict(request.headers), "req_body": _body(body),
             "status": r.status_code, "resp_headers": [list(kv) for kv in r.headers.multi_items()], "resp_body": _body(content)}
    if r.status_code == 200 and (b"controller_host" in content or b"lobby_host" in content):
        try:
            j = json.loads(content)
        except ValueError:
            j = None
        n = _rewrite_rooms(j)   # any object with controller_*/lobby_* (Anubis answers: one room or a list of rooms)
        if n:
            content = json.dumps(j).encode()
            entry["rewritten"] = content.decode()
        if False:
            host = None
            local = {}
            for kind, key in (("ah", "controller_tcp_port"), ("ah_http", "controller_http_port"), ("ah_https", "controller_https_port"),
                              ("ah", "controller_port"), ("ah", "pport"), ("lobby", "lobby_tcp_port"), ("lobby", "lobby_port"),
                              ("lobby_http", "lobby_http_port")):
                if key in j and isinstance(j[key], int):
                    h = j.get("lobby_host", host) if kind.startswith("lobby") else host
                    if (h, j[key]) not in local:
                        local[(h, j[key])] = pool_port(kind, h, j[key])
                    j[key] = local[(h, j[key])]
            for key in ("controller_host", "controller_public_host", "controller_private_host", "lobby_host"):
                if key in j:
                    j[key] = "127.0.0.1"
            content = json.dumps(j).encode()
            entry["rewritten"] = content.decode()
    q = str(request.url.query)
    if request.url.path.endswith("/locate") and r.status_code == 200 and not any(("service=%s" % s) in q for s in ("alert", "groupchat")):
        text = content.decode("latin1").strip()
        if ":" in text and not text.endswith(":443"):
            h, p = text.rsplit(":", 1)
            if p.isdigit():
                svc = (q.split("service=", 1)[1].split("&", 1)[0]) if "service=" in q else "svc"
                content = ("127.0.0.1:%d" % pool_port(svc, h, int(p))).encode()
                entry["rewritten"] = content.decode()
    for svc, local in (("alert", alert_port), ("groupchat", GROUPCHAT_PORT)):
        if request.url.path.endswith("/locate") and ("service=%s" % svc) in q and r.status_code == 200:
            text = content.decode("latin1").strip()
            if ":" in text:
                h, p = text.rsplit(":", 1)
                _set_relay(svc, h, p)
                content = ("127.0.0.1:%d" % local).encode()
                entry["rewritten"] = content.decode()
    _append("http.jsonl", entry)
    out_headers = {k: v for k, v in r.headers.items() if k.lower() not in DROP_RESP}
    return r.status_code, out_headers, content


class _CrmPatch:
    """AH server->client stream: the real CRM config ('?' frame) turns on the Didomi consent gate (`didomi_type`), whose web SDK
    needs the internet; the phone has none. Only that field is set to [] (what our own server sends); everything else passes
    unchanged. The trace keeps the original bytes."""

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes) -> bytes:
        import sys
        sys.path.insert(0, HERE)
        from mc5 import ahproto, lz4
        self.buf += data
        out = b""
        while self.buf:
            if self.buf[:1] == b"{":
                i = self.buf.find(b"\n")
                if i < 0:
                    break
                out, self.buf = out + self.buf[:i + 1], self.buf[i + 1:]
                continue
            if len(self.buf) < 3:
                break
            n = int.from_bytes(self.buf[1:3], "big")
            if len(self.buf) < n:
                break
            fr, self.buf = self.buf[:n], self.buf[n:]
            if fr[0] == ahproto.S_CRM:
                try:
                    raw = lz4.unpack_sized(fr[3:])
                    j = json.loads(raw.rstrip(b"\0"))
                    gp = j.get("game", {}).get("_global_params", {})
                    if gp.get("didomi_type"):
                        gp["didomi_type"] = []
                        fr = ahproto.crm(j)
                        _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": "ah", "dir": "s2c", "len": 0, "hex": "",
                                              "event": "patched CRM: didomi_type -> []"})
                except Exception as e:  # never break the stream because of the patch
                    _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": "ah", "dir": "s2c", "len": 0, "hex": "", "event": "crm patch failed: %r" % e})
            out += fr
        return out


class _UrlPatch:
    """HTTP responses of the chat service (groupchat) carry further endpoints (`cmd_url` https://host:port, `listen_url` http://host:port).
    Each complete response (headers + Content-Length body) gets those host:port replaced by pool relays; Content-Length is fixed."""
    URL = __import__("re").compile(rb"(https?)://([A-Za-z0-9.\-]+):(\d+)")

    def __init__(self, kind):
        self.kind, self.buf = kind, b""

    def feed(self, data: bytes) -> bytes:
        self.buf += data
        out = b""
        while True:
            h = self.buf.find(b"\r\n\r\n")
            if h < 0 or not self.buf.startswith(b"HTTP/"):
                if not self.buf.startswith(b"HTTP/") and self.buf:   # not HTTP (stream data): pass through
                    out, self.buf = out + self.buf, b""
                break
            head = self.buf[:h].decode("latin1")
            n = 0
            for line in head.split("\r\n")[1:]:
                if line.lower().startswith("content-length:"):
                    n = int(line.split(":", 1)[1])
            if n == 0 and "content-length" not in head.lower():
                out, self.buf = out + self.buf, b""   # chunked/streaming: pass through
                break
            if len(self.buf) < h + 4 + n:
                break
            body, self.buf = self.buf[h + 4:h + 4 + n], self.buf[h + 4 + n:]

            def sub(m):
                lp = pool_port(self.kind + "_" + m.group(1).decode(), m.group(2).decode(), int(m.group(3)))
                return b"%s://127.0.0.1:%d" % (m.group(1), lp)
            new = self.URL.sub(sub, body)
            if new != body:
                _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": self.kind, "dir": "s2c", "len": 0, "hex": "",
                                      "event": "rewritten urls: %s" % new[:300].decode("latin1")})
            lines = [l for l in head.split("\r\n") if not l.lower().startswith("content-length:")]
            out += ("\r\n".join(lines) + "\r\nContent-Length: %d\r\n\r\n" % len(new)).encode("latin1") + new
        return out


async def _pipe(kind, direction, reader, writer):
    patch = _CrmPatch() if (kind, direction) == ("ah", "s2c") else _UrlPatch(kind) if (kind, direction) == ("groupchat", "s2c") else None
    try:
        while True:
            data = await reader.read(65536)
            if not data:
                break
            _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": direction, "len": len(data), "hex": data.hex()})
            writer.write(patch.feed(data) if patch else data)
            await writer.drain()
        _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": direction, "len": 0, "hex": "", "event": "eof"})
    except (ConnectionError, asyncio.IncompleteReadError, ssl.SSLError) as e:
        _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": direction, "len": 0, "hex": "", "event": "error: %r" % e})
    finally:
        writer.close()


def _relay_handler(kind, upstream_tls, log):
    async def handle(c_reader, c_writer):
        target = _relays().get(kind)
        if not target:
            log("%s relay: no upstream known yet" % kind)
            c_writer.close()
            return
        host, port = target
        ctx = None
        if upstream_tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        try:
            if os.environ.get("MC5_SOCKS_TCP") == "direct":   # diagnostics: raw sockets without the SOCKS proxy
                u_reader, u_writer = await asyncio.open_connection(host, port, ssl=ctx, server_hostname=host if ctx else None)
            else:
                u_reader, u_writer = await socks_connect(host, port, ctx)
        except OSError as e:
            log("%s relay: upstream %s:%s failed: %s" % (kind, host, port, e))
            c_writer.close()
            return
        log("%s relay: client <-> %s:%s" % (kind, host, port))
        await asyncio.gather(_pipe(kind, "c2s", c_reader, u_writer), _pipe(kind, "s2c", u_reader, c_writer))
        log("%s relay: closed" % kind)
    return handle


def _pool_handler(lp, cert, key, log):
    """Relay for a pool port. TLS is detected from the client's first bytes (ClientHello 0x16); if the client stays silent ~1.5 s the
    server speaks first (AH protocol) and the stream is relayed raw. TLS is terminated on our side so the trace holds plaintext."""
    async def handle(c_reader, c_writer):
        target = _relays().get("pool:%d" % lp)
        if not target:
            log("pool %d: no target" % lp)
            c_writer.close()
            return
        host, port, kind = target[:3]
        await _relay_auto(c_reader, c_writer, host, port, kind, "pool %d" % lp, cert, key, log)
    return handle


async def _relay_auto(c_reader, c_writer, host, port, kind, tag, cert, key, log):
    """Relay a client stream to host:port through the proxy; TLS (terminated here, plaintext in the trace) or raw, by who speaks first."""
    lp = tag
    if True:
        # connect upstream at once (game servers speak first); decide TLS by who talks first
        try:
            u_reader, u_writer = await socks_connect(host, port, None)
        except OSError as e:
            log("%s (%s): upstream %s:%s failed: %s" % (lp, kind, host, port, e))
            c_writer.close()
            return
        c_task = asyncio.ensure_future(c_reader.read(65536))
        u_task = asyncio.ensure_future(u_reader.read(65536))
        done, _ = await asyncio.wait({c_task, u_task}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
        first, server_first = b"", b""
        if u_task in done:
            server_first = u_task.result()
            c_task.cancel()
        elif c_task in done:
            first = c_task.result()
            u_task.cancel()
        else:
            c_task.cancel()
            u_task.cancel()
        # let the cancelled read finish before the pipes read the same stream again
        await asyncio.gather(*(t for t in (c_task, u_task) if t.cancelled() or not t.done()), return_exceptions=True)
        tls = first[:1] == b"\x16"
        if tls:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            loop = asyncio.get_running_loop()
            t = await loop.start_tls(u_writer.transport, u_writer.transport.get_protocol(), ctx, server_hostname=host)
            u_writer._transport = t
            u_reader._transport = t
        if server_first:
            _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": "s2c", "len": len(server_first), "hex": server_first.hex()})
            c_writer.write(server_first)
        log("%s (%s): client <-> %s:%s%s" % (lp, kind, host, port, " (TLS)" if tls else ""))
        if not tls:
            if first:
                _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": "c2s", "len": len(first), "hex": first.hex()})
                u_writer.write(first)
            await asyncio.gather(_pipe(kind, "c2s", c_reader, u_writer), _pipe(kind, "s2c", u_reader, c_writer))
            return
        # terminate the client's TLS with our certificate (memory BIO), plaintext both ways
        sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        sctx.load_cert_chain(cert, key)
        inc, out = ssl.MemoryBIO(), ssl.MemoryBIO()
        sobj = sctx.wrap_bio(inc, out, server_side=True)
        inc.write(first)

        async def flush():
            data = out.read()
            if data:
                c_writer.write(data)
                await c_writer.drain()
        try:
            while True:
                try:
                    sobj.do_handshake()
                    break
                except ssl.SSLWantReadError:
                    await flush()
                    data = await c_reader.read(65536)
                    if not data:
                        return
                    inc.write(data)
            await flush()

            async def c2s():
                while True:
                    try:
                        plain = sobj.read(65536)
                    except ssl.SSLWantReadError:
                        data = await c_reader.read(65536)
                        if not data:
                            break
                        inc.write(data)
                        continue
                    if not plain:
                        break
                    _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": "c2s", "len": len(plain), "hex": plain.hex()})
                    u_writer.write(plain)
                    await u_writer.drain()
                u_writer.close()

            async def s2c():
                while True:
                    data = await u_reader.read(65536)
                    if not data:
                        break
                    _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": "s2c", "len": len(data), "hex": data.hex()})
                    sobj.write(data)
                    await flush()
                c_writer.close()
            await asyncio.gather(c2s(), s2c())
        except (ConnectionError, ssl.SSLError) as e:
            log("%s (%s): %s" % (lp, kind, e))
        finally:
            log("%s (%s): closed" % (lp, kind))


TCP_TUN_PORT = 33698   # TCP from the tracer: "MC5T", u8 name length, name, u16 port (any Gameloft host, any port but 443/80)


def _tcp_tunnel_handler(cert, key, log):
    async def handle(c_reader, c_writer):
        try:
            if await c_reader.readexactly(4) != b"MC5T":
                c_writer.close()
                return
            n = (await c_reader.readexactly(1))[0]
            host = (await c_reader.readexactly(n)).decode()
            port = int.from_bytes(await c_reader.readexactly(2), "big")
        except asyncio.IncompleteReadError:
            c_writer.close()
            return
        await _relay_auto(c_reader, c_writer, host, port, "tcp:%s:%d" % (host.split(".")[0], port), "tunnel", cert, key, log)
    return handle


UDP_TUN_PORT = 33699   # TCP from the tracer on the phone (mc5trace/15_udp.c), adb reverse


def _udp_target_host():
    """The game server host for UDP: the controller host of the most recent pool mapping of kind ah/lobby (matchmaking answer)."""
    r = _relays()
    best = None
    for k, v in r.items():
        if k.startswith("pool:") and len(v) >= 3 and v[2] in ("ah", "lobby"):
            if best is None or (len(v) > 3 and v[3] > best[1]):
                best = (v[0], v[3] if len(v) > 3 else 0)
    return best[0] if best else None


async def _socks_udp_associate():
    """SOCKS5 UDP ASSOCIATE: returns (control writer, relay (host, port)). The control TCP connection must stay open."""
    sh, sp = SOCKS.rsplit(":", 1)
    reader, writer = await asyncio.open_connection(sh, int(sp))
    writer.write(b"\x05\x01\x00")
    await writer.drain()
    if await reader.readexactly(2) != b"\x05\x00":
        raise OSError("socks: no-auth refused")
    writer.write(b"\x05\x03\x00\x01" + bytes(6))
    await writer.drain()
    head = await reader.readexactly(4)
    if head[1] != 0:
        raise OSError("socks: udp associate failed, code %d" % head[1])
    import socket as _s
    addr = await reader.readexactly(4) if head[3] == 1 else (await reader.readexactly((await reader.readexactly(1))[0]))
    port = int.from_bytes(await reader.readexactly(2), "big")
    host = _s.inet_ntoa(addr) if head[3] == 1 else addr.decode()
    if host == "0.0.0.0":
        host = sh
    return writer, (host, port)


def _udp_tunnel_handler(log):
    """Phone tracer -> (TCP frames) -> here -> SOCKS5 UDP -> real game server. Datagrams both ways are recorded as kind udp:<port>."""
    async def handle(reader, writer):
        try:
            hello = await reader.readexactly(6)
        except asyncio.IncompleteReadError:
            writer.close()
            return
        if hello[:4] != b"MC5U":
            writer.close()
            return
        port = int.from_bytes(hello[4:6], "big")
        kind = "udp:%d" % port
        try:
            nl = (await reader.readexactly(1))[0]
            named = (await reader.readexactly(nl)).decode() if nl else ""
        except asyncio.IncompleteReadError:
            named = ""
        host = named or _udp_target_host()
        if not host:
            log("%s: no game server host known" % kind)
            writer.close()
            return
        try:
            ctl, relay = await _socks_udp_associate()
        except OSError as e:
            log("%s: %s" % (kind, e))
            writer.close()
            return
        loop = asyncio.get_running_loop()
        name = host.encode()
        head = b"\x00\x00\x00\x03" + bytes([len(name)]) + name + port.to_bytes(2, "big")

        class Proto(asyncio.DatagramProtocol):
            def datagram_received(self, data, addr):
                # strip the SOCKS5 UDP header (atyp 1: 10 bytes, atyp 3: 7 + name)
                atyp = data[3]
                off = 10 if atyp == 1 else 22 if atyp == 4 else 7 + data[4]
                payload = data[off:]
                _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": "s2c", "len": len(payload), "hex": payload.hex()})
                writer.write(len(payload).to_bytes(2, "big") + payload)
        transport, _ = await loop.create_datagram_endpoint(Proto, remote_addr=relay)
        log("%s: tunnel <-> %s:%d via SOCKS5 UDP %s:%d" % (kind, host, port, relay[0], relay[1]))
        n = 0
        try:
            while True:
                h = await reader.readexactly(2)
                data = await reader.readexactly(int.from_bytes(h, "big"))
                _append("tcp.jsonl", {"t": round(time.time(), 3), "kind": kind, "dir": "c2s", "len": len(data), "hex": data.hex()})
                transport.sendto(head + data)
                n += 1
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            log("%s: tunnel closed after %d datagrams up" % (kind, n))
            transport.close()
            ctl.close()
            writer.close()
    return handle


async def start_relays(ah_port, alert_port, cert, key, log):
    """HTTP instance only. alert is TLS on the client side (it accepts any certificate) and on the real side; AH is relayed raw."""
    sctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    sctx.load_cert_chain(cert, key)
    await asyncio.start_server(_relay_handler("alert", True, log), "127.0.0.1", alert_port, ssl=sctx)
    await asyncio.start_server(_relay_handler("groupchat", True, log), "127.0.0.1", GROUPCHAT_PORT, ssl=sctx)
    for i, kind in enumerate(("ah", "ah_http", "ah_https")):
        await asyncio.start_server(_relay_handler(kind, False, log), "127.0.0.1", ah_port + i)
    for lp in POOL:
        await asyncio.start_server(_pool_handler(lp, cert, key, log), "127.0.0.1", lp)
    await asyncio.start_server(_udp_tunnel_handler(log), "127.0.0.1", UDP_TUN_PORT)
    await asyncio.start_server(_tcp_tunnel_handler(cert, key, log), "127.0.0.1", TCP_TUN_PORT)
    log("record mode: relays on %d (alert, TLS) and %d..%d (ah tcp/http/https, raw); trace in %s" % (alert_port, ah_port, ah_port + 2, TRACE))
