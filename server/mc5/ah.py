"""AH game server (mc5AH_1924): the player-profile server the client connects to after Federation `sessions` (documentation/protocol.md).

Behaviour (not replay): the profile of every account lives in the store; a new player gets the template profile with his own
`created`, `deviceId`, `country`; fields the server hands out (alias, tournament participations, subscriptions, offers, leagues,
ratings, display name) are written into the profile, so the next login returns them inside the full profile, as the real server did.
Unknown client frames are logged in hex and left unanswered.
"""

import asyncio
import copy
import hashlib
import json
import os
import random
import struct
import time

from . import ahproto as P
from . import iap, lz4, social, tokens
from .economy import fnv1a as P_fnv
from .liveops import LiveOps, fmt

HEARTBEAT = 1.0
START_TIME_EPOCH_MIN = 12891700  # current_mission.start_time: recorded 16989567 at 23:07Z 2026-10-24 = minutes since the epoch minus this
RETURNING_WAIT = 0.15  # after `01` the client sends `I` at once if it wants the profile; otherwise the "returning" answer follows


MODES = ("assault", "battleroyale", "recon", "zmbmode", "zombieai")  # opened by the first campaign win (`_inventory.<mode>` = 1)


def result_objectives(head: str) -> dict:
    """Header "0:73300843:N:" + triples "type:id:value": type 0 hash:count, type 1 objective index:done, type 2 hash:1 (trace_full1).
    progress keeps the bonus objectives only (both recorded missions: objective2/objective3, objective 1 is not stored)."""
    tok = [t for t in head.split(":") if t != ""]
    out = {}
    for j in range(3, len(tok) - 2, 3):
        if tok[j] == "1" and tok[j + 1].isdigit() and int(tok[j + 1]) >= 2 and tok[j + 2] != "0":
            out["objective%s" % tok[j + 1]] = True
    return out


def apply_result(acc: dict, p: bytes):
    """Apply a mission result (`11` payload) to the profile the way the real AH did (profiles before/after both results in trace_full1):
    statistics.sp.* summed (killstreak.* = max), _inventory.xp += sum(xp.*) + 1 (= the `12` answer), _inventory_shadow.upd_xp,
    ads_pending_item rwd_xp (double xp for an ad), progress entry with the bonus objectives, highest_unlocked_mission, modes on the
    first campaign win, current_mission -> null.
    No running mission (current_mission is null: the client re-sends `11` after a reconnect, or the result is from another install)
    -> None; the real server answered such a result with `12 {"error": -3}`. Otherwise {"xp", "first", "modes", "level"}.
    Used by the AH server and by tools/import_from_trace.py."""
    head, i = P.read_s16(p, 0)
    stats_raw, i = P.read_s16(p, i)
    stats = json.loads(stats_raw)
    prof = acc["profile"]
    cur = prof.get("current_mission")
    acc.setdefault("ah", {}).setdefault("results", []).append(
        {"t": time.time(), "head": head.decode("latin1"), "stats": stats, "tail": p[i:].hex(), "level": (cur or {}).get("level"), "applied": bool(cur)}
    )
    if not cur:
        return None
    sp = prof.setdefault("statistics", {}).setdefault("sp", {})
    for k, v in stats.items():
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            sp[k] = max(sp.get(k, 0), v) if k.startswith("killstreak.") else sp.get(k, 0) + v
    for k in ("kill.explosives", "kill.melees"):
        sp.setdefault(k, 0)
    gained = sum(v for k, v in stats.items() if k.startswith("xp.") and isinstance(v, (int, float))) + 1  # 893+1, 1337+1, 983+1
    inv = prof.setdefault("_inventory", {})
    shadow = prof.setdefault("_inventory_shadow", {})
    inv["xp"] = inv.get("xp", 0) + gained
    shadow["upd_xp"] = inv["xp"]
    prof["ads_pending_item"] = {"credit": {"name": "rwd_xp", "qty": gained}}
    level = cur.get("level")
    progress = prof.get("progress") or []
    entry = next((e for e in progress if e.get("level") == level), None)
    first = entry is None
    if first:
        entry = {"level": level, "node": cur.get("node")}
        progress.append(entry)
    entry.update(result_objectives(head.decode("latin1")))
    prof["progress"] = progress
    prof["highest_unlocked_mission"] = 200 + len(progress)  # recorded 302 (new) -> 201 -> 202; rule from two points, unchecked further
    modes = None
    if stats.get("game.campaign.wins") and not all(inv.get(m) for m in MODES):
        modes = {m: 1 for m in MODES}
        inv.update(modes)
        shadow["upd_unlocked_zones"] = 1
    prof["current_mission"] = None
    return {"xp": gained, "first": first, "modes": modes, "level": level}


