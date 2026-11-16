"""Gaia HTTP services of MC5 6.0.12a, built on the shared state (documentation/protocol.md): Eve, Pandora, GDID, Janus, Osiris, Hermes, Federation,
Anubis, Iris, plus the small ones (sink, oct, iap). Answers are generated from the store; recorded bodies were only the model."""
import hashlib
import json
import os
import re
import time
from typing import Dict, List
from urllib.parse import parse_qs

from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from .web import FastAPI, Request

from . import chat, iap, social, tokens

app = FastAPI(title="MC5 Gaia stand-in")
cfg: Dict[str, object] = {}       # filled by server/mc5server.py: store, log, dirs, public addresses, ports
LOG: List[dict] = []

LOCATE = {"auth": "janus", "asset": "iris", "social": "osiris", "leaderboard": "olympus", "storage": "seshat", "matchmaker": "anubisfinder",
          "schedule": "chronos", "transaction": "mercury", "message": "hermes"}
URL_SERVICES = ["ads_agency", "apple_iap", "china_regulation", "crm_iap", "customer_care", "ecomm_api_root", "etsv2", "federation",
                "federation-internal", "game_portal", "game_portal-internal", "gdid", "gllive-asa", "gllive-bdc", "gllive-ope",
                "livewebapp", "marketing_site", "offline_apple_iap", "offline_items", "online_connectivity", "statetrackers", "tapjoy"]
JSON_UTF8 = "application/json;charset=UTF-8"


def log(msg):
    cfg["log"](msg)


def store():
    return cfg["store"]


def form(request: Request) -> dict:
    """Body was read by the ASGI wrapper (server/mc5server.py) into scope['mc5.body']."""
    body = request.scope.get("mc5.body", b"")
    return {k: v[0] for k, v in parse_qs(body.decode("latin1"), keep_blank_values=True).items()}


def account_of(token: str):
    info = tokens.parse(token or "")
    if not info:
        return None, None
    return store().by_fed_id(info["fed_id"]), info


def unauthorized():
    return JSONResponse({"error": "invalid access token"}, status_code=401)


# ------------------------------------------------------------------ admin
@app.get("/_mc5/ready")
def ready():
    return {"ok": True, "accounts": len(store().data["accounts"]), "iris": cfg["iris_dirs"]}


@app.get("/_mc5/log")
def get_log(n: int = 100):
    return LOG[-n:]


# ------------------------------------------------------------------ small services
@app.get("/has-conf-api")
def sink_has_conf_api():
    return Response(b"", media_type="application/json", headers={"x-ll-code": "204"})


@app.get("/")
def root_ok():
    return PlainTextResponse("OK")  # online_connectivity probe


@app.post("/")
def root_post(request: Request):
    """GLOT / etsv2 telemetry (JSON) and the e-commerce actions of the client's IAP library (form `action=...`, documentation/protocol.md)."""
    body = request.scope.get("mc5.body", b"")
    if body.startswith(b"action="):
        f = form(request)
        out = iap.ecomm_action(f, store())
        log("ecomm %s -> %s" % (f.get("action"), json.dumps(out)[:200]))
        return JSONResponse(out, headers={"X-InApp-Hash": "mc5-local"})     # the client wants the header (value is not checked in our build, IAP_NOVERIFY)
    return PlainTextResponse("OK")


@app.post("/connectionstatus")
def connectionstatus():
    return PlainTextResponse("OK\n")


@app.get("/inapp_crm/index.php")
def iap_crm(action: str = ""):
    return Response(json.dumps({"enabled": False}, separators=(",", ":")), media_type="application/com.gameloft.ecomm.crm-v1.3+json")


def iap_catalog() -> "iap.Catalog":
    return iap.catalog()


@app.get("/iap/products")
def iap_products(ids: str = "", type: str = ""):
    """Product details for the ids the game asks Google for (mc5.Store, documentation/protocol.md)."""
    out = [d for d in (iap_catalog().details(i) for i in ids.split(",") if i) if d]
    log("iap products %s -> %d" % (ids[:80], len(out)))
    return JSONResponse(out)


