"""Osiris social objects shared by the HTTP services and the AH server: member records and groups (clans).

A clan is created/edited by the AH frame `76` (answer `77`), then read through Osiris `/groups/<id>`, `/members`, `/wall`
(documentation/protocol.md). Shapes follow the recorded answers of the real Osiris; contents come from our store.
"""
import time
import uuid

GROUP_CATEGORY = "mc5_clan_v01"


def fmt(t: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%SZ", time.gmtime(t))


def member(acc: dict, online: bool = True) -> dict:
    """Osiris member record (as in /groups/<id>/members)."""
    o = acc.get("osiris") or {}
    prof = acc.get("profile") or {}
    last = acc.get("last_login") or time.time()
    return {"credential": acc["credential"], "name": (prof.get("osiris_info") or {}).get("display_name") or o.get("name", ""),
            "avatar": "", "game": "1924", "status_line": "", "fed_id": acc["fed_id"], "avatar_name": None, "online": online,
            "seconds_since_last_status_change": int(time.time() - last), "status_last_update": fmt(last),
            "status": "online" if online else "offline", "last_online": fmt(last),
            "_killsig_color": str(prof.get("killsig_color", 12722475)), "_killsig_id": prof.get("killsig_id", "default_killsig_01"),
            "_score": str(prof.get("rating", 800)), "_xp": str((prof.get("_inventory") or {}).get("xp", 0))}


def groups(store) -> dict:
    return store.data.setdefault("groups", {})


def group_view(store, g: dict) -> dict:
    """Full group object (Osiris /groups/<id> and the `77` answer)."""
    accs = [store.by_fed_id(f) for f in g["members"]]
    accs = [a for a in accs if a]
    owners = [a for a in accs if a["fed_id"] in g["owners"]]
    out = {"name": g["name"], "category": GROUP_CATEGORY, "member_limit": 30, "member_count": len(accs),
           "owner": member(owners[0]) if owners else None, "membership": "open", "edit_permissions": "owner", "type": "clan",
           "visibility": None, "id": g["id"], "members": [member(a) for a in accs], "owners": [member(a) for a in owners],
           "active_clan_label": False, "active_clan_threshold": 10, "active_member_count": len(accs), "active_member_threshold": 86400,
           "activity_as_recommendation": False, "avatar": None, "criteria": [], "currency": 0, "days_offline_before_demotion": 0}
    out.update(g["attrs"])
    return out


def save_clan(store, acc: dict, attrs: dict) -> dict:
    """Create the player's clan or update it (the same owner edits the existing one)."""
    gs = groups(store)
    g = next((x for x in gs.values() if acc["fed_id"] in x["owners"]), None)
    if g is None:
        g = {"id": str(uuid.uuid1()), "name": attrs.get("name", ""), "owners": [acc["fed_id"]], "members": [acc["fed_id"]],
             "attrs": {}, "wall": [], "created": time.time()}
        gs[g["id"]] = g
    g["name"] = attrs.get("name", g["name"])
    league = (acc.get("profile") or {}).get("league_info_user") or {"index": 0, "last_season": -1, "last_year": -1}
    g["attrs"].update({"_league_info": league, "_rating": g["attrs"].get("_rating", 1000), "description": attrs.get("description", "")})
    for k in ("_logo", "_logo_clr_prim", "_logo_clr_sec", "_min_join_value"):
        if k in attrs:
            g["attrs"][k] = str(attrs[k])
    store.save()
    return g
