#!/usr/bin/env python3
"""Move a player recorded against the real servers (record mode) to the local server: account (credential + password + device from the
last Janus authorize), the last full profile the real AH sent, and only the mission results sent AFTER that profile (the profile
already contains the earlier ones; applying them again counted xp and stats twice). A result after the last profile is applied like
the local AH does, with the level from the client's last `10` (level start).
Stop the server first (it keeps the state in memory).
Run: .venv/bin/python -I tools/import_from_trace.py work/real/trace_mission1 [work/state/mc5_state.json]
"""
import json
import os
import sys
from urllib.parse import parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "server"))
from mc5 import ahproto as P, lz4  # noqa: E402
from mc5.ah import apply_result  # noqa: E402
from mc5.store import Store  # noqa: E402

trace = sys.argv[1]
state = sys.argv[2] if len(sys.argv) > 2 else os.path.join(ROOT, "work", "state", "mc5_state.json")
auth = None
for line in open(os.path.join(trace, "http.jsonl")):
    r = json.loads(line)
    if r["url"].endswith("/authorize") and r.get("status") == 200 and "scope=alert" in (r.get("req_body") or ""):
        auth = {k: v[0] for k, v in parse_qs(r["req_body"]).items()}
# only frames of AH connections opened by THIS credential (the trace can hold other players, e.g. an older install resending its result)
profile, results, buf, owner, level = None, [], {"c2s": b"", "s2c": b""}, None, None
for line in open(os.path.join(trace, "tcp.jsonl")):
    r = json.loads(line)
    if r.get("kind") != "ah":
        continue
    if r.get("event"):
        if str(r["event"]).startswith("eof"):
            buf, owner = {"c2s": b"", "s2c": b""}, None
        continue
    buf[r["dir"]] += bytes.fromhex(r["hex"])
    used = 0
    for t, p in P.split_frames(buf[r["dir"]]):
        used += len(p) + (0 if t == -1 else 3)
        if t == -1 and r["dir"] == "c2s":
            owner = json.loads(p).get("username")
        if owner != auth["username"]:
            continue
        if r["dir"] == "s2c" and t == P.S_PROFILE:
            profile, results = json.loads(lz4.unpack_sized(p)), []
        if r["dir"] == "c2s" and t == P.C_LEVEL:
            level = json.loads(P.read_s16(p, 0)[0])
        if r["dir"] == "c2s" and t == P.C_RESULT:
            results.append((p, level))
            level = None        # a re-sent `11` (after a reconnect) has no level start of its own
    buf[r["dir"]] = buf[r["dir"]][used:]
if profile is None:
    sys.exit("no authorize or no profile in %s" % trace)
store = Store(state)
acc = store.login(auth["username"], auth.get("password", ""), auth)
acc["profile"] = profile
acc.setdefault("ah", {})["rest_done"] = True
applied = 0
for p, lv in results:
    if not profile.get("current_mission") and lv:
        profile["current_mission"] = {"level": lv.get("level"), "node": lv.get("node")}
    applied += apply_result(acc, p) is not None
store.save()
print("imported %s: profile keys %d, results after the last profile %d (applied %d), xp %s" % (
    auth["username"][:40], len(profile), len(results), applied, profile.get("_inventory", {}).get("xp")))