@app.get("/iap/owned")
def iap_owned(type: str = "inapp"):
    """Purchases the player owns but the game has not been given yet (queryPurchases of RESTORE PURCHASES, mc5.Store.owned): our orders that are not
    claimed. Subscriptions (`subs`): none are kept."""
    if type != "inapp":
        return JSONResponse([])
    out = [{"orderId": o["order_id"], "productId": o["product_id"], "json": o["json"]}
           for o in store().data.get("iap_orders", {}).values() if not o.get("claimed")]
    log("iap owned %s -> %d" % (type, len(out)))
    return JSONResponse(out)


@app.post("/iap/order")
async def iap_order(request: Request):
    """The player taps a pack: an order is created (as Google's purchase) and kept until the game confirms it."""
    req = json.loads(request.scope.get("mc5.body", b"{}") or b"{}")
    pid = req.get("product_id", "")
    if not iap_catalog().details(pid):
        return JSONResponse({"status": 1, "error": "unknown product"})
    order = iap.new_order(pid, req.get("payload", ""))
    store().data.setdefault("iap_orders", {})[order["order_id"]] = order
    store().save()
    log("iap order %s %s" % (order["order_id"], pid))
    return JSONResponse({"status": 0, "orderId": order["order_id"], "json": order["json"]})


@app.get("/android/banned_services/")
def banned_services():
    return []


# ------------------------------------------------------------------ Eve / Pandora / GDID
@app.get("/config/{client}/datacenters")
def eve_datacenters(client: str):
    dcs = [{"name": n, "status": "active", "preferred": n == "eur", "country_code": "US", "_datacenter_id": "local_1924_01"}
           for n in ("eur", "eur_in_apa", "eur_in_chn")]
    body = json.dumps(dcs)
    return Response(body, media_type="application/json", headers={"ETag": '"%s"' % hashlib.sha1(body.encode()).hexdigest()})


@app.get("/config/{client}/datacenters/{dc}/urls")
@app.get("/config/{client}/urls")
def eve_urls(client: str, dc: str = "eur"):
    base, tls = "http://" + cfg["public"], "https://" + cfg["public_tls"]
    out = {name: base for name in URL_SERVICES}
    out["federation"] = tls          # https as the real one: with http the native client does not call Pandora
    out["pandora"] = tls + "/" + client
    out["status"] = "none"
    return out


@app.get("/{client}/locate")
@app.get("/locate")
def pandora_locate(request: Request, service: str = "", client: str = ""):
    if service == "alert":
        return PlainTextResponse("127.0.0.1:%d" % cfg["alert_port"])
    if service == "groupchat":   # real: Tornado over TLS on its own port (ChatLibv2 speaks TLS to it); here the HTTPS app of this process
        return PlainTextResponse(cfg["public_tls"])
    if service in LOCATE:
        # the client takes the scheme of the Pandora URL for the located host (Iris too); Java asks over http
        tls = request.url.scheme == "https"
        return PlainTextResponse(cfg["public_tls"] if tls or service != "asset" else cfg["public"])
    return PlainTextResponse("Service %s not found" % service, status_code=404)


@app.get("/assign_global_id/")
def gdid_assign(hdidfv: str = "", client_id: str = ""):
    return PlainTextResponse(store().device_id(hdidfv or client_id), media_type="text/plain")


# ------------------------------------------------------------------ Janus
@app.post("/authorize")
def janus_authorize(request: Request):
    f = form(request)
    cred, client = f.get("username", ""), f.get("client_id", "")
    if not cred.startswith("anonymous:"):
        log("janus: unsupported credential type %r" % cred[:40])
        return JSONResponse({"error": "unsupported credential"}, status_code=400)
    acc = store().login(cred, f.get("password", ""), f)
    dev = f.get("device_id", "")
    tok = tokens.make(acc, f.get("scope", ""), client, dev)
    if f.get("access_token_only") == "1":
        return Response(tok, media_type=JSON_UTF8)
    return Response(json.dumps({"access_token": tok, "token_type": "gameloft_online", "fed_id": acc["fed_id"],
                                "scope": tokens.canonical_scope(f.get("scope", "")),
                                "refresh_token": tokens.make(acc, f.get("scope", ""), client, dev, tokens.REFRESH_LIFETIME, "refresh|")},
                               separators=(",", ":")), media_type=JSON_UTF8)


