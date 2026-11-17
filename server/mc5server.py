#!/usr/bin/env python3
"""Local server for Modern Combat 5 6.0.12a: replaces the Gameloft servers the client talks to (documentation/protocol.md).

One process, one shared state (server/mc5/store.py):
  HTTP  :18080   Gaia services (server/mc5/gaia.py): Eve, Pandora, GDID, Janus, Osiris, Hermes, Federation, Anubis, Iris, sink, oct, iap
  HTTPS :18443   the same app (the client calls Janus/Federation/Iris over TLS; certificate work/tls/self.pem, client patched TLS_NOVERIFY)
  alert :33508   TLS SSE socket (server/mc5/alert.py)
  AH    :33600   game server = player profile (server/mc5/ah.py); :33601/:33602 only log (controller http/https ports)
Record mode (MC5_UPSTREAM=1, server/mc5proxy.py): requests for real hosts and the alert/AH sockets go to the real servers through SOCKS5.

Reference data (Gameloft's CRM, events, catalogue, Iris assets, campaign table) is not part of the repository: `--data <folder>` (default server/data),
see documentation/development.md. Without it the server says which files are missing and stops.

Run:  .venv/bin/python server/mc5server.py [--tls-cert work/tls/self.pem --tls-key work/tls/self.key] [--state work/state/mc5_state.json] [--data <folder>]
"""
import argparse
import asyncio
import os
import signal
import time
from email.utils import formatdate

import uvicorn
from starlette.requests import Request
from starlette.responses import Response

try:
    import mc5proxy
except ImportError:             # record mode needs httpx (PC only); on the phone (bridge) there is no upstream
    class mc5proxy:             # noqa: N801
        ENABLED = False
        SOCKS = ""

        @staticmethod
        def route(path):
            return None

        @staticmethod
        def is_upstream(host):
            return False
from mc5 import gaia, iap, tokens
from mc5.ah import AHServer
from mc5.alert import serve as serve_alert
from mc5.liveops import LiveOps
from mc5.store import Store

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
# Gameloft reference data the server cannot run without (recorded from the real servers / read from the client, documentation/architecture.md);
# the rest of the data folder (Iris pictures, campaign.json) is optional: without it those features are missing
DATA_FILES = ("ah/crm.json", "ah/events.json", "ah/meta.json", "ah/config.bin", "ah/new_profile.json", "iris/game_object", "ads_config.json")


def log(msg: str):
    print(time.strftime("%H:%M:%S ") + "[mc5] " + msg, flush=True)


def date_header(send):
    """`Date:` with a capital D (and every other header name capitalised), as nginx/Tornado on the real servers. The client finds the server time by a case-sensitive search for
    "Date:" in each header line (libMC5 0xc75bbc: std::string::find, then the value from offset 6); uvicorn writes `date:` -> the client
    had no server time (Lucky Spin timer counted from 0: "20755d", documentation/protocol.md). In record mode the upstream value is kept."""
    async def send2(msg):
        if msg["type"] == "http.response.start":
            hs = msg.get("headers", [])
            value = next((v for k, v in hs if k.lower() == b"date"), None) or formatdate(usegmt=True).encode()
            # all names as Tornado/nginx write them (Content-Type, Content-Length ...): the client reads headers case-sensitively (27.10: chat subscribe)
            title = lambda k: b"-".join(x.capitalize() for x in k.split(b"-"))
            msg = dict(msg, headers=[(b"Date", value)] + [(title(k), v) for k, v in hs if k.lower() != b"date"])
        await send(msg)
    return send2


