"""Persistent server state: devices, accounts, Osiris profiles, rooms and AH player profiles.

One JSON file (default work/state/mc5_state.json, `--state` / MC5_STATE). Every service reads and writes the same state, so the HTTP and
HTTPS listeners, the alert socket and the AH server live in one process (server/mc5server.py).
"""
import json
import os
import random
import threading
import time
import uuid


class Store:
    def __init__(self, path: str):
        self.path = path
        self.lock = threading.RLock()
        self.data = {"devices": {}, "accounts": {}, "rooms": {}}
        if os.path.isfile(path):
            with open(path) as f:
                self.data.update(json.load(f))
        self._dirty = False

    def save(self):
        with self.lock:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.path)
            self._mirror()

    def _mirror(self):
        """Bridge: a copy of the state in the shared folder (MC5_STATE_MIRROR) survives an uninstall of the app; at most every 10 s."""
        dst = os.environ.get("MC5_STATE_MIRROR")
        if not dst or time.time() - getattr(self, "_mirrored", 0) < 10:
            return
        self._mirrored = time.time()
        try:
            import shutil
            shutil.copyfile(self.path, dst + ".tmp")
            os.replace(dst + ".tmp", dst)
        except OSError:
            pass

    # --- GDID: one 19-digit device id per hdidfv ---
    def device_id(self, hdidfv: str) -> str:
        with self.lock:
            d = self.data["devices"]
            if hdidfv not in d:
                d[hdidfv] = str(random.randint(10 ** 18, 9 * 10 ** 18))
                self.save()
            return d[hdidfv]

    # --- Janus accounts (key: credential "anonymous:<b64>") ---
    def account(self, credential: str):
        return self.data["accounts"].get(credential)

    def login(self, credential: str, password: str, device: dict) -> dict:
        """Anonymous login: the first authorize creates the account with this password (documentation/protocol.md)."""
        with self.lock:
            acc = self.data["accounts"].get(credential)
            if acc is None:
                acc = {"fed_id": str(uuid.uuid1()), "credential": credential, "password": password, "created": time.time(),
                       "installations": [], "osiris": None, "profile": None, "alias": None}
                self.data["accounts"][credential] = acc
            elif password and acc["password"] != password:
                acc["password_mismatch"] = time.time()  # not seen in the recordings; logged, login still allowed
            if device.get("device_id"):
                inst = {"carrier": None, "language": device.get("device_language"), "country": device.get("device_country"),
                        "download_code": None, "model": device.get("device_model"), "firmware": None,
                        "resolution": device.get("device_resolution"), "device_id": device["device_id"]}
                acc["installations"] = [i for i in acc["installations"] if i["device_id"] != inst["device_id"]] + [inst]
            acc["last_login"] = time.time()
            self.save()
            return acc

    def by_fed_id(self, fed_id: str):
        for acc in self.data["accounts"].values():
            if acc["fed_id"] == fed_id:
                return acc
        return None

    # --- Federation / Anubis rooms ---
    def new_room(self, acc: dict, kind: str) -> str:
        with self.lock:
            rid = str(uuid.uuid1())
            self.data["rooms"][rid] = {"fed_id": acc["fed_id"], "kind": kind, "created": time.time()}
            # old rooms are of no use: keep the last few per account
            mine = sorted((r for r in self.data["rooms"].items() if r[1]["fed_id"] == acc["fed_id"]), key=lambda r: r[1]["created"])
            for old, _ in mine[:-4]:
                del self.data["rooms"][old]
            self.save()
            return rid

    def room(self, rid: str):
        return self.data["rooms"].get(rid)