@app.get("/users/me")
def janus_users_me(access_token: str = ""):
    acc, _ = account_of(access_token)
    if not acc:
        return unauthorized()
    # credentials: STRINGS "<type>:<id>" (objects crash the client, documentation/protocol.md)
    return {"account": acc["fed_id"], "credentials": [acc["credential"]], "client_ids": [], "alias": [],
            "installations": acc["installations"], "last_login": None, "is_ghost": False, "role_data": None}


@app.post("/encrypt_token")
def janus_encrypt_token(request: Request):
    tok = form(request).get("access_token", "")
    if not tokens.parse(tok):
        return unauthorized()
    return Response(tokens.encrypt(tok), media_type=JSON_UTF8)


# ------------------------------------------------------------------ Federation / Anubis: rooms on our AH server
def controller(acc, client: str, device_id: str, kind: str) -> dict:
    rid = store().new_room(acc, kind)
    lobby = tokens.make(acc, "lobby", client, device_id)
    host, port = cfg["ah_host"], cfg["ah_port"]
    return {"controller_host": host, "controller_port": port, "controller_tcp_port": port, "controller_http_port": port + 1,
            "controller_https_port": port + 2, "room_id": rid, "access_token": lobby, "encrypted_access_token": tokens.encrypt(lobby)}


@app.post("/sessions/{client}/{credential:path}")
def federation_session(client: str, credential: str, request: Request):
    f = form(request)
    acc = store().account(credential)
    if not acc or (acc["password"] and f.get("password") != acc["password"]):
        return PlainTextResponse("404 Not Found : The path '/sessions/%s/%s' was not found." % (client, credential), status_code=404)
    c = controller(acc, client, f.get("device_id", ""), "session")
    out = {k: c[k] for k in ("controller_host", "controller_port", "controller_tcp_port", "controller_http_port", "controller_https_port")}
    out.update(success=True, action="launch game", room_id=c["room_id"], access_token=c["access_token"],
               encrypted_access_token=c["encrypted_access_token"])
    return out


@app.post("/rooms/{client}/automatch/quick_join_ah")
def anubis_quick_join_ah(client: str, request: Request):
    f = form(request)
    acc, info = account_of(f.get("access_token", ""))
    if not acc:
        return unauthorized()
    c = controller(acc, client, info["device_id"], "ah")
    member = {"fed_id": acc["fed_id"], "credential": acc["credential"], "client_id": client, "name": None, "country": "US"}
    now = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime())
    out = {"automatched": True, "automatcher": "quick_join_ah", "fill": 1, "min_fill": 1, "fill_curve": 0, "relax_fill": False,
           "fill_timeout": 15, "user_args": {"country": "US"}, "creator_datacenter": "None", "automatch_launching": True,
           "members": [member], "owner": member, "name": None, "id": c["room_id"], "game_started": True, "full": True,
           "client_id": client, "created": now, "launch_date": now, "member_count": 1, "pid": str(os.getpid()),
           "server_type": f.get("server_type", "ts"), "team_room": False, "lobby_host": c["controller_host"],
           "lobby_port": c["controller_port"], "preferred_region": "default", "lobby_tcp_port": c["controller_port"],
           "lobby_http_port": c["controller_http_port"], "capacity": 1, "available_slots": 0,
           "controller_private_host": c["controller_host"], "controller_public_host": c["controller_host"]}
    out.update({k: c[k] for k in ("controller_host", "controller_tcp_port", "controller_http_port", "controller_https_port",
                                  "controller_port", "encrypted_access_token")})
    out["pport"] = c["controller_port"]
    return out


# ------------------------------------------------------------------ Osiris / Hermes
def osiris_of(acc) -> dict:
    if acc.get("osiris") is None:
        acc["osiris"] = {"name": acc["credential"].split(":", 1)[1], "created": time.time()}
    acc["osiris"]["last_time_played"] = time.time()
    return acc["osiris"]