class Wrapper:
    """ASGI wrapper: reads the body once (scope['mc5.body']), logs every request, forwards real hosts in record mode,
    writes the `Date:` header the way the client parses it."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        send = date_header(send)
        body, more = b"", True
        while more:
            m = await receive()
            body += m.get("body", b"")
            more = m.get("more_body", False)
        scope["mc5.body"] = body

        given = False

        async def replay():
            # the body once, then the real receive (waits for the disconnect): SSE responses (chat) listen for it
            nonlocal given
            if not given:
                given = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        req = Request(scope, replay)
        host = req.headers.get("host", "")
        line = "%s %s %s%s" % (scope["scheme"], req.method, req.url.path, "?" + req.url.query if req.url.query else "")
        # record mode: requests with a real Host (Eve arrives as `Host: eve.gameloft.com` from a second, unpatched source, documentation/client-patches.md #1,
        # and then the client uses the real Pandora/Iris names) plus the account routes of mc5proxy.ROUTES go to the real servers.
        # Keeping Eve/Pandora/Iris local in record mode was tried 24.10: the client then failed to connect.
        real = mc5proxy.route(req.url.path)
        if mc5proxy.is_upstream(host) or real:
            status, headers, content = await mc5proxy.forward(req, body, gaia.cfg["ah_port"], gaia.cfg["alert_port"], real)
            host = real or host
            log("UPSTREAM %s %s -> %d" % (host, line, status))
            return await Response(content=content, status_code=status, headers=headers)(scope, replay, send)
        status = {}

        async def send_spy(msg):
            if msg["type"] == "http.response.start":
                status["code"] = msg["status"]
            await send(msg)

        await self.app(scope, replay, send_spy)
        gaia.LOG.append({"t": round(time.time(), 3), "line": line, "host": host, "body": body[:2000].decode("latin1"),
                         "status": status.get("code")})
        del gaia.LOG[:-2000]
        log("%s -> %s" % (line[:200], status.get("code")))


async def log_only(port: int, name: str = "", cert: str = None, key: str = None, host: str = "127.0.0.1"):
    """Accept, keep open and log everything (hex in work/state/<name>.jsonl). If the first bytes are a TLS ClientHello and a certificate
    is given, TLS is set up first (the client accepts any certificate). For services whose protocol is not known yet."""
    import json as _json
    import ssl as _ssl
    path = os.path.join(os.path.dirname(gaia.cfg["store"].path), "%s.jsonl" % (name or port))

    def rec(direction, data):
        with open(path, "a") as f:
            f.write(_json.dumps({"t": round(time.time(), 3), "dir": direction, "hex": data.hex()}) + "\n")

    async def handle(reader, writer):
        log("%s %d: connection from %s" % (name, port, writer.get_extra_info("peername")))
        try:
            first = await reader.read(4096)
            if first[:1] == b"\x16" and cert:
                ctx = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
                ctx.load_cert_chain(cert, key)
                # replay the ClientHello into a TLS server stream
                loop = asyncio.get_running_loop()
                rd = asyncio.StreamReader()
                rd.feed_data(first)
                proto = asyncio.StreamReaderProtocol(rd)
                transport = writer.transport
                tls_reader = asyncio.StreamReader()
                incoming, outgoing = _ssl.MemoryBIO(), _ssl.MemoryBIO()
                sobj = ctx.wrap_bio(incoming, outgoing, server_side=True)
                incoming.write(first)
                buf = b""
                while True:
                    try:
                        sobj.do_handshake()
                        break
                    except _ssl.SSLWantReadError:
                        pass
                    out = outgoing.read()
                    if out:
                        writer.write(out)
                        await writer.drain()
                    data = await reader.read(4096)
                    if not data:
                        return
                    incoming.write(data)
                out = outgoing.read()
                if out:
                    writer.write(out)
                    await writer.drain()
                log("%s %d: TLS up" % (name, port))
                while True:
                    try:
                        plain = sobj.read(65536)
                        rec("c2s", plain)
                        log("%s %d: %r" % (name, port, plain[:160]))
                        continue
                    except _ssl.SSLWantReadError:
                        pass
                    data = await reader.read(65536)
                    if not data:
                        break
                    incoming.write(data)
            else:
                data = first
                while data:
                    rec("c2s", data)
                    log("%s %d: %r" % (name, port, data[:160]))
                    data = await reader.read(65536)
        except (ConnectionError, _ssl.SSLError) as e:
            log("%s %d: %s" % (name, port, e))
        finally:
            log("%s %d: closed" % (name, port))
            writer.close()
    return await asyncio.start_server(handle, host, port)


async def main_async(a):
    store = Store(a.state)
    tokens.key(os.path.join(os.path.dirname(a.state), "mc5_secret.bin"))
    data = a.data
    missing = [f for f in DATA_FILES if not os.path.isfile(os.path.join(data, f))]
    if missing:   # Gameloft reference data is not shipped with the code (documentation/architecture.md): say exactly what is missing and stop
        log("NO SERVER DATA in %s: missing %s (Gameloft reference data: server-data/ of the cache archive MC5-cache-6.0.12a.zip, documentation/development.md)" % (data, ", ".join(missing)))
        raise SystemExit(3)
    iap.DATA_DIR = data
    gaia.cfg.update(store=store, log=log, data_dir=data, public=a.public, public_tls=a.public_tls, alert_port=a.alert_port, ah_host=a.ah_host,
                    ah_port=a.ah_port, iris_dirs=[d for d in (os.path.join(data, "iris"), a.bald) if d and os.path.isdir(d)])
    app = Wrapper(gaia.app)
    servers = [uvicorn.Server(uvicorn.Config(app, host=a.host, port=a.port, log_level=os.environ.get("MC5_UVICORN_LOG", "warning"), lifespan="off",
                                                date_header=False))]
    if a.tls_cert:
        servers.append(uvicorn.Server(uvicorn.Config(app, host=a.host, port=a.tls_port, log_level=os.environ.get("MC5_UVICORN_LOG", "warning"), lifespan="off",
                                                     date_header=False, ssl_certfile=a.tls_cert, ssl_keyfile=a.tls_key)))
    if mc5proxy.ENABLED:
        await mc5proxy.start_relays(a.ah_port, a.alert_port, a.tls_cert, a.tls_key, log)
        log("record mode: alert/AH relayed to the real servers via %s" % mc5proxy.SOCKS)
    else:
        if a.tls_cert:
            await serve_alert(a.host, a.alert_port, a.tls_cert, a.tls_key, log)
        await AHServer(store, LiveOps(data), log).serve(a.host, a.ah_port)
        for p in (a.ah_port + 1, a.ah_port + 2):
            await log_only(p, "ah_port_%d" % p, host=a.host)
    log("listening: http %d, https %s, alert %d, ah %d; state %s; bald %s; data %s" % (a.port, a.tls_port if a.tls_cert else "-", a.alert_port, a.ah_port, a.state, a.bald if a.bald and os.path.isdir(a.bald) else "(none)", data))
    # two uvicorn servers in one loop do not stop on SIGTERM by themselves; the state is saved on every change, so just exit
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda: (store.save(), os._exit(0)))
        except NotImplementedError:     # Windows event loop: Ctrl+C simply ends the process, the state is already saved
            pass
    for s in servers:
        s.install_signal_handlers = lambda: None
    await asyncio.gather(*(s.serve() for s in servers))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=18080)
    ap.add_argument("--tls-port", type=int, default=18443)
    ap.add_argument("--tls-cert")
    ap.add_argument("--tls-key")
    ap.add_argument("--alert-port", type=int, default=33508)
    ap.add_argument("--ah-port", type=int, default=33600)
    ap.add_argument("--ah-host", default="127.0.0.1", help="controller host told to the client")
    ap.add_argument("--public", default=os.environ.get("MC5_PUBLIC", "127.0.0.1:18080"), help="http host:port told to the client")
    ap.add_argument("--public-tls", default=os.environ.get("MC5_PUBLIC_TLS", "127.0.0.1:18443"))
    ap.add_argument("--state", default=os.environ.get("MC5_STATE", os.path.join(ROOT, "work", "state", "mc5_state.json")))
    ap.add_argument("--bald", default=os.path.join(ROOT, "work", "bald6012"), help="BALD store (chapters), tools/mk_bald_store.sh")
    ap.add_argument("--data", default=os.environ.get("MC5_DATA", os.path.join(HERE, "data")),
                    help="Gameloft reference data (ah/, iris/, ads_config.json); not in the repository: server-data/ of the cache archive")
    asyncio.run(main_async(ap.parse_args()))


if __name__ == "__main__":
    main()
