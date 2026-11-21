"""Wire format of the AH game server (mc5AH_1924), see documentation/protocol.md

Handshake: JSON lines ending with `\\n`. Then binary frames: `type (1) + length (2, BE, header included) + payload`.
Strings: `u16 BE length + bytes`. Compressed bodies: `u32 BE block length + LZ4 block` (server/mc5/lz4.py).
"""
import json
import struct

from . import lz4

# client -> server
C_LOGIN = 0x01        # `33 0b`, u32 (0 on first login), strings: country, language, client_id, portal URL, federation URL, ...
C_PROFILE = 0x49      # 'I': send the profile
C_EVENTS = 0x16       # u8 kind + u8 arg: 0,0x10 cached profile -> event list; 0,0x0e/0x00 match enter/leave; 1,idx + JSON = save loadout
C_REST = 0x74         # 't': events, alias, flags, CRM config, offers
C_CREDS = 0x50        # 'P': u32 count + strings (credentials)
C_NAME = 0x0B         # JSON string {"display_name": ...}
C_LEAGUES = 0x34      # '4': league info
C_PING = 0x1C         # u32: ms since the server's previous heartbeat `1b`
C_LEVEL = 0x10        # string JSON {"level": "Venice_01_Intro", "node": ...}: a level starts
C_RESULT = 0x11       # mission result: string header "0:73300843:15:...", string JSON stats, binary tail
C_MISSION_END = 0x96  # empty: mission over, client asks the profile
C_AGE = 0x59          # u32 age, u32 gender
C_TIME = 0x52         # empty: client asks the server time (answer `4f`)
C_FLAGS = 0xAD        # three strings ("true")
C_A8 = 0xA8           # empty, after the age frame (no answer recorded)
C_48 = 0x48           # 16 bytes, after the mission result (no answer recorded)
C_OFFER = 0x41        # u32 id (FNV-1a of the offer name), u32 0 (template rentals: another value, e.g. 2): buy/claim an offer
C_CREDIT = 0x43       # u32 id (FNV-1a of the credit name), u32 0: use a credit (open a pack, claim an award)
C_VIEW_PACK = 0x81    # string pack name: the player looked at the pack (battlepacks_history.viewed = 1)
C_SETTING = 0x1A      # string key + values: profile setting/flag (killsign, core, armory_reminder, achievements ...)
C_LEVEL_DATA = 0x06   # string "<level>.lvc", u32 content release (244): answer `07`
C_TIME_SYNC = 0x1D    # empty: answer `4f` + `1e`
C_CLAN = 0x76         # u32 seq, string JSON (name, _logo, colours, _min_join_value, description): answer `77`
C_CLAIM_TASK = 0x64  # string event id + string task id (Activities): claim the task award -> 'F' id FNV-1a("activity_reward")
C_CLAIM_MILESTONE = 0x7F  # string event id + string milestone id (Activities points bar): claim the milestone award -> 'F' id FNV-1a("claim_event_milestone")
C_EVENT_INFO = 0x0C  # string JSON {"event_id": ...}: no answer known (not recorded), left unanswered
C_LEAGUES2 = 0x19    # `00 00 00 0e 00 00 00 00 00`: league request of the match menu -> `3d`, `3e`, `28` like `34`
C_BOOSTS = 0x24      # empty: refresh the permanent (VIP) boosts -> `46` {"boosts": ...}
C_KILLSIGN = 0x66    # empty: take a default kill sign -> `45` {"default_killsig_N": 1}
C_PENDING = 0x72     # u32 FNV-1a(name of a pending inventory item, e.g. levelup_3): claim it -> `46` id FNV-1a("pending_inventory_tr")
C_REFRESH = 0x21     # u8: refresh of the returning-player state (veteran flag, ratings, league, event ranks)
C_NEXT_LEVEL = 0xA3  # u8: block of the next campaign level -> `07` (same bytes as for `06`)
C_LEAVE = 0x05       # empty: leave the room -> `1f`
S_LEFT = 0x1F        # empty: answer to `05`
C_QUIET = (0x17, 0x2A, 0x2B, 0x68, 0x69, 0x67, 0x0C)   # recorded without any answer (`68` 01/00 toggles around store/offer screens, `2a` = client time, ...)
C_IAP_CLAIM = 0x44   # 4 bytes FNV-1a(entry id of the real-money store entry, e.g. captains_pay_b_b00): the payment is verified, give the goods -> `46` same id {item: total}
C_BYE = 0x14          # empty: client gives up the connection (sent after 60 s without heartbeat)
# server -> client
S_PONG = 0x1B         # heartbeat, sent by the server every second
S_TIME = 0x4F         # u32 unix time
S_CONFIG = 0x23       # '#': static server config
S_J = 0x4A            # u32 0, after the config when the profile is requested
S_PROFILE = 0x27      # "'": LZ4 JSON profile
S_FIELD = 0x46        # 'F': key id (4), float 1.0, u32 0, u32 0, LZ4 JSON {key: value}
S_EVENTS = 0x28       # '(': flag (1 = pushed, 0 = answer), LZ4 JSON list of live events
S_ALIAS = 0x70        # 'p': string
S_FLAG = 0x75         # 'u': string "&key=value"
S_CRM = 0x3F          # '?': LZ4 JSON CRM config + \0
S_OFFERS = 0x47       # 'G': u32 0, u32 length, JSON
S_LEAGUE = 0x3D       # '=': u8 1, string JSON + \n, trailing byte
S_END = 0x3E          # '>': u32 1, u8 0
S_RATING = 0x37       # '7': u32 rating, u32 rating_duel
S_EVENT_RANK = 0x55   # 'U': string JSON + \n
S_RANKS_END = 0x22    # '"'
S_LEVEL_OK = 0x10     # u32 0: answer to a level start
S_LEVEL_DATA = 0x07   # u32 0, or an encrypted level block (stored per level from the recording)
S_TIME_SYNC = 0x1E    # empty, after `4f`
S_CLAN = 0x77         # u32 seq, string JSON {"answer": "<group JSON>"}
S_FIELD_RAW = 0x45    # 'E': like 'F' but the JSON is plain: key id (4), float 1.0, u32 0, u32 0, u32 length, JSON + \n
S_XP = 0x12           # string JSON {"sp": 0, "xp": gained in this mission} after a result; {"error": -3} when no mission runs