@app.get("/accounts/me")
def osiris_account_get(access_token: str = ""):
    acc, _ = account_of(access_token)
    if not acc:
        return unauthorized()
    o = osiris_of(acc)
    store().save()
    return {"credential": acc["credential"], "name": o["name"], "avatar": "", "game": "1924", "status_line": "", "fed_id": acc["fed_id"],
            "avatar_name": None, "online": False, "seconds_since_last_status_change": None,
            "games": {"1924": {"last_time_played": o["last_time_played"]}}, "country": None, "language": None, "groups": [], "participations": []}


@app.post("/accounts/me")
def osiris_account_post(request: Request):
    f = form(request)
    acc, _ = account_of(f.get("access_token", ""))
    if not acc:
        return unauthorized()
    if f.get("name"):
        osiris_of(acc)["name"] = f["name"]
        store().save()
    return Response(b"", media_type="text/html;charset=utf-8")


@app.get("/accounts/me/requests")
@app.get("/accounts/me/connections/{kind}")
def osiris_lists(access_token: str = "", kind: str = ""):
    acc, _ = account_of(access_token)
    if not acc:
        return unauthorized()
    if acc.get("osiris") is None:
        return PlainTextResponse("404 Not Found : Account does not exist", status_code=404, media_type="text/html;charset=utf-8")
    return []


@app.get("/messages/inbox/me")
@app.get("/messages/secured/me")
def hermes_lists(access_token: str = ""):
    acc, _ = account_of(access_token)
    return [] if acc else unauthorized()


# ------------------------------------------------------------------ Seshat / Janus alias / Osiris groups (clans)
@app.post("/profiles/me/myprofile/consent")
def seshat_consent(request: Request):
    """Seshat checks the scope: the game token has no storage scope, the real server answers 403 (recorded); same rule here."""
    acc, info = account_of(form(request).get("access_token", ""))
    if not acc:
        return unauthorized()
    if not any(s in info["scope"].split() for s in ("storage", "storage_restricted", "storage_admin")):
        return PlainTextResponse("403 Forbidden : The provided access token with client_id: %s does not contain the scope required to run "
                                 "this command. One of the following scopes is required: storage storage_restricted storage_admin"
                                 % info["client_id"], status_code=403, media_type="text/html;charset=utf-8")
    acc.setdefault("seshat", {})["consent"] = form(request)
    store().save()
    return Response(b"", media_type="text/html;charset=utf-8")


@app.post("/games/mygame/alias")
def janus_alias(request: Request):
    acc, _ = account_of(form(request).get("access_token", ""))
    if not acc:
        return unauthorized()
    if not acc.get("game_alias"):
        import random
        used = {a.get("game_alias") for a in store().data["accounts"].values()}
        acc["game_alias"] = next(str(n) for n in iter(lambda: random.randint(10000, 99999), None) if str(n) not in used)
        store().save()
    return {"alias": acc["game_alias"]}


@app.get("/groups/categories/{category}/find/keyword")
def osiris_find_groups(category: str, access_token: str = "", keyword: str = ""):
    acc, _ = account_of(access_token)
    if not acc:
        return unauthorized()
    gs = social.groups(store()).values()
    return [social.group_view(store(), g) for g in gs if keyword and keyword.lower() in g["name"].lower()]


def _group(gid):
    return social.groups(store()).get(gid)


@app.get("/groups/{gid}")
def osiris_group(gid: str, access_token: str = ""):
    acc, _ = account_of(access_token)
    if not acc:
        return unauthorized()
    g = _group(gid)
    return social.group_view(store(), g) if g else PlainTextResponse("404 Not Found : Group does not exist", status_code=404)


@app.get("/groups/{gid}/members")
def osiris_group_members(gid: str, access_token: str = ""):
    acc, _ = account_of(access_token)
    g = _group(gid)
    if not acc or not g:
        return unauthorized() if not acc else PlainTextResponse("404 Not Found : Group does not exist", status_code=404)
    return [social.member(a) for a in (store().by_fed_id(f) for f in g["members"]) if a]


