"""Gaia `alert` socket (TLS): `GET /alerts/me?...content_type=event-stream` -> SSE stream kept open (documentation/protocol.md).
No events yet (the recordings show none in 10 minutes)."""
import asyncio
import ssl
from email.utils import formatdate

HEAD = ("HTTP/1.1 200 OK\r\nServer: mc5-local\r\nContent-Type: text/event-stream\r\nDate: %s\r\nAccess-Control-Allow-Origin: *\r\n"
        "Access-Control-Allow-Methods: *\r\nAccess-Control-Expose-Headers: Date\r\nVary: Accept-Encoding\r\nTransfer-Encoding: chunked\r\n\r\n")


async def serve(host: str, port: int, cert: str, key: str, log):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(cert, key)

    async def handle(reader, writer):
        try:
            req = await reader.readuntil(b"\r\n\r\n")
            line = req.split(b"\r\n", 1)[0].decode("latin1")
            log("alert: %s" % line[:120])
            writer.write((HEAD % formatdate(usegmt=True)).encode())   # Date: as the real (Tornado) one
            await writer.drain()
            while await reader.read(4096):
                pass
        except (asyncio.IncompleteReadError, ConnectionError, ssl.SSLError) as e:
            log("alert: %s" % e)
        finally:
            writer.close()

    return await asyncio.start_server(handle, host, port, ssl=ctx)