# key ids of 'F' frames, as recorded (same for every account); the hash behind them is not known yet
FIELD_IDS = {"tournaments_sem": bytes.fromhex("19f1587f"), "active_subs": bytes.fromhex("d925332a"),
             "energy": bytes.fromhex("24989307"), "_stats_update": bytes.fromhex("593e4732"),
             # ids of the steps of a mission-result answer (names are ours): step 2 carries the inventory changes (modes after the first
             # win in one recording, energy in the other), step 3 the mission reward; so these are not key hashes
             "unlocked_modes": bytes.fromhex("ab3ee8ac"), "mission_reward": bytes.fromhex("0f6bedd4"),
             "killsign": bytes.fromhex("77faca06")}


def split_frames(buf: bytes):
    """Yield (type, payload) for every complete frame; JSON handshake lines come as type -1."""
    while buf:
        if buf[:1] == b"{":
            i = buf.find(b"\n")
            if i < 0:
                return
            yield -1, buf[:i + 1]
            buf = buf[i + 1:]
            continue
        if len(buf) < 3:
            return
        n = int.from_bytes(buf[1:3], "big")
        if n < 3 or len(buf) < n:
            return
        yield buf[0], buf[3:n]
        buf = buf[n:]


class Reader:
    """Incremental frame reader for a socket: feed() bytes, then frames() until empty."""

    def __init__(self):
        self.buf = b""

    def feed(self, data: bytes):
        self.buf += data

    def frames(self):
        while self.buf:
            if self.buf[:1] == b"{":
                i = self.buf.find(b"\n")
                if i < 0:
                    return
                line, self.buf = self.buf[:i + 1], self.buf[i + 1:]
                yield -1, line
                continue
            if len(self.buf) < 3:
                return
            n = int.from_bytes(self.buf[1:3], "big")
            if n < 3:
                raise ValueError("ah: bad frame length %d" % n)
            if len(self.buf) < n:
                return
            t, payload, self.buf = self.buf[0], self.buf[3:n], self.buf[n:]
            yield t, payload


def frame(t: int, payload: bytes = b"") -> bytes:
    n = len(payload) + 3
    if n > 0xFFFF:
        raise ValueError("ah: frame too long (%d)" % n)
    return bytes([t]) + n.to_bytes(2, "big") + payload