@app.post("/groups/{gid}/members/{credential:path}")
def osiris_group_join(gid: str, credential: str, request: Request):
    acc, _ = account_of(form(request).get("access_token", ""))
    g = _group(gid)
    who = store().account(credential)
    if not acc or not g or not who:
        return PlainTextResponse("404 Not Found", status_code=404)
    if who["fed_id"] not in g["members"]:
        g["members"].append(who["fed_id"])
        store().save()
    return PlainTextResponse("OK", media_type="text/html;charset=utf-8")


@app.get("/groups/{gid}/wall")
def osiris_wall(gid: str, access_token: str = ""):
    acc, _ = account_of(access_token)
    g = _group(gid)
    if not acc or not g:
        return unauthorized() if not acc else PlainTextResponse("404 Not Found : Group does not exist", status_code=404)
    return g["wall"][-50:]


@app.post("/groups/{gid}/wall")
def osiris_wall_post(gid: str, request: Request):
    f = form(request)
    acc, _ = account_of(f.get("access_token", ""))
    g = _group(gid)
    if not acc or not g:
        return unauthorized() if not acc else PlainTextResponse("404 Not Found : Group does not exist", status_code=404)
    import uuid as _u
    msg = {k: v for k, v in f.items() if k != "access_token"}
    msg.update(id=str(_u.uuid1()), sender=social.member(acc), created=social.fmt(time.time()))
    g["wall"].append(msg)
    store().save()
    return {"id": msg["id"]}


# ------------------------------------------------------------------ Anubis room list (no local matches yet: empty, as the real one often is)
@app.get("/rooms/{client}")
def anubis_rooms(client: str):
    return []


# ------------------------------------------------------------------ Anubis automatch (quickplayany / quickplaynewplayer), documentation/protocol.md
def _automatch(name: str, client: str, request: Request):
    """Quick match: the real one answers with a room on a game server (`mp_server`) and our player among its members. We have no match
    server: the room points at our controller (AH), the lobby side decides what happens next."""
    f = form(request)
    acc, info = account_of(f.get("access_token", ""))
    if not acc:
        return unauthorized()
    flt = {k: v[0] for k, v in parse_qs(f.get("filter", ""), keep_blank_values=True).items()}
    c = controller(acc, client, info["device_id"], "mp")
    nick = ((acc.get("osiris") or {}).get("name")) or (acc.get("profile") or {}).get("name") or ""
    score = float((acc.get("profile") or {}).get("rating", 800))
    now = time.time()
    uargs = {"name": nick, "country": "US", "matchmaking_starting_time": now, "matchmaking_score": score}
    member = dict({"fed_id": acc["fed_id"], "credential": acc["credential"], "client_id": client}, **uargs)
    cap = int(flt.get("capacity") or (70 if flt.get("_game_mode") == "BattleRoyale" else 12))
    stamp = time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(now))
    out = {"automatched": True, "automatcher": name}
    out.update({k: v for k, v in flt.items() if k.startswith("_")})
    out.update({"matchmake_score": score, "matchmake_time": now, "fill": 2, "min_fill": 1, "fill_curve": 0, "relax_fill": False,
                "fill_timeout": 15, "user_args": uargs, "creator_datacenter": "None", "automatch_launching": True, "members": [member],
                "owner": member, "name": None, "id": c["room_id"], "game_started": True, "full": False, "client_id": client,
                "created": stamp, "launch_date": stamp, "member_count": 1, "pid": str(os.getpid()), "server_type": "mp_server",
                "team_room": False, "lobby_host": c["controller_host"], "lobby_port": c["controller_port"], "preferred_region": "default",
                "lobby_tcp_port": c["controller_port"], "lobby_http_port": c["controller_http_port"], "capacity": cap,
                "available_slots": cap - 1, "controller_private_host": c["controller_host"], "controller_public_host": c["controller_host"]})
    out.update({k: c[k] for k in ("controller_host", "controller_tcp_port", "controller_http_port", "controller_https_port",
                                  "controller_port", "encrypted_access_token")})
    out["pport"] = c["controller_port"]
    log("automatch %s %s -> room %s" % (name, flt.get("_game_mode"), c["room_id"]))
    return out


@app.post("/rooms/{client}/automatch/quickplayany")
def anubis_quickplayany(client: str, request: Request):
    return _automatch("quickplayany", client, request)


