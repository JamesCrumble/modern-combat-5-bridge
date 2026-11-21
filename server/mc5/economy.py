"""Economy of the AH server, driven by the game's own data (CRM config `game`, Iris `game_object`), documentation/protocol.md:

- ids on the wire are FNV-1a 32 of the item/offer name, big-endian (`battlepack` = 28b13c02);
- `_credits`: every item (category, tier, autoactivate, param ...), `game_object`: the catalog (categories of cores etc.);
- `_battlepacks_def[pack]` -> weighted config base -> stages `<base>#1..#N` in `_battlepacks_configs*`; an entry is an item, `x*N`
  (item x, quantity N) or a group `<category>#<tier>` (any droppable credit of that category and tier; cores: level = 2nd digit);
- offers (`_offers[offer].items`) cost `offline_store.prices[_id].billing_methods[0].price` (currency, price);
- Ultimate Draw (`_ultimate_draw_config`): price by step, each item drawn once (`ultimate_draw.ud_inventory`);
- mission rewards (`_mission_rewards[kind]`): `pb_credits: N` always, then one weighted pick among the other entries.
  This reading of the table matches both recorded first-time results ({"battlepack":1,"pb_credits":50}); not proven further.
Answers carry the NEW totals of the changed inventory keys (recorded: `battlepack: 0` after opening, `AR05_bp` 3 -> 4).
"""
import json
import os
import random
import time


def fnv1a(name: str) -> bytes:
    h = 0x811C9DC5
    for c in name.encode():
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h.to_bytes(4, "big")