def s16(s) -> bytes:
    b = s.encode() if isinstance(s, str) else s
    return len(b).to_bytes(2, "big") + b


def read_s16(p: bytes, i: int):
    n = int.from_bytes(p[i:i + 2], "big")
    return p[i + 2:i + 2 + n], i + 2 + n


def jline(obj) -> bytes:
    return (json.dumps(obj, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def jcompact(obj) -> bytes:
    return json.dumps(obj, separators=(",", ":"), ensure_ascii=False).encode()


# --- server frames ---
def pong() -> bytes:
    return frame(S_PONG)


def server_time(t: int) -> bytes:
    return frame(S_TIME, struct.pack(">I", t & 0xFFFFFFFF))


def profile(obj) -> bytes:
    return frame(S_PROFILE, lz4.pack_sized(jcompact(obj)))


def field(key: str, value) -> bytes:
    head = FIELD_IDS[key] + struct.pack("<f", 1.0) + b"\0" * 8
    return frame(S_FIELD, head + lz4.pack_sized(jcompact({key: value})))


def field_raw(key: str, obj) -> bytes:
    body = jline(obj)
    return frame(S_FIELD_RAW, FIELD_IDS[key] + struct.pack("<f", 1.0) + b"\0" * 8 + len(body).to_bytes(4, "big") + body)


def changes_packed(fid: bytes, obj) -> bytes:
    """'F' keyed by an item/offer id (FNV-1a), JSON = new totals of the changed keys."""
    return frame(S_FIELD, fid + struct.pack("<f", 1.0) + b"\0" * 8 + lz4.pack_sized(jcompact(obj)))


def item_raw(reason: bytes, item: bytes, obj) -> bytes:
    """'E' keyed by a reason id with the item id in the first u32 after the float (recorded weapon_assemble / weapon_upgrade:
    `45 0cf1fb56 1.0 4f6e7651 0 {"AR05":1}`)."""
    body = jline(obj)
    return frame(S_FIELD_RAW, reason + struct.pack("<f", 1.0) + item + b"\0" * 4 + len(body).to_bytes(4, "big") + body)


def refused(fid: bytes, status: int = 4) -> bytes:
    """'E' with a status and no body (recorded refusal: status 4 when the offer cannot be paid)."""
    return frame(S_FIELD_RAW, fid + struct.pack("<f", 1.0) + b"\0\0\0\0" + struct.pack(">I", status))


def field_packed(key: str, obj) -> bytes:
    """'F' with a JSON that is not wrapped in {key: ...} (unlocked_modes)."""
    return frame(S_FIELD, FIELD_IDS[key] + struct.pack("<f", 1.0) + b"\0" * 8 + lz4.pack_sized(jcompact(obj)))


def events(lst, pushed: bool) -> bytes:
    return frame(S_EVENTS, bytes([1 if pushed else 0]) + lz4.pack_sized(jcompact(lst)))


def crm(obj) -> bytes:
    return frame(S_CRM, lz4.pack_sized(jcompact(obj) + b"\0"))


def offers(obj) -> bytes:
    body = jline(obj)
    return frame(S_OFFERS, b"\0\0\0\0" + len(body).to_bytes(4, "big") + body)


def league(obj, tail: int) -> bytes:
    return frame(S_LEAGUE, b"\x01" + s16(jline(obj)) + bytes([tail]))


def end() -> bytes:
    return frame(S_END, struct.pack(">IB", 1, 0))


def rating(r: int, duel: int) -> bytes:
    return frame(S_RATING, struct.pack(">II", r, duel))


def event_rank(obj) -> bytes:
    return frame(S_EVENT_RANK, s16(jline(obj)))


def parse_login(p: bytes) -> dict:
    """`01` payload: version (2), install value (u32), then strings (see documentation/protocol.md)."""
    out = {"version": p[:2].hex(), "install": int.from_bytes(p[2:6], "big")}
    i, names = 6, ["country", "language", "client_id", "portal", "federation"]
    for name in names:
        s, i = read_s16(p, i)
        out[name] = s.decode("latin1")
    if i < len(p):
        i += 1  # 01
        s, i = read_s16(p, i)
        out["device_id"] = s.decode("latin1")
        s, i = read_s16(p, i)
        out["model"] = s.decode("latin1")
    return out