@app.post("/rooms/{client}/automatch/quickplaynewplayer")
def anubis_quickplaynewplayer(client: str, request: Request):
    return _automatch("quickplaynewplayer", client, request)


# ------------------------------------------------------------------ Ads (a314 /un/index.hhh) and telemetry (etsv2 /binary), documentation/protocol.md
@app.post("/un/index.hhh")
def ads_index(request: Request, event: str = "", ad: str = ""):
    """Ad network. The request body (`data=`) is encrypted by the client. `event=init` -> the locations table (kept as data/ads_config.json,
    our own customID); `ad=...` -> no content (the real one often had none; the client then shows nothing)."""
    if event == "init":
        with open(os.path.join(cfg["data_dir"], "ads_config.json")) as f:
            conf = json.load(f)
        st = store().data
        if "ads_custom_id" not in st:
            st["ads_custom_id"] = hashlib.md5(os.urandom(16)).hexdigest()
            store().save()
        out = {"ucd": conf["ucd"], "customID": st["ads_custom_id"], "timeouts": conf["timeouts"], "locations": conf["locations"]}
        return Response(json.dumps(out, separators=(",", ":")), headers={"Content-Type": "text/html; charset=UTF-8"})
    return Response('{"action":"exit","error":"There is no content available"}', headers={"Content-Type": "text/html; charset=UTF-8"})


@app.post("/binary")
def etsv2_binary():
    """GLOT telemetry (`application/gl-stream`): accepted, nothing to answer (the real one: 200, empty body)."""
    return Response(b"", media_type=None)


# ------------------------------------------------------------------ Chat (documentation/protocol.md, server/mc5/chat.py)
_HUB = []


def hub() -> "chat.Hub":
    if not _HUB:
        _HUB.append(chat.Hub(store()))
    return _HUB[0]


def _chat_urls(kind: str, key: str, fed_id: str, lang: str = "") -> dict:
    """Real: `listen_url` is http on its own port, `https_listen_url` https. The client talks TLS to whichever it uses (27.10: TLS sent to our plain :18080 gave
    "Invalid HTTP request"), so both point at the HTTPS app of this process."""
    path = "/v1/chat/%s/%s" % (kind, key)
    q = "?game=1924&memberid=%s&language=%s" % (fed_id, lang or "en")
    url = "https://%s%s" % (cfg["public_tls"], path)
    return {"cmd_url": url, "listen_url": url + q, "status": "ok", "https_listen_url": url + q}


def _chat_json(obj) -> Response:
    """As Tornado wrote it: `application/json; charset=UTF-8`, json.dumps with default separators (the client of the chat is strict about the content type?)."""
    return Response(json.dumps(obj), media_type="application/json; charset=UTF-8")


@app.post("/chat/channels/{name}/subscribe")
def chat_subscribe_channel(name: str, request: Request):
    f = form(request)
    acc, _ = account_of(f.get("access_token", ""))
    if not acc:
        return unauthorized()
    lang = f.get("language", "en")
    return _chat_json(_chat_urls("channels", "%s.%s" % (name, lang), acc["fed_id"], lang))


@app.post("/chat/rooms/{rid}/subscribe")
def chat_subscribe_room(rid: str, request: Request):
    f = form(request)
    acc, _ = account_of(f.get("access_token", ""))
    if not acc:
        return unauthorized()
    return _chat_json(_chat_urls("rooms", rid, acc["fed_id"], f.get("language", "en")))


def _chat_listen(key: str):
    return StreamingResponse(hub().listen(key), headers={"Content-Type": "text/event-stream"})   # no charset suffix, as recorded


def _chat_send(key: str, request: Request):  # called from async routes: the hub queues belong to the event loop
    f = form(request)
    acc, _ = account_of(f.get("access_token", ""))
    if not acc:
        return unauthorized()
    try:
        nick = json.loads(f.get("user", "{}")).get("nickname")
    except ValueError:
        nick = None
    nick = nick or ((acc.get("osiris") or {}).get("name")) or ""
    attrs = {k: v for k, v in f.items() if k not in ("access_token", "msg", "user")}
    msg = hub().post(key, attrs, f.get("msg", ""), {"credential": acc["credential"], "nickname": nick})
    log("chat %s <%s> %s" % (key, nick, f.get("msg", "")[:60]))
    return Response(json.dumps({"msg": msg}, separators=(",", ":")), headers={"Content-Type": "text/html; charset=UTF-8"})