class Economy:
    def __init__(self, crm: dict, data_dir: str):
        g = crm.get("game", {})
        self.credits = g.get("_credits", {})
        self.packs = g.get("_battlepacks_def", {})
        self.configs = {}
        for k, v in g.items():
            if k.startswith("_battlepacks_configs") and isinstance(v, dict):
                self.configs.update(v)
        self.offers = g.get("_offers", {})
        self.ud = g.get("_ultimate_draw_config", {})
        self.mission_rewards = g.get("_mission_rewards", {})
        self.prices = {}
        for p in crm.get("offline_store", {}).get("prices", []) or []:
            try:
                bm = p["billing_methods"][0]["price"][0]
                self.prices[p["_id"]] = (bm["currency"], int(bm["price"]))
            except (KeyError, IndexError, TypeError, ValueError):
                pass
        self.catalog = {}
        path = os.path.join(data_dir, "iris", "game_object")
        if os.path.isfile(path):
            for o in json.load(open(path)):
                if "id" in o:
                    self.catalog[o["id"]] = o
        names = set(self.credits) | set(self.packs) | set(self.offers) | set(self.catalog) | set(self.prices)
        self.by_id = {fnv1a(n): n for n in names}
        self.rentals = self._template_offers()
        self.by_id.update({fnv1a(n): n for n in self.rentals})

    def _template_offers(self) -> dict:
        """Instances of the template offers, as the client builds them (libMC5: `%s_rent` 0x610414, OnePlus 16.11 `ptrace_log`):
        the template credit `wp_rent_t<N>` (`is_template`, category `weapon_rent`, tier N, boosts stat `weapon#N`) becomes one credit
        `<weapon>_rent` per weapon of tier N (boosts stat = the weapon id, as the plain `levelup_t3_assault_rent` -> `AR03`), and the
        template offer `rent_weapon_tier_N` (items `weapon_rent#N`, `template: true`) one offer `<offer>_<weapon>_rent` per such credit;
        the `41` id is FNV-1a of that name (`rent_weapon_tier_3_AR03_rent` = 97d90471 for TRY IT on UFIA PSD-2).
        Weapon tiers are client data: an instance is made for every catalog weapon, the name already says which offer and weapon."""
        tmpl = {}
        for k, v in self.credits.items():
            if v.get("is_template") and v.get("category") == "weapon_rent" and v.get("tier") is not None:
                tmpl["weapon_rent#%s" % v["tier"]] = (k, v)
        weapons = {o for o, c in self.catalog.items() if c.get("category") in ("weapon", "weapon_pro")}
        out = {}
        for name, off in self.offers.items():
            if not off.get("template"):
                continue
            for it in off.get("items") or []:
                t = tmpl.get(it.get("id"))
                if not t:
                    continue
                for w in weapons:
                    out["%s_%s_rent" % (name, w)] = (name, w, t[1])
        return out

    def rent(self, prof: dict, inst: str):
        """Buy an instance of a template rental offer -> (status, changes): price of the template offer (offline_store), the rented weapon
        becomes a boost {weapon id: [{factor, expiry = now in minutes + validity, from_credit <weapon>_rent, timestamp}]} like the level-up
        rentals (`72`) and the bundle rentals (iap.grant_bundle). Status 4 = not enough currency."""
        offer, weapon, cred = self.rentals[inst]
        cur, price = self.prices.get(offer, ("credits", 0))
        inv = self.inv(prof)
        if (inv.get(cur) or 0) < price:
            return 4, {}
        changes = {}
        if price:
            inv[cur] -= price
            changes[cur] = inv[cur]
        now = int(time.time())
        boosts = inv.setdefault("boosts", {})
        for b in cred.get("boosts") or [{"value": 1}]:
            lst = boosts.setdefault(weapon, [])
            lst.append({"expiry": now // 60 + int(cred.get("validity", 0)), "factor": b.get("value", 1), "from_credit": weapon + "_rent", "timestamp": now})
            changes.setdefault("boosts", {})[weapon] = list(lst)
        return 0, changes

    # ---------------------------------------------------------------- inventory
    @staticmethod
    def inv(prof: dict) -> dict:
        return prof.setdefault("_inventory", {})

    def grant(self, prof: dict, item: str, qty: int, changes: dict):
        inv = self.inv(prof)
        inv[item] = (inv.get(item) or 0) + qty
        changes[item] = inv[item]

    def weapon_by_id(self, fid: bytes):
        """FNV-1a id -> weapon name, or None: a catalog weapon (`weapon`, `weapon_pro`) or anything with a blueprint `<name>_bp`."""
        name = self.by_id.get(fid)
        if not name:
            return None
        cat = (self.catalog.get(name) or {}).get("category")
        return name if cat in ("weapon", "weapon_pro") or name + "_bp" in self.catalog else None

    def weapon_step(self, prof: dict, weapon: str, upgrade: bool) -> dict:
        """ASSEMBLE -> the weapon becomes 1, an upgrade adds 1 (recorded AR05: 1, 2, 3). Blueprints and credits stay as they are: the real
        server did not take them (AR05_bp 4 before and after), the client compares the blueprint count with its own cost table."""
        inv = self.inv(prof)
        cur = inv.get(weapon) or 0
        inv[weapon] = cur + 1 if upgrade else max(cur, 1)
        return {weapon: inv[weapon]}

    def group(self, ref: str, exclude=()) -> list:
        """`weapon_bp#3` -> droppable weapon blueprints of tier 3; `core#21` -> cores of level 1 (tier digit not mapped yet)."""
        cat, _, tier = ref.partition("#")
        if cat == "core" and len(tier) == 2:
            level = "_l" + tier[1]
            return [k for k, o in self.catalog.items() if o.get("category") == "core" and k.endswith(level)]
        t = int(tier) if tier.isdigit() else None
        found = [k for k, v in self.credits.items() if isinstance(v, dict) and v.get("category") == cat and v.get("tier") == t
                 and v.get("can_drop_bp", True) and not v.get("is_template")]
        if not found and cat == "weapon_bp":
            # APPROXIMATION: weapon tiers are not in the server data (client data, encrypted options.gla2): any catalog
            # blueprint except the stage's zero-weight exclusions. The real distribution per tier is not reproduced yet.
            found = [k for k, o in self.catalog.items() if o.get("category") == "weapon_bp" and k not in exclude]
        return found

    def apply_entry(self, prof: dict, entry: str, changes: dict, exclude=()):
        if "*" in entry:
            item, _, n = entry.partition("*")
            self.grant(prof, item, int(n), changes)
        elif "#" in entry:
            pool = self.group(entry, exclude)
            if pool:
                self.grant(prof, random.choice(pool), 1, changes)
        else:
            self.grant(prof, entry, 1, changes)

    @staticmethod
    def pick(table: dict):
        items = [(k, w) for k, w in table.items() if isinstance(w, (int, float)) and w > 0 and k != "has_watch_add"]
        if not items:
            return None
        r = random.uniform(0, sum(w for _, w in items))
        for k, w in items:
            r -= w
            if r <= 0:
                return k
        return items[-1][0]

    # ---------------------------------------------------------------- packs, credits, offers
    def open_pack(self, prof: dict, pack: str, changes: dict):
        """Consume one pack and roll its stages."""
        inv = self.inv(prof)
        if (inv.get(pack) or 0) > 0:
            inv[pack] -= 1
        changes[pack] = inv.get(pack, 0)
        if pack == "ultimate_battlepack" or (self.credits.get(pack) or {}).get("param") == "ultimate":
            return self.ultimate_draw(prof, changes)
        base = self.pick(self.packs.get(pack, {}))
        if not base:
            return
        stage = 1
        while ("%s#%d" % (base, stage)) in self.configs:
            table = self.configs["%s#%d" % (base, stage)]
            entry = self.pick(table)
            if entry:
                self.apply_entry(prof, entry, changes, {k for k, w in table.items() if w == 0})
            stage += 1

    def use_credit(self, prof: dict, name: str) -> dict:
        changes = {}
        c = self.credits.get(name) or {}
        if c.get("category") == "battlepack" or name in self.packs:
            self.open_pack(prof, name, changes)
        else:
            inv = self.inv(prof)
            if (inv.get(name) or 0) > 0:
                inv[name] -= 1
            changes[name] = inv.get(name, 0)
        return changes

    def buy_offer(self, prof: dict, offer: str):
        """-> (status, changes, opened) ; status 0 ok, 4 not enough currency (recorded refusal code)."""
        items = (self.offers.get(offer) or {}).get("items") or [{"id": offer, "qty": 1}]
        cur, price = self.prices.get(offer, ("credits", 0))
        if offer.startswith("ultimate_battlepack"):
            steps = self.ud.get("ultimate_draw_prices") or [0]
            step = prof.get("ud_step", (prof.get("ultimate_draw") or {}).get("ud_step", 0))
            price = steps[min(step, len(steps) - 1)]
            cur = self.ud.get("ultimate_draw_currency", "credits")
        inv = self.inv(prof)
        if (inv.get(cur) or 0) < price:
            return 4, {}, []
        changes = {}
        if price:
            inv[cur] -= price
            changes[cur] = inv[cur]
        opened = []
        hist = prof.setdefault("battlepacks_history", {})
        for it in items:
            iid, qty = it.get("id"), int(it.get("qty", 1))
            self.grant(prof, iid, qty, changes)
            if (self.credits.get(iid) or {}).get("category") == "battlepack":
                h = hist.setdefault(iid, {"count": 0, "next_reset": 0, "viewed": 0})
                changes.setdefault("battlepacks_history", {})[iid] = h
            if (self.credits.get(iid) or {}).get("autoactivate"):
                opened.append(iid)
        return 0, changes, opened

    def ultimate_draw(self, prof: dict, changes: dict):
        ud = prof.setdefault("ultimate_draw", {"ud_ver": self.ud.get("ultimate_draw_version")})
        have = {k for d in ud.get("ud_inventory") or [] for k in d}
        table = dict((self.configs.get("ultimate_1#1") or {}))
        for k in list(table):
            if k in have:
                del table[k]
        if not table:   # list exhausted: the remaining configured items (currency entries) with rarity weights
            names = self.ud.get("ultimate_draw_items") or []
            rar = self.ud.get("ultimate_draw_rarities") or []
            table = {n: rar[i] if i < len(rar) else 1 for i, n in enumerate(names) if n not in have}
        item = self.pick(table)
        if not item:
            return
        got = {}
        self.apply_entry(prof, item, got)
        changes.update(got)
        changes["_ultimateDraw"] = {item: 1}
        ud.setdefault("ud_inventory", []).append({item: 1})
        ud["ud_step"] = ud.get("ud_step", 0) + 1
        prof["ud_step"] = ud["ud_step"]      # the client reads the step from the top-level profile field (27.10: nested only -> "FREE SPIN!" at any step)
        ud["ud_ver"] = self.ud.get("ultimate_draw_version", ud.get("ud_ver"))

    def view_pack(self, prof: dict, pack: str):
        h = prof.setdefault("battlepacks_history", {}).setdefault(pack, {"count": 0, "next_reset": 0, "viewed": 0})
        h["viewed"] = 1

    # ---------------------------------------------------------------- missions
    def mission_reward(self, prof: dict, kind: str) -> dict:
        table = dict(self.mission_rewards.get(kind) or {})
        table.pop("location", None)
        changes = {}
        pb = table.pop("pb_credits", 0)
        if pb:
            self.grant(prof, "pb_credits", int(pb), changes)
        entry = self.pick(table)
        if entry:
            self.apply_entry(prof, entry, changes)
        return changes
