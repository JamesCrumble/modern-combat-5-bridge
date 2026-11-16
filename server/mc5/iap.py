"""Real-money store without Google (documentation/protocol.md): the catalog is CRM `iap.prices` (the data Gameloft's own server distributes), the Java layer of the
client (mc5.Store, bridge/patch/dex/iap.spec) asks us for product details and orders instead of Google Play Billing.
A product is a CRM entry whose billing method `googleplay` has a `content_id` (the product id the game asks Google for); its `bundle` is what the player gets."""
import json
import os
import random
import string
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PACKAGE = "com.gameloft.android.ANMP.GloftM5HM"


def fnv1a(name: str) -> bytes:
    h = 0x811C9DC5
    for c in name.encode():
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h.to_bytes(4, "big")


class Catalog:
    def __init__(self, crm_path: str):
        crm = json.load(open(crm_path))
        self.credits = crm.get("game", {}).get("_credits", {})      # CRM definitions of the items (category, autoactivate, boosts, validity)
        self.by_content = {}
        self.by_entry = {}          # FNV-1a(entry_id) -> content_id: the id the client sends to the game server after the payment (AH frame 0x44)
        for p in crm.get("iap", {}).get("prices", []):
            for bm in p.get("billing_methods", []):
                if bm.get("type") == "googleplay" and bm.get("content_id"):
                    self.by_content[bm["content_id"]] = (p, bm)
                    for key in (p.get("entry_id"), p.get("_id")):
                        if key:
                            self.by_entry[fnv1a(key)] = bm["content_id"]

    def details(self, content_id: str):
        """Product details in the shape the Java layer expects (what it builds from Google's ProductDetails)."""
        hit = self.by_content.get(content_id)
        if not hit:
            return None
        p, bm = hit
        return {"productId": content_id, "type": "inapp", "title": p.get("name", content_id), "description": p.get("description", ""),
                "price": bm.get("display_price") or "%.2f %s" % (bm["price"], bm["currency"]),
                "price_amount_micros": int(round(float(bm["price"]) * 1000000)), "price_currency_code": bm["currency"]}

    def bundle(self, content_id: str) -> list:
        hit = self.by_content.get(content_id)
        return [{"item": b["item"], "quantity": b["quantity"]} for b in hit[0].get("bundle", [])] if hit else []


def new_order(product_id: str, payload: str) -> dict:
    """A purchase as Google would sign it (the signature is the marker MC5LOCAL that the patched client accepts)."""
    rnd = lambda n: "".join(random.choice(string.digits) for _ in range(n))
    order_id = "GPA.%s-%s-%s-%s" % (rnd(4), rnd(4), rnd(4), rnd(5))
    token = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(48))
    now = int(time.time() * 1000)
    purchase = {"orderId": order_id, "packageName": PACKAGE, "productId": product_id, "purchaseTime": now, "purchaseState": 0,
                "purchaseToken": token, "quantity": 1, "acknowledged": False, "developerPayload": payload or ""}
    return {"order_id": order_id, "product_id": product_id, "token": token, "time": now, "json": json.dumps(purchase, separators=(",", ":")),
            "payload": payload or "", "granted": False}


def decode_cinfo(b64: str) -> dict:
    import base64
    try:
        return json.loads(base64.b64decode(b64 + "=" * (-len(b64) % 4)).decode("utf-8"))
    except (ValueError, TypeError):
        return {}


def ecomm_action(f: dict, store) -> dict:
    """E-commerce server of the IAP library (POST / with `action=`). Every action is recorded in full (state iap_requests): the client's
    parsing of each answer is known only from its code, the real answers were never recorded.
    pre_transaction (pre_buy_registration): answer `{"status": "1"}` = registration accepted (anything else is read as an error:
    code, code_str, message, next_transaction_time, seconds_before_next_transaction)."""
    action = f.get("action", "")
    rec = store.data.setdefault("iap_requests", [])
    rec.append({"t": time.time(), "form": {k: (v if k not in ("token",) else v[:40]) for k, v in f.items()}})
    del rec[:-200]
    over = os.path.join(os.path.dirname(store.path), "ecomm_override.json")     # experiments: {"<action>": <answer>} read at every request
    if os.path.isfile(over):
        try:
            ans = json.load(open(over)).get(action)
            if ans is not None:
                return ans
        except ValueError:
            pass
    if action == "transaction":
        return deliver(f, store)
    if action == "pre_transaction":
        item = decode_cinfo(f.get("cinfo", ""))
        store.data.setdefault("iap_pre", {})[f.get("token", "")[:36]] = item.get("_id")
        store.save()
        return {"status": "1"}
    return {"status": "1"}


