"""Live-ops schedule of the AH server: events, CRM config, daily offers, league season.

The real server keeps event templates and makes a new instance of every event for each period: daily activities events every day
(00:00Z..00:00Z), the weekly ones every week, each instance with its own id (uuid1 of its creation time) and milestone ids
(documentation/protocol.md). We do the same from the seed (server/data/ah/events.json, crm.json): an instance is the seed moved by a whole
number of its periods so that `now` falls inside it; daily variants of one event (`_V2`, `_V3`) take turns.
"""
import calendar
import copy
import datetime
import hashlib
import json
import os
import re
import time
import uuid

DAY = 86400
FMT = "%Y-%m-%d %H:%M:%SZ"
DATE_RE = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d:\d\dZ")


def parse(s: str) -> int:
    return calendar.timegm(time.strptime(s, FMT))


def fmt(t: float) -> str:
    return time.strftime(FMT, time.gmtime(t))


class LiveOps:
    def __init__(self, data_dir: str):
        d = os.path.join(data_dir, "ah")
        self.events_seed = json.load(open(os.path.join(d, "events.json")))
        self.crm_seed = json.load(open(os.path.join(d, "crm.json")))
        self.meta = json.load(open(os.path.join(d, "meta.json")))
        self.config = open(os.path.join(d, "config.bin"), "rb").read()
        self.new_profile = json.load(open(os.path.join(d, "new_profile.json")))
        from .economy import Economy
        self.economy = Economy(self.crm_seed, data_dir)
        lv = os.path.join(d, "levels_07.json")   # encrypted level blocks the real server sent for `06` (static content)
        self.levels = {k: bytes.fromhex(v) for k, v in json.load(open(lv)).items()} if os.path.isfile(lv) else {}
        cp = os.path.join(d, "campaign.json")    # client data read from libMC5 memory (documentation/protocol.md): story mission nodes per chapter, XP thresholds
        self.campaign = json.load(open(cp)) if os.path.isfile(cp) else {}

    # --- campaign chapters ('Zone N' of _zones_unlock opens chapter N+1) ---
    def player_level(self, prof: dict) -> int:
        xp = (prof.get("_inventory") or {}).get("xp") or 0
        return sum(1 for t in self.campaign.get("xp_levels") or [0] if t <= xp)

    @staticmethod
    def service_stars(prof: dict) -> int:
        """Mission service stars: one for the mission and one per bonus objective (progress `objective2`, `objective3`); 16 on OnePlus 16.11 = client."""
        return sum(1 + bool(p.get("objective2")) + bool(p.get("objective3")) for p in prof.get("progress") or [] if isinstance(p, dict))

    def zone_unlocks(self, prof: dict) -> dict:
        """Open every next zone whose conditions hold; -> inventory changes ({} if none). `_inventory.unlocked_zones` = number of open zones
        (1 for a new player: chapters 1-2), the client locks chapter i (0-based) while i > unlocked_zones. Zone N needs all story missions of
        chapter N-1 (mandatory) and its other conditions (`_zones_unlock`), or the bought skip `skip_ucrit_zone_N`; then the prize of the zone.
        Conditions the server cannot count (finishmp, sqdmember, weaptier/weapcount, openpacks) count as not met: they can be skipped."""
        zones = (self.crm_seed.get("game") or {}).get("_zones_unlock") or {}
        story = self.campaign.get("story_nodes") or {}
        inv = prof.setdefault("_inventory", {})
        done = {p.get("node") for p in prof.get("progress") or [] if isinstance(p, dict)}
        changes = {}
        while True:
            n = int(inv.get("unlocked_zones") or 1) + 1
            z = zones.get("Zone %d" % n)
            nodes = story.get(str(n - 1))
            if not z or nodes is None or not set(nodes) <= done:
                break
            skipped = (inv.get("skip_ucrit_zone_%d" % n) or 0) > 0
            have = {"servicestars": self.service_stars(prof), "playerlvl": self.player_level(prof)}
            unmet = [k for k in z if k not in ("prize_name", "prize_qty") and z[k] and have.get(k, -1) < z[k]]
            if unmet and not skipped:
                break
            inv["unlocked_zones"] = n
            prof.setdefault("_inventory_shadow", {})["upd_unlocked_zones"] = n
            changes["unlocked_zones"] = n
            prize, qty = z.get("prize_name"), int(z.get("prize_qty") or 0)
            if prize and 0 < qty < 99999:       # Zone 1: AR03_bp x 99999 = no real prize (the starting weapon)
                inv[prize] = (inv.get(prize) or 0) + qty
                changes[prize] = inv[prize]
        return changes

    def level_data(self, name: str):
        return self.levels.get(name)

    # --- events ---
    @staticmethod
    def _period(start: int, end: int) -> int:
        return DAY if end - start <= DAY else 7 * DAY

    def _groups(self) -> list:
        """Seed events grouped into rotations: daily variants of one event (`ACTIVITIES_Upd27_V2` on 23.10, `_V3` on 24.10 in the
        recordings) take turns day by day, in the order of their recorded days. Anything else is a group of one."""
        groups = {}
        for e in self.events_seed:
            s, t = parse(e["start_date"]), parse(e["end_date"])
            per = self._period(s, t)
            key = (VARIANT_RE.sub("", e["name"]), per) if per == DAY else (e["id"], per)
            groups.setdefault(key, []).append(e)
        return [sorted(g, key=lambda e: parse(e["start_date"])) for g in groups.values()]

    def _instances(self, now: float):
        """(seed event, shift in seconds) of the occurrence of every event that is running or next at `now`."""
        out = []
        for g in self._groups():
            e = g[0]
            s, t = parse(e["start_date"]), parse(e["end_date"])
            per = self._period(s, t)
            k = int((now - s) // per)
            if now >= s + k * per + (t - s):  # gap between occurrences (e.g. ends 23:59): next occurrence
                k += 1
            if len(g) > 1:                    # daily rotation: the variant recorded k days after the first one, cyclically
                e = g[k % len(g)]
                k -= (parse(e["start_date"]) - s) // per
            out.append((e, k * per))
        return out

    def events(self, now: float = None) -> list:
        """Every occurrence is a new event instance, as at the real server: its own id (uuid1 of its creation time, `_created_on`)
        and its own milestone ids (V2 -> V3: new id and new `_milestone_id`s, documentation/protocol.md). The player's participation
        (`tournaments_sem`, claimed tasks/milestones) is per id, so a new day starts with fresh daily tasks."""
        now = now or time.time()
        out = []
        for e, shift in self._instances(now):
            ev = copy.deepcopy(e)
            for key in ("start_date", "end_date", "participation_end_date", "_advertisement_start_date", "_advertisement_end_date",
                        "_created_on"):
                if isinstance(ev.get(key), str) and DATE_RE.fullmatch(ev[key]):
                    ev[key] = fmt(parse(ev[key]) + shift)
            if shift:
                ev["id"] = instance_id(e["id"], shift)
                _remap_milestones(ev, shift)
            ev["status"] = "started" if parse(ev["start_date"]) <= now < parse(ev["end_date"]) else "scheduled"
            out.append(ev)
        return out

    def _event_ids(self, now: float) -> dict:
        """seed id -> (id of the current instance, shift, seed id of the chosen variant, its creation time) for every seed event;
        all variants of a rotation map to the chosen one. `meta.event_aliases`: ids of earlier instances that the CRM seed
        (recorded a day before the events seed) still names -> seed id of the same event."""
        cur = {}
        for e, shift in self._instances(now):
            cur[VARIANT_RE.sub("", e["name"])] = (instance_id(e["id"], shift) if shift else e["id"], shift, e["id"],
                                                  parse(e["_created_on"]) + shift if DATE_RE.fullmatch(e.get("_created_on") or "") else None)
        out = {e["id"]: cur[VARIANT_RE.sub("", e["name"])] for e in self.events_seed if VARIANT_RE.sub("", e["name"]) in cur}
        for old, sid in self.meta.get("event_aliases", {}).items():
            if sid in out:
                out[old] = out[sid]
        return out

    @staticmethod
    def activity_events(events: list) -> list:
        """Events the player takes part in automatically (tournaments_sem): category mc5_activities_event."""
        return [e for e in events if e["_template"].get("category") == "mc5_activities_event" and e["status"] == "started"]

    @staticmethod
    def task_count(ev: dict) -> int:
        tasks = ev["_template"].get("event_tuning", {}).get("_tasks", {}).get("value", [])
        return len(tasks)

    @staticmethod
    def initial_stats(ev: dict, prof: dict) -> list:
        """`initial_activities_stats` of a new participation: the player's counter of every task at the moment he joins
        (the client shows progress = counter - initial). With zeros a veteran finished every SP task at once and the client
        claimed them by itself (OnePlus 16.11: tasks 0, 2, 3, 4 of a fresh instance, not the MP one where the counter is 0).
        Counters known from that observation: TASK_STATS; other conditions (MP, BR, daily reward) start at 0, as recorded."""
        st = (prof or {}).get("statistics") or {}
        out = []
        for t in ev["_template"].get("event_tuning", {}).get("_tasks", {}).get("value", []):
            cond = ((t.get("sub") or {}).get("condition") or {}).get("value") or {}
            v = 0
            for key in cond:
                path = TASK_STATS.get(key)
                if path:
                    o = st
                    for part in path:
                        o = o.get(part) if isinstance(o, dict) else None
                    v = int(o) if isinstance(o, (int, float)) else 0
            out.append(v)
        return out

    # --- CRM config ('?' frame) ---
    def crm(self, events: list, now: float = None, prof: dict = None) -> dict:
        now = now or time.time()
        c = copy.deepcopy(self.crm_seed)
        if prof and (prof.get("ud_step") or (prof.get("ultimate_draw") or {}).get("ud_step")):
            # the Lucky Spin promo popup advertises the first, free spin: not shown to a player who has already spun
            c["pointcut_actions"] = [a for a in c.get("pointcut_actions", []) if "ULTIMATEDRAW" not in str(a.get("popup_id", ""))]
        ids = {e["id"] for e in events}
        inst = self._event_ids(now)
        gw = c.get("groupware", {}).get("events", {})
        for k in list(gw):
            rows = []
            for p in gw[k]:
                new_id, shift, chosen, created = inst.get(p.get("id"), (p.get("id"), 0, p.get("id"), None))
                if new_id in ids and new_id not in {r["id"] for r in rows}:
                    if isinstance(p.get("changed"), str) and DATE_RE.fullmatch(p["changed"]):
                        if chosen == p.get("id"):
                            p["changed"] = fmt(parse(p["changed"]) + shift)
                        elif created is not None:     # another variant / an alias: changed right after the instance was created
                            p["changed"] = fmt(created)
                    p["id"] = new_id
                    rows.append(p)
            gw[k] = rows
        # Lucky Spin: the recorded draw ends 2026-10-29 10:00Z; it is prolonged week by week (same items and version 77,
        # the player's ud_step / ud_inventory carry on: what the real server does after a draw ends is not recorded)
        ud = c.get("game", {}).get("_ultimate_draw_config", {})
        if isinstance(ud.get("ultimate_draw_end"), str) and DATE_RE.fullmatch(ud["ultimate_draw_end"]):
            end = parse(ud["ultimate_draw_end"])
            if now >= end:
                end += (int((now - end) // (7 * DAY)) + 1) * 7 * DAY
            ud["ultimate_draw_end"] = fmt(end)
        c["expiry"] = fmt(next_midnight(now))
        # consent SDK (Didomi) is a server decision: `didomi_type` [] = no Didomi gate (default; the web SDK needs the internet),
        # MC5_DIDOMI=on keeps the recorded mode DIDOMI_AGEGATE_WITHREJECT
        if os.environ.get("MC5_DIDOMI", "off") != "on":
            c.get("game", {}).get("_global_params", {})["didomi_type"] = []
        return c

    # --- daily offers ('G' frame) ---
    def daily_offers(self, now: float = None) -> dict:
        """Offers valid until the next day boundary; expiry in MINUTES since the epoch (recorded 29880120 = 2026-10-24 02:00Z)."""
        now = now or time.time()
        return {"expiry": int((next_midnight(now) + 2 * 3600) // 60), "offers": [{"name": n, "used": 0} for n in self.meta.get("offers", [])]}

    # --- league season ('=' frame) ---
    @staticmethod
    def last_season(now: float = None):
        """Weekly seasons: last_season = ISO week of the previous week (recorded 42 on 2026-10-23, week 43)."""
        now = now or time.time()
        d = datetime.datetime.utcfromtimestamp(now) - datetime.timedelta(days=7)
        y, w, _ = d.isocalendar()
        return w, y


def next_midnight(now: float) -> int:
    return (int(now) // DAY + 1) * DAY


VARIANT_RE = re.compile(r"_V\d+$")
# activities task condition -> path in profile `statistics` (what the server sums from mission results, ah.apply_result)
TASK_STATS = {"singleplayer_kills": ("sp", "kill.total"), "singleplayer_headshots": ("sp", "kill.headshots"),
              "singleplayer_missions": ("sp", "game.campaign.wins")}
UUID_EPOCH = 0x01B21DD213814000   # 1582-10-15 in 100 ns units (uuid1 time base)


def instance_id(seed_id: str, shift: int) -> str:
    """uuid1 of the instance: the seed's time moved by `shift`, same clock sequence and node (all recorded ids share the
    Gameloft node, e.g. ...-c6d6ee507b37). Deterministic, so every login on the same day sees the same id."""
    u = uuid.UUID(seed_id)
    t = u.time + shift * 10 ** 7
    return str(uuid.UUID(fields=(t & 0xFFFFFFFF, (t >> 32) & 0xFFFF, ((t >> 48) & 0x0FFF) | 0x1000,
                                 u.clock_seq_hi_variant, u.clock_seq_low, u.node)))


def _remap_milestones(ev: dict, shift: int):
    """New `_milestone_id` (32 hex) for every task and milestone of an instance; deterministic per seed id and shift."""
    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == "_milestone_id" and isinstance(v, dict) and isinstance((v.get("value") or {}).get("text_plain"), str):
                    tp = v["value"]["text_plain"]
                    v["value"]["text_plain"] = hashlib.md5(("%s:%d" % (tp, shift)).encode()).hexdigest()
                else:
                    walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(ev.get("_template"))