class AHServer:
    def __init__(self, store, liveops: LiveOps, log):
        self.store, self.lo, self.log = store, liveops, log
        self.conns = 0

    async def serve(self, host: str, port: int):
        return await asyncio.start_server(self.handle, host, port)

    # ------------------------------------------------------------------ connection
    async def handle(self, reader, writer):
        self.conns += 1
        cid = self.conns
        c = Conn(self, cid, writer)
        self.log("ah[%d]: connection from %s" % (cid, writer.get_extra_info("peername")))
        c.send_json({"action": "create connection", "success": "True", "nonce": "%032x" % random.getrandbits(128)})
        rd = P.Reader()
        try:
            while True:
                data = await reader.read(65536)
                if not data:
                    break
                rd.feed(data)
                for t, payload in rd.frames():
                    await c.on_frame(t, payload)
                await writer.drain()
        except (ConnectionError, ValueError) as e:
            self.log("ah[%d]: %s" % (cid, e))
        finally:
            c.close()
            self.log("ah[%d]: closed (%d pings)" % (cid, c.pings))
            writer.close()


class Conn:
    def __init__(self, srv: AHServer, cid: int, writer):
        self.srv, self.cid, self.w = srv, cid, writer
        self.acc = None
        self.login = None
        self.pending = None
        self.heartbeat = None
        self.leagues_sent = False
        self.pings = 0

    def log(self, msg):
        self.srv.log("ah[%d]: %s" % (self.cid, msg))

    def send(self, data: bytes):
        self.w.write(data)

    def send_json(self, obj):
        self.w.write(P.jline(obj))

    async def beat(self):
        """Heartbeat is driven by the server: `1b` every second, the client answers `1c` (recorded: ~1000 ms values).
        Without it the client sends `14` after 60 s and logs in again."""
        while True:
            await asyncio.sleep(HEARTBEAT)
            self.send(P.pong())
            await self.w.drain()

    def close(self):
        if self.heartbeat:
            self.heartbeat.cancel()
        if self.pending:
            self.pending.cancel()
        if self.acc:
            self.srv.store.save()

    # ------------------------------------------------------------------ dispatch
    async def on_frame(self, t: int, p: bytes):
        if t == -1:
            return self.on_handshake(json.loads(p))
        if self.acc is None:
            self.log("frame %02x before the handshake, ignored" % t)
            return
        if t == P.C_PING:  # answer to our heartbeat: ms since our previous `1b`
            self.pings += 1
            return
        self.record(t, p)
        name = {
            P.C_LOGIN: "login",
            P.C_PROFILE: "profile",
            P.C_EVENTS: "events",
            P.C_REST: "rest",
            P.C_CREDS: "creds",
            P.C_NAME: "name",
            P.C_LEAGUES: "leagues",
            P.C_LEVEL: "level",
            P.C_RESULT: "result",
            P.C_MISSION_END: "mission_end",
            P.C_AGE: "age",
            P.C_TIME: "time",
            P.C_FLAGS: "flags",
            P.C_A8: "ignore",
            P.C_48: "shadow",
            P.C_LEVEL_DATA: "level_data",
            P.C_TIME_SYNC: "time_sync",
            P.C_CLAN: "clan",
            P.C_OFFER: "offer",
            P.C_CREDIT: "credit",
            P.C_VIEW_PACK: "view_pack",
            P.C_SETTING: "setting",
            P.C_CLAIM_TASK: "claim_task",
            P.C_CLAIM_MILESTONE: "claim_milestone",
            P.C_BOOSTS: "boosts",
            P.C_IAP_CLAIM: "iap_claim",
            P.C_KILLSIGN: "killsign",
            P.C_PENDING: "pending",
            P.C_REFRESH: "refresh",
            P.C_NEXT_LEVEL: "next_level",
            P.C_LEAVE: "leave",
            P.C_LEAGUES2: "leagues",
        }.get(t) or ("ignore" if t in P.C_QUIET else None)
        if name is None:
            self.log("unknown frame %02x len %d: %s" % (t, len(p), p[:120].hex()))
            return
        self.log("<- %s %s" % (name, p[:80].hex() if t not in (P.C_LOGIN, P.C_NAME) else ""))
        return getattr(self, "on_" + name)(p)

    def record(self, t: int, p: bytes):
        """Every client frame (except pings) in full: work/state/ah_frames.jsonl. Frames the server does not know yet are the
        spec for the next steps (mission results, progress) and must not be lost."""
        path = os.path.join(os.path.dirname(self.srv.store.path), "ah_frames.jsonl")
        with open(path, "a") as f:
            f.write(
                json.dumps(
                    {
                        "t": round(time.time(), 3),
                        "conn": self.cid,
                        "fed_id": self.acc["fed_id"] if self.acc else None,
                        "type": "%02x" % t,
                        "len": len(p),
                        "hex": p.hex(),
                    }
                )
                + "\n"
            )

    # ------------------------------------------------------------------ handshake
    def on_handshake(self, msg: dict):
        """c2s {"access_token": <encrypted lobby token>, "action": "connect game", "room_id", "username": <credential>}."""
        tok = tokens.decrypt(msg.get("access_token", ""))
        info = tokens.parse(tok) if tok else None
        room = self.srv.store.room(msg.get("room_id", ""))
        acc = self.srv.store.by_fed_id(info["fed_id"]) if info else None
        why = (
            "bad token"
            if not info
            else "expired token"
            if info["expiry"] < time.time()
            else "unknown room"
            if not room
            else "room of another player"
            if room["fed_id"] != info["fed_id"]
            else "credential mismatch"
            if acc is None or acc["credential"] != msg.get("username")
            else ""
        )
        if why:
            self.log("handshake refused: " + why)
            return self.send_json({"success": False, "action": "connect game", "error": why})
        self.acc = acc
        self.device_id = info["device_id"]
        self.send_json({"slot": "%x" % random.randint(0x1000, 0xFFFF), "success": True, "action": "connect game"})
        self.log("handshake ok: fed_id %s room %s" % (acc["fed_id"], msg["room_id"]))

    # ------------------------------------------------------------------ profile model
    def state(self) -> dict:
        return self.acc.setdefault("ah", {})

    def profile(self, login: dict) -> dict:
        prof = self.acc.get("profile")
        if prof is None:
            prof = copy.deepcopy(self.srv.lo.new_profile)
            prof["created"] = fmt(time.time())
            prof["deviceId"] = login.get("device_id") or self.device_id
            prof["country"] = prof["_initial_country"] = login.get("country") or prof.get("country")
            prof["client_version"] = (login.get("client_id") or "::").split(":")[2] or prof.get("client_version")
            self.acc["profile"] = prof
            self.state()["new"] = True
        self.srv.lo.economy.full_energy(prof)
        return prof

    def participations(self, events: list) -> list:
        """tournaments_sem: one entry per running activities event (rank -1, score 0, a zero per task)."""
        prof = self.acc["profile"]
        have = {e["event_id"]: e for e in prof.get("tournaments_sem") or [] if isinstance(e, dict)}
        out = []
        for ev in self.srv.lo.activity_events(events):
            out.append(
                have.get(ev["id"])
                or {"event_id": ev["id"], "event_rank": -1, "event_score": 0, "initial_activities_stats": self.srv.lo.initial_stats(ev, prof)}
            )
        prof["tournaments_sem"] = out
        return out

    # ------------------------------------------------------------------ client requests
    def on_login(self, p: bytes):
        self.login = P.parse_login(p)
        self.log("login %s" % json.dumps({k: v for k, v in self.login.items() if k not in ("portal", "federation")}))
        self.send(P.server_time(int(time.time())))
        if not self.heartbeat:
            self.heartbeat = asyncio.ensure_future(self.beat())
        self.send(P.frame(P.S_CONFIG, self.srv.lo.config))
        self.profile(self.login)
        self.pending = asyncio.ensure_future(self._returning_later())

    async def _returning_later(self):
        await asyncio.sleep(RETURNING_WAIT)
        self.pending = None
        self.returning()
        await self.w.drain()

    def returning(self):
        """Login without `I` (client has the profile cached): ratings, league, event ranks, end, pushed event list."""
        prof, now = self.acc["profile"], time.time()
        events = self.srv.lo.events(now)
        self.send(P.field_raw("energy", {"energy": prof["_inventory"]["energy"]}))  # as the real server at login; the cached value may be stale
        self.send(P.rating(prof.get("rating") or 800, prof.get("rating_duel") or 800))
        self.send_league(final_only=True)
        for part in self.participations(events):
            self.send(P.event_rank(dict(credential=self.acc["credential"], **part)))
        self.send(P.frame(P.S_RANKS_END))
        self.send(P.end())
        self.send(P.events(events, pushed=True))

    def on_profile(self, p: bytes):
        """`I`: the full profile. A new player first gets his tournament participations as field updates."""
        if self.pending:
            self.pending.cancel()
            self.pending = None
        events = self.srv.lo.events()
        self.send(P.frame(P.S_J, b"\0\0\0\0"))
        self.zones("profile")
        st = self.state()
        if st.pop("new", False):
            parts = self.participations(events)
            for part in parts:
                self.send(P.field("tournaments_sem", part))
            self.send(P.events(events, pushed=True))
            self.send(P.profile(self.acc["profile"]))
        else:
            self.participations(events)
            self.send(P.profile(self.acc["profile"]))
            self.send(P.end())

    def on_events(self, p: bytes):
        """`16`: u8 kind + u8 arg (all recordings, documentation/protocol.md).
        kind 0: client state; arg 0x10 (profile cached, menu) -> the event list, as the real server; 0x0e / 0x00 (around entering
        and leaving a match) -> no answer.
        kind 1: arg = loadout index, then a string with the loadout JSON -> inventory.loadouts[index], current_weapon = primary
        weapon, current_skill = skill (next real profile had exactly this); the real server sent no answer."""
        kind, arg = p[0] if p else 0, p[1] if len(p) > 1 else 0
        if kind == 1:
            s, _ = P.read_s16(p, 2)
            lo = json.loads(s)
            inv = self.acc["profile"].setdefault("inventory", {})
            slots = inv.get("loadouts") or []
            while len(slots) <= arg:
                slots.append(None)
            slots[arg] = lo
            inv["loadouts"] = slots
            if (lo.get("primary") or {}).get("weapon"):
                inv["current_weapon"] = lo["primary"]["weapon"]
            if lo.get("skill"):
                inv["current_skill"] = lo["skill"]
            self.log("loadout %d saved: %s / %s" % (arg, inv.get("current_skill"), inv.get("current_weapon")))
            return self.srv.store.save()
        self.state()["client_state"] = arg
        if arg == 0x10:
            self.send(P.events(self.srv.lo.events(), pushed=False))

    def on_rest(self, p: bytes):
        """`t`: what the player does not have yet: participations, alias, veteran flag, subscriptions, CRM config, offers."""
        prof, st, now = self.acc["profile"], self.state(), time.time()
        events = self.srv.lo.events(now)
        first = not st.get("rest_done")
        if first:
            for part in self.participations(events):
                self.send(P.field("tournaments_sem", part))
        self.send(P.events(events, pushed=not first))
        if not prof.get("alias"):
            prof["alias"] = "%05x" % random.getrandbits(20)
            self.send(P.frame(P.S_ALIAS, P.s16(prof["alias"])))
        self.send(P.frame(P.S_FLAG, P.s16("&_veteran=" + ("true" if prof.get("is_veteran") else "false"))))
        if first:
            prof["active_subs"] = {"fake_sub_expire": 0, "fake_sub_id": "", "switch_processed": True}
            self.send(P.field("active_subs", prof["active_subs"]))
        crm = self.srv.lo.crm(events, now, prof)
        digest = hashlib.sha1(P.jcompact(crm)).hexdigest()
        if st.get("crm_hash") != digest:  # sent again whenever the content changes (expiry every day, server settings)
            self.send(P.crm(crm))
            st["crm_hash"] = digest
        offers = prof.get("daily_offers")
        if not offers or offers.get("expiry", 0) * 60 <= now:
            prof["daily_offers"] = self.srv.lo.daily_offers(now)
            self.send(P.offers(prof["daily_offers"]))
        if first:
            self.send(P.events(events, pushed=False))
        st["rest_done"] = True
        self.srv.store.save()

    def on_creds(self, p: bytes):
        n = int.from_bytes(p[:4], "big")
        creds, i = [], 4
        for _ in range(n):
            s, i = P.read_s16(p, i)
            creds.append(s.decode("latin1"))
        self.state()["creds"] = creds

    def on_name(self, p: bytes):
        s, _ = P.read_s16(p, 0)
        try:
            name = json.loads(s).get("display_name")
        except ValueError:
            return self.log("bad name frame %r" % s)
        if name:
            self.acc["profile"].setdefault("osiris_info", {})["display_name"] = name
            self.srv.store.save()

    def on_leagues(self, p: bytes):
        if not self.leagues_sent:
            self.send_league(final_only=False)
            self.send(P.end())
        self.send(P.events(self.srv.lo.events(), pushed=False))

    # ---------------------------------------------------------------- campaign (answers as recorded from the real AH, work/real/trace_mission1)
    def on_ignore(self, p: bytes):
        """`a8`, `48`: the real server sent nothing back (frames are kept in ah_frames.jsonl)."""

    def on_time(self, p: bytes):
        self.send(P.server_time(int(time.time())))

    def on_age(self, p: bytes):
        age, gender = int.from_bytes(p[:4], "big"), int.from_bytes(p[4:8], "big")
        prof = self.acc["profile"]
        prof["age"] = age
        prof["gender"] = {1: "male", 2: "female"}.get(gender, None)
        prof["birthdate"] = fmt(time.time() - age * 365.25 * 86400)
        self.srv.store.save()

    def on_flags(self, p: bytes):
        """Three strings ("true"): seen together with menu_tutorials [false, false, false] + menu_tutorials_skipped true in the profile."""
        vals, i = [], 0
        while i + 2 <= len(p):
            s, i = P.read_s16(p, i)
            vals.append(s.decode("latin1"))
        prof = self.acc["profile"]
        prof["menu_tutorials"] = [False] * len(vals)
        prof["menu_tutorials_skipped"] = all(v == "true" for v in vals)
        self.srv.store.save()

    def on_level(self, p: bytes):
        """Level start: the server records current_mission (with the player's boost factors) and the energy time, answers `45 energy` + `10`.
        The real server charged the mission cost here (Tokyo_01: +10 min) and gave it back on a win; energy is kept full instead (Economy.full_energy)."""
        s, _ = P.read_s16(p, 0)
        info = json.loads(s)
        prof, now = self.acc["profile"], time.time()
        inv = prof.setdefault("_inventory", {})
        boosts = inv.get("boosts") or {}
        factor = lambda k, d: (boosts.get(k) or [{}])[0].get("factor", d)
        energy = self.srv.lo.economy.full_energy(prof)
        prof["current_mission"] = {
            "boosts": {"dbmsrw": factor("dbmsrw", 0.0), "ws": factor("ws4", 1.0), "xp": factor("xp4", 1.0)},
            "level": info.get("level"),
            "node": info.get("node"),
            "start_time": int(now // 60) - START_TIME_EPOCH_MIN,
        }
        self.send(P.field_raw("energy", {"energy": energy}))
        self.send(P.frame(P.S_LEVEL_OK, b"\0\0\0\0"))
        self.srv.store.save()

    def on_mission_end(self, p: bytes):
        self.send(P.profile(self.acc["profile"]))

    def on_result(self, p: bytes):
        """Mission result: header string, JSON stats, binary tail. Recorded answer: `45 _stats_update`, `46` inventory changes
        (modes on the first win), `45` mission reward, `12` {sp, xp gained in this mission}, then CRM and the event list.
        Without a running mission: `12 {"error": -3}` only (as the real server, trace_mission1)."""
        prof = self.acc["profile"]
        info = apply_result(self.acc, p)
        if info is None:
            self.log("result without a running mission: refused (-3)")
            self.send(P.frame(P.S_XP, P.s16(P.jline({"error": -3}))))
            return self.srv.store.save()
        kind = "sp_first_time" if info["first"] else "sp_replay"
        self.send(P.field_raw("_stats_update", {"_stats_update": {"distance_run": 0}}))  # distance source unknown; 0 keeps the shape
        step = dict(info["modes"] or {}, **self.zones("result"))  # endmission step: modes on the first win, opened chapters (zones)
        if step:
            self.send(P.field_packed("unlocked_modes", step))
        reward = self.srv.lo.economy.mission_reward(prof, kind)
        self.log("mission %s (%s) xp +%d reward %s" % (info["level"], kind, info["xp"], json.dumps(reward)))
        self.send(P.field_raw("mission_reward", reward))
        self.send(P.frame(P.S_XP, P.s16(P.jline({"sp": 0, "xp": info["xp"]}))))
        events = self.srv.lo.events()
        self.send(P.crm(self.srv.lo.crm(events, prof=self.acc["profile"])))
        self.send(P.events(events, pushed=False))
        self.srv.store.save()

    # ---------------------------------------------------------------- economy (server/mc5/economy.py)
    def on_offer(self, p: bytes):
        fid = p[:4]
        eco = self.srv.lo.economy
        name = eco.by_id.get(fid)
        if not name:
            self.log("offer %s: unknown id" % fid.hex())
            return self.send(P.refused(fid))
        if name in eco.rentals:  # TRY IT: instance of a template rental offer (the u32 after the id is 2 here, 0 for plain offers)
            status, changes = eco.rent(self.acc["profile"], name)
            self.log("rent %s (arg %s) -> status %d %s" % (name, p[4:8].hex(), status, json.dumps(changes)[:200]))
            if status:
                return self.send(P.refused(fid, status))
            self.send(P.changes_packed(fid, changes))
            return self.srv.store.save()
        status, changes, opened = eco.buy_offer(self.acc["profile"], name)
        self.log("offer %s -> status %d %s" % (name, status, json.dumps(changes)[:200]))
        if status:
            return self.send(P.refused(fid, status))
        if name.startswith("skip_unlock_zone"):  # bought skip of a chapter's optional conditions: the zone opens now (client handler reads unlocked_zones)
            changes.update(self.zones("skip"))
        self.send(P.changes_packed(fid, changes))
        for credit in opened:  # autoactivate (ultimate_battlepack): opened at once, its own id
            got = eco.use_credit(self.acc["profile"], credit)
            self.send(P.changes_packed(P_fnv(credit), got))
        self.srv.store.save()

    def zones(self, why: str) -> dict:
        """Open the next campaign zones whose conditions hold (liveops.zone_unlocks); -> the inventory changes."""
        prof = self.acc["profile"]
        ch = self.srv.lo.zone_unlocks(prof)
        if ch:
            self.log("zones (%s): %s; level %d, stars %d" % (why, json.dumps(ch), self.srv.lo.player_level(prof), self.srv.lo.service_stars(prof)))
            self.srv.store.save()
        return ch

    def on_credit(self, p: bytes):
        fid = p[:4]
        eco = self.srv.lo.economy
        name = eco.by_id.get(fid)
        if not name:
            self.log("credit %s: unknown id" % fid.hex())
            return
        changes = eco.use_credit(self.acc["profile"], name)
        self.log("credit %s -> %s" % (name, json.dumps(changes)[:200]))
        self.send(P.changes_packed(fid, changes))
        self.srv.store.save()

    def on_view_pack(self, p: bytes):
        s, _ = P.read_s16(p, 0)
        self.srv.lo.economy.view_pack(self.acc["profile"], s.decode("latin1"))
        self.srv.store.save()

    def on_setting(self, p: bytes):
        """`1a` string key + raw values: kept in the profile (no answer in most recordings)."""
        key, i = P.read_s16(p, 0)
        self.acc["profile"].setdefault("_settings", {})[key.decode("latin1")] = p[i:].hex()
        self.srv.store.save()

    def on_claim_task(self, p: bytes):
        """`64` string event id + string task id (condition id of the Activities task, e.g. GEN_daily_bonus_01): claim the task award.
        Not in any recording (account banned before it could be recorded). Built from the client (libMC5 0x5fef4c): the change with
        id FNV-1a("activity_reward") carries {"tournaments_sem": {event_id, claimed_activities: [task indexes]}}; the ids of all
        recorded `45`/`46` frames are FNV-1a of such reason names (general_stat_update, endmission_rwd_sp, energy_update ...).
        The award (task `award` list) is added to the inventory, its new totals go in the same JSON, points to event_score."""
        ev_id, i = P.read_s16(p, 0)
        task_id, _ = P.read_s16(p, i)
        ev_id, task_id = ev_id.decode("latin1"), task_id.decode("latin1")
        prof = self.acc["profile"]
        ev = next((e for e in self.srv.lo.events() if e["id"] == ev_id), None)
        tasks = (ev or {}).get("_template", {}).get("event_tuning", {}).get("_tasks", {}).get("value", [])
        idx = next((k for k, t in enumerate(tasks) if any(c.get("id") == task_id for c in t["sub"]["condition"]["value"].values())), None)
        part = next((e for e in prof.get("tournaments_sem") or [] if isinstance(e, dict) and e.get("event_id") == ev_id), None)
        if idx is None or part is None:
            return self.log("claim %s/%s: unknown event or task" % (ev_id, task_id))
        changes = {}
        claimed = part.setdefault("claimed_activities", [])
        if idx not in claimed:  # a repeated `64` (the client re-sends until answered) gets the same answer, no second award
            claimed.append(idx)
            sub = tasks[idx]["sub"]
            for award in sub["award"]["value"]:
                for item, a in award["value"].items():
                    self.srv.lo.economy.grant(prof, a.get("id") or item, int(a.get("value", 0)), changes)
            part["event_score"] = part.get("event_score", 0) + int(sub.get("points", {}).get("value", 0))
        else:
            inv = prof.get("_inventory") or {}
            for award in tasks[idx]["sub"]["award"]["value"]:
                for item, a in award["value"].items():
                    k = a.get("id") or item
                    changes[k] = inv.get(k, 0)
        changes["tournaments_sem"] = part
        self.log("claim %s task %d (%s) -> %s" % (ev["name"], idx, task_id, json.dumps(changes)[:200]))
        self.send(P.changes_packed(P_fnv("activity_reward"), changes))
        self.srv.store.save()

    def on_claim_milestone(self, p: bytes):
        """`7f` string event id + string milestone id (the points bar of Challenges, seen from a real client press 25.10; no recording of the answer).
        Same shape as the task claim: award from the event's `milestones[].sub.award`, needs `event_score >= condition`, one claim per milestone
        (`claimed_milestones` in the participation); answer `46` id FNV-1a("claim_event_milestone") = {<award totals>, "tournaments_sem": <participation>}."""
        ev_id, i = P.read_s16(p, 0)
        ms_id, _ = P.read_s16(p, i)
        ev_id, ms_id = ev_id.decode("latin1"), ms_id.decode("latin1")
        prof = self.acc["profile"]
        ev = next((e for e in self.srv.lo.events() if e["id"] == ev_id), None)
        ms = next(
            (
                m["sub"]
                for m in (ev or {}).get("_template", {}).get("milestones", {}).get("value", [])
                if m["sub"]["_milestone_id"]["value"]["text_plain"] == ms_id
            ),
            None,
        )
        part = next((e for e in prof.get("tournaments_sem") or [] if isinstance(e, dict) and e.get("event_id") == ev_id), None)
        if ms is None or part is None:
            return self.log("milestone %s/%s: unknown event or milestone" % (ev_id, ms_id))
        if part.get("event_score", 0) < ms["condition"]["value"]:
            return self.log("milestone %s: %s points needed, %s have" % (ms_id, ms["condition"]["value"], part.get("event_score", 0)))
        changes = {}
        claimed = part.setdefault("claimed_milestones", [])
        eco = self.srv.lo.economy
        for award in ms["award"]["value"]:
            for item, a in award["value"].items():
                k = a.get("id") or item
                if ms_id not in claimed:
                    eco.grant(prof, k, int(a.get("value", 0)), changes)
                else:
                    changes[k] = (prof.get("_inventory") or {}).get(k, 0)
        if ms_id not in claimed:
            claimed.append(ms_id)
        changes.update({"_sem_event_id": ev_id, "_sem_milestone_id": ms_id, "success": True})  # fields the client handler reads (libMC5 0x5fb6e4..0x5fb780)
        changes["tournaments_sem"] = part
        self.log("milestone %s (%s points) -> %s" % (ms_id, ms["condition"]["value"], json.dumps(changes)[:200]))
        self.send(P.changes_packed(P_fnv("claim_event_milestone"), changes))
        self.srv.store.save()

    # ---------------------------------------------------------------- small frames (answers as recorded in trace_full1; documentation/protocol.md)
    def on_iap_claim(self, p: bytes):
        """`44` <FNV-1a(entry id)>: after the e-commerce server confirmed the payment (mc5.Store + `action=transaction`) the client asks the game server for the goods;
        the answer is `46` with the same id and the new totals (credits, vip_points ...), like a bought offer. No paid order -> refused like an offer (`45` status 4)."""
        fid = p[:4]
        changes = iap.claim(self.srv.store, self.acc, fid)
        self.log("iap claim %s -> %s" % (fid.hex(), json.dumps(changes)))
        if changes is None:
            return self.send(P.refused(fid, 4))
        self.send(P.changes_packed(fid, changes))

    def on_boosts(self, p: bytes):
        """`24`: the client refreshes the permanent (VIP) boosts at every login. The answer `46` id 50c8eec5 {"boosts": <all boosts>} (the id is not FNV-1a of a name found
        in the client) is a "boosts granted" event: the client shows the "Reached VIP level N" window with it (27.10, OnePlus: with the answer at every login the
        window came at every login; without the answer it did not). The real server answered the first login of a new player (recorded); later logins are not recorded,
        so the answer is sent only when the permanent boosts differ from what the client was last told (`acc.ah.boosts_sig`)."""
        prof, now = self.acc["profile"], int(time.time())
        boosts = prof.setdefault("_inventory", {}).setdefault("boosts", {})
        perm = sorted((stat, b.get("from_credit", ""), b.get("factor")) for stat, lst in boosts.items() for b in lst if b.get("expiry") == -1)
        sig = hashlib.md5(json.dumps(perm).encode()).hexdigest()
        ah = self.acc.setdefault("ah", {})
        if ah.get("boosts_sig") == sig:
            return self.log("boosts: permanent boosts unchanged, no answer")
        for lst in boosts.values():
            for b in lst:
                if b.get("expiry") == -1:
                    b["timestamp"] = now
        ah["boosts_sig"] = sig
        self.send(P.frame(P.S_FIELD, bytes.fromhex("50c8eec5") + struct.pack("<f", 1.0) + b"\0" * 8 + lz4.pack_sized(P.jcompact({"boosts": boosts}))))
        self.srv.store.save()

    def on_killsign(self, p: bytes):
        """`66`: a default kill sign the player does not own yet (`default_killsig_N`) -> `45` id 77faca06 {name: 1}."""
        inv = self.acc["profile"].setdefault("_inventory", {})
        free = sorted(k for k in self.srv.lo.economy.catalog if k.startswith("default_killsig_") and not inv.get(k))
        if not free:
            return self.log("killsign: all owned")
        name = random.choice(free)
        inv[name] = 1
        self.send(P.field_raw("killsign", {name: 1}))
        self.srv.store.save()

    def on_pending(self, p: bytes):
        """`72` u32 id of a pending inventory item (`_pending_inv.<name>`, e.g. a level-up rental): its boosts go to `_inventory.boosts`
        (timestamp now, expiry = now in minutes + validity), the entry becomes null; answer `46` id FNV-1a("pending_inventory_tr")."""
        fid = p[:4]
        prof, now = self.acc["profile"], int(time.time())
        pend = prof.get("_pending_inv") or {}
        name = next((k for k in pend if P_fnv(k) == fid), None)
        item = pend.get(name) if name else None
        if not item:
            return self.log("pending %s: nothing to claim" % fid.hex())
        boosts = prof.setdefault("_inventory", {}).setdefault("boosts", {})
        out = {}
        for stat, lst in (item.get("boosts") or {}).items():
            for b in lst:
                b = dict(b, timestamp=now, expiry=now // 60 + int(b.get("expiry", 120)) if b.get("expiry", 0) < 100000 else b["expiry"])
                boosts.setdefault(stat, []).append(b)
                out.setdefault(stat, []).append(b)
        pend[name] = None
        self.log("pending %s claimed: %s" % (name, json.dumps(out)[:160]))
        self.send(P.changes_packed(P_fnv("pending_inventory_tr"), {"_pending_inv": {name: None}, "boosts": out}))
        self.srv.store.save()

    def on_shadow(self, p: bytes):
        """`48`: 16 bytes = FNV-1a(item) + u32 + u32 action + 811c9dc5 (FNV-1a of "").
        For a weapon (trace_full1, AR05): action 0 = ASSEMBLE -> `45 weapon_assemble {"AR05":1}`, action 1 = upgrade -> `45 weapon_upgrade
        {"AR05":2}`, then 3. The real server kept `AR05_bp` (4) and the credits as they were: the client counts blueprints itself (issue: ASSEMBLE
        showed UNLOCKED, but without the answer the weapon stayed locked).
        For another field (`xp` after a mission, `vip_points` after the VIP window / a purchase) the client says it has shown the value:
        `_inventory_shadow.upd_<field>` = the current value (with `upd_vip_points` stuck at 0 the "REACHED VIP LEVEL" window came back at
        every login). No answer, as the real server."""
        prof = self.acc["profile"]
        weapon = self.srv.lo.economy.weapon_by_id(p[:4])
        if weapon:
            action = int.from_bytes(p[8:12], "big")
            changes = self.srv.lo.economy.weapon_step(prof, weapon, upgrade=bool(action))
            reason = "weapon_upgrade" if action else "weapon_assemble"
            self.log("%s %s (args %s) -> %s" % (reason, weapon, p[4:].hex(), json.dumps(changes)))
            self.send(P.item_raw(P_fnv(reason), p[:4], changes))
            return self.srv.store.save()
        inv = prof.setdefault("_inventory", {})
        name = next((k for k in inv if P_fnv(k) == p[:4] and isinstance(inv[k], (int, float))), None)
        if not name:
            return self.log("shadow %s: unknown field" % p[:4].hex())
        self.acc["profile"].setdefault("_inventory_shadow", {})["upd_" + name] = inv[name]
        self.log("shadow upd_%s = %s" % (name, inv[name]))
        self.srv.store.save()

    def on_refresh(self, p: bytes):
        """`21`: like the login of a returning player: veteran flag, ratings, league, event ranks, end of list (recorded order)."""
        prof = self.acc["profile"]
        events = self.srv.lo.events()
        self.send(P.frame(P.S_FLAG, P.s16("&_veteran=" + ("true" if prof.get("is_veteran") else "false"))))
        self.send(P.rating(prof.get("rating") or 800, prof.get("rating_duel") or 800))
        self.send_league(final_only=True)
        for part in self.participations(events):
            self.send(P.event_rank(dict(credential=self.acc["credential"], **part)))
        self.send(P.frame(P.S_RANKS_END))

    def on_next_level(self, p: bytes):
        """`a3`: the block of the next campaign level (the recording: the Tokyo block, exactly as for `06`); `u32 0` when we have none."""
        done = {e.get("level") for e in self.acc["profile"].get("progress") or []}
        for name in self.srv.lo.levels:
            if name != "Story_01.lvc" and name[:-4] not in done:
                return self.send(P.frame(P.S_LEVEL_DATA, self.srv.lo.levels[name]))
        self.send(P.frame(P.S_LEVEL_DATA, b"\0\0\0\0"))

    def on_leave(self, p: bytes):
        self.send(P.frame(P.S_LEFT))

    def on_level_data(self, p: bytes):
        """`06` "<level>.lvc", u32 release -> `07`: the stored block for the level (static content, from the recording) or u32 0."""
        name, _ = P.read_s16(p, 0)
        blob = self.srv.lo.level_data(name.decode("latin1"))
        self.send(P.frame(P.S_LEVEL_DATA, blob if blob is not None else b"\0\0\0\0"))

    def on_time_sync(self, p: bytes):
        self.send(P.server_time(int(time.time())))
        self.send(P.frame(P.S_TIME_SYNC))

    def on_clan(self, p: bytes):
        """`76` u32 seq + JSON -> create/update the player's clan, `77` u32 seq + {"answer": "<group JSON>"}."""
        seq = p[:4]
        s, _ = P.read_s16(p, 4)
        attrs = json.loads(s)
        g = social.save_clan(self.srv.store, self.acc, attrs)
        body = json.dumps({"answer": json.dumps(social.group_view(self.srv.store, g), separators=(",", ":"))}).encode()
        self.send(P.frame(P.S_CLAN, seq + P.s16(body)))

    def send_league(self, final_only: bool):
        """League of the player: the previous value (index, -1/-1 for a new one) then the current season."""
        prof = self.acc["profile"]
        cur = prof.get("league_info_user") or {"index": -1, "last_season": -1, "last_year": -1}
        season, year = self.srv.lo.last_season()
        new = {"index": max(cur.get("index", -1), 0), "last_season": season, "last_year": year}
        if not final_only:
            self.send(P.league(cur, 0xFF))
        self.send(P.league(new, 0x00))
        prof["league_info_user"] = new
        prof.setdefault("league_info_duel", {"index": 0})
        prof.setdefault("rating", 800)
        prof.setdefault("rating_duel", 800)
        self.leagues_sent = True