def deliver(f: dict, store) -> dict:
    """`action=transaction` (verify_transaction of the client): the payment made by mc5.Store (`rdata` = our order id, `gp_token` = purchase token, `cid` = Google
    product id) is confirmed: the order is marked `paid` for the account in `token` (first field = fed_id). Answer read by the client (libMC5 0xd0ecb4..0xd0f064):
    `status` = "delivered", `transaction_id` non-empty. The goods are given by the game server when the client asks for them (AH frame 0x44, `claim`)."""
    orders = store.data.setdefault("iap_orders", {})
    order = orders.get(f.get("rdata", "")) or next((o for o in orders.values() if o.get("token") == f.get("gp_token")), None)
    fed_id = (f.get("token") or "").split(",")[0]
    if not order or store.by_fed_id(fed_id) is None or not catalog().bundle(order["product_id"]):
        return {"status": "error", "message": "unknown order or product"}
    order["paid"] = True
    order["fed_id"] = fed_id
    store.save()
    return {"status": "delivered", "transaction_id": order["order_id"]}


def grant_bundle(acc: dict, content_id: str) -> dict:
    """Give the bundle of a product to the profile; -> the changes for the `46` answer ({item: new total}, plus `boosts` for the autoactivated boosts).
    Items are inventory counters (credits, vip_points, battlepacks, weapon `_PRO` / `_bp`, camos, masks, killsigns, skill classes, purchase limiters: the CRM
    marks them `delivery: profile_transaction`). Autoactivated credits with `boosts` (e.g. pwrusr_iap_bundle_1) become boosts for `validity` minutes,
    like the level-up rentals. `unlock_weapons_<class>` / `upgrade_skills_<class>` (autoactivate, param = tier) are only counted: what they change in the profile is not known."""
    cat = catalog()
    inv = acc.setdefault("profile", {}).setdefault("_inventory", {})
    changes, now = {}, int(time.time())
    for it in cat.bundle(content_id):
        name, qty = it["item"], int(it["quantity"])
        c = cat.credits.get(name) or {}
        if c.get("autoactivate") and c.get("boosts"):
            boosts = inv.setdefault("boosts", {})
            for b in c["boosts"]:
                lst = boosts.setdefault(b["stat"], [])
                lst.append({"expiry": now // 60 + int(c.get("validity", 0)), "factor": b["value"], "from_credit": name, "timestamp": now})
                changes.setdefault("boosts", {})[b["stat"]] = list(lst)
            continue
        inv[name] = (inv.get(name) or 0) + qty
        changes[name] = inv[name]
    return changes


def claim(store, acc: dict, entry_id: bytes):
    """AH frame 0x44 <FNV-1a(entry id)>: the client has paid and asks for the goods. -> changes or None when there is no paid, unclaimed order."""
    content_id = catalog().by_entry.get(entry_id)
    mine = [o for o in store.data.get("iap_orders", {}).values() if o.get("paid") and not o.get("claimed") and o.get("fed_id") == acc["fed_id"]]
    order = next((o for o in mine if o["product_id"] == content_id), None)
    if not order and content_id is None and mine:
        # an id that is no CRM entry: seen in the RESTORE PURCHASES flow (27.10: `3f9ef80c` after `transaction` of an order restored at startup, the refusal
        # crashed the client): the player's oldest paid, not yet delivered order is given
        order = min(mine, key=lambda o: o["time"])
        content_id = order["product_id"]
    if not order:
        return None
    changes = grant_bundle(acc, content_id)
    order["claimed"] = True
    order["claimed_at"] = time.time()
    store.save()
    return changes


_cat = []
DATA_DIR = os.path.join(HERE, "..", "data")      # set by mc5server.py (--data)


def catalog() -> "Catalog":
    if not _cat:
        _cat.append(Catalog(os.path.join(DATA_DIR, "ah", "crm.json")))
    return _cat[0]
