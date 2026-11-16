"""Gaia chat (`groupchat`, ChatLibv2) from the recording work/real/trace_full1 (documentation/protocol.md).

  POST /chat/channels/<name>/subscribe  (language, access_token)  -> cmd_url / listen_url / https_listen_url
  POST /chat/rooms/<room id>/subscribe                            -> the same for a match/clan room
  GET  /v1/chat/channels/<name>.<lang>?game&memberid&language     -> SSE: room_info, history (message*), then live messages,
  GET  /v1/chat/rooms/<room id>?...                                  room_info every 30 s as a keep-alive
  POST /v1/chat/channels/<name>.<lang> | /v1/chat/rooms/<id>      -> send (_* attributes, msg, user, access_token) -> {"msg": {...}}
Messages are kept in the store (data["chat"][key]); listeners are the connected clients of this process.
"""
import asyncio
import json
import time
from typing import Dict, List

HISTORY = 100          # messages replayed on connect (the real one replayed about 100 of the global channel)
KEEPALIVE = 30         # seconds between room_info events (recording: 30 s)
INFO = {"motd": "", "notify_activity": False, "historisable_type": ["message", "game"], "receiver_filter": False}
QUOTA = {"send_quota": 20, "quota_period": 60}


def fmt(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(t))


class Hub:
    def __init__(self, store):
        self.store = store
        self.listeners: Dict[str, List[asyncio.Queue]] = {}

    def history(self, key: str) -> list:
        return self.store.data.setdefault("chat", {}).setdefault(key, [])

    def room_info(self, key: str) -> dict:
        # the real channel counted all connected players; here: our listeners (at least the asking one)
        return dict(INFO, type="room_info", num_members=max(1, len(self.listeners.get(key, []))), reconnect_key="disabled", **QUOTA)

    def post(self, key: str, attrs: dict, text: str, sender: dict) -> dict:
        """Store and fan out a message; the field order is the recorded one."""
        h = self.history(key)
        nxt = (int(h[-1]["id"], 16) + 1) if h else 0x100
        msg = {"type": "message", "moderator": False}
        msg.update(attrs)
        msg.update(sent=fmt(time.time()), msg=text, sender=sender, id="%x" % nxt)
        h.append(msg)
        del h[:-HISTORY]
        self.store.save()
        for q in self.listeners.get(key, []):
            q.put_nowait(msg)
        return msg

    async def listen(self, key: str):
        """SSE body: one JSON event per chunk, `\\n`-terminated (as Tornado wrote it)."""
        q: asyncio.Queue = asyncio.Queue()
        self.listeners.setdefault(key, []).append(q)
        try:
            yield json.dumps(self.room_info(key), separators=(",", ":")) + "\n"
            for m in list(self.history(key)):
                yield json.dumps(m, separators=(",", ":")) + "\n"
            while True:
                try:
                    ev = await asyncio.wait_for(q.get(), KEEPALIVE)
                except asyncio.TimeoutError:
                    ev = self.room_info(key)
                yield json.dumps(ev, separators=(",", ":")) + "\n"
        finally:
            self.listeners[key].remove(q)