@app.get("/v1/chat/channels/{key}")
async def chat_listen_channel(key: str):
    return _chat_listen("channels/" + key)


@app.get("/v1/chat/rooms/{rid}")
async def chat_listen_room(rid: str):
    return _chat_listen("rooms/" + rid)


@app.post("/v1/chat/channels/{key}")
async def chat_send_channel(key: str, request: Request):
    return _chat_send("channels/" + key, request)


@app.post("/v1/chat/rooms/{rid}")
async def chat_send_room(rid: str, request: Request):
    return _chat_send("rooms/" + rid, request)


# ------------------------------------------------------------------ Iris
_HASH: Dict[tuple, str] = {}


def iris_file(name: str) -> str:
    base = os.path.basename(name)
    m = re.match(r"^bald_.+?___(index|toc|hashes|version)$", base)  # client asks `bald_android_astc_h___index`, stored `bald___index___.txt`
    if m:
        base = "bald___%s___" % m.group(1)
    for root in cfg["iris_dirs"]:
        for cand in (base, base + ".dcmp", base + ".txt"):
            p = os.path.join(root, cand)
            if os.path.isfile(p):
                return p
    return ""


def sha256_of(path: str) -> str:
    st = os.stat(path)
    k = (path, st.st_size, st.st_mtime)
    if k not in _HASH:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        _HASH[k] = h.hexdigest()
    return _HASH[k]


IRIS_CACHED_ONLY = ("behavioral.json", "compliancy.json")  # content unknown: the client keeps its cached copy (304 on If-None-Match)


@app.api_route("/assets/{name:path}", methods=["GET", "HEAD"])
def iris_asset(name: str, request: Request):
    parts = name.split("/")
    if len(parts) > 1 and ":" in parts[0]:
        parts = parts[1:]                       # /assets/<client_id>/<asset>[/metadata/hash|/hash|/size]
    asset, sub = parts[0], "/".join(parts[1:])
    if asset in IRIS_CACHED_ONLY:
        inm = request.headers.get("if-none-match")
        return Response(status_code=304, headers={"ETag": inm}) if inm else JSONResponse({}, headers={"ETag": '"mc5-empty"'})
    path = iris_file(asset)
    if not path:
        return Response(b"", status_code=404, media_type="text/html;charset=utf-8")
    size, digest = os.path.getsize(path), sha256_of(path)
    if sub in ("metadata/hash", "hash"):
        return Response(json.dumps({"hash": digest}), media_type="application/json;charset=utf-8")
    if sub == "size":
        return {"size": size}
    et = '"%s"' % digest
    hdr = {"ETag": et, "asset-hash": digest, "asset_hash": digest, "Accept-Ranges": "bytes"}
    if request.headers.get("if-none-match") == et:
        return Response(status_code=304, headers=hdr)
    start, end = 0, size - 1
    rng, q = request.headers.get("range", ""), request.query_params
    if rng.startswith("bytes="):
        a, _, b = rng[6:].partition("-")
        start, end = int(a or 0), int(b) if b else size - 1
    elif "from_offset" in q or "to_offset" in q:
        start = int(q.get("from_offset", 0))
        end = int(q["to_offset"]) - 1 if "to_offset" in q else size - 1
    end = min(end, size - 1)
    status = 206 if (start, end) != (0, size - 1) else 200
    if status == 206:
        hdr["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
    if request.method == "HEAD":
        hdr["Content-Length"] = str(end - start + 1)
        return Response(status_code=status, headers=hdr, media_type="binary/octet-stream")
    with open(path, "rb") as f:
        f.seek(start)
        data = f.read(end - start + 1)
    return Response(data, status_code=status, headers=hdr, media_type="binary/octet-stream")


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "HEAD"])
def fallback(path: str):
    """Unknown request: logged (UNKNOWN in the server log), empty JSON so the client does not stall."""
    log("UNKNOWN /%s" % path)
    return {}
