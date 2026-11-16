"""Janus access tokens in the format of the real server (documentation/protocol.md):

    <fed_id>,<scope>,<client_id>,<expiry>,<credential>,<device_id>,<dc>|<signature>

The signature is ours (HMAC, the client does not check it). encrypt()/decrypt() give the opaque `encrypt_token` /
`encrypted_access_token` value the client hands to the AH server, which verifies it with decrypt().
"""
import base64
import hashlib
import hmac
import os
import time

DC = "local"
LIFETIME = 14400            # 4 h, as the real Janus
REFRESH_LIFETIME = 35 * 86400
# canonical scope order of the real Janus; an unknown scope name crashes the client (documentation/protocol.md)
SCOPE_ORDER = ["leaderboard_ro", "lobby", "alert", "auth", "social", "chat", "session", "message", "tracking_bi", "storage_ro", "config"]

_key = None


def key(path: str) -> bytes:
    """Server secret, created once next to the state file."""
    global _key
    if _key is None:
        if os.path.isfile(path):
            _key = open(path, "rb").read()
        else:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
            _key = os.urandom(32)
            with open(path, "wb") as f:
                f.write(_key)
    return _key


def canonical_scope(scope: str) -> str:
    asked = scope.split()
    known = [s for s in SCOPE_ORDER if s in asked]
    return " ".join(known + [s for s in asked if s not in SCOPE_ORDER])


def make(acc: dict, scope: str, client_id: str, device_id: str, lifetime: int = LIFETIME, prefix: str = "") -> str:
    exp = "%.6f" % round(time.time() + lifetime, 3)
    body = ",".join([acc["fed_id"], canonical_scope(scope), client_id, exp, acc["credential"], device_id or "", DC])
    sig = hmac.new(_key, (prefix + body).encode(), hashlib.md5).hexdigest()
    return prefix + body + "|" + sig


def parse(token: str):
    """-> dict of the fields if the signature is ours, else None."""
    if "|" not in token:
        return None
    body, sig = token.rsplit("|", 1)
    if not hmac.compare_digest(hmac.new(_key, body.encode(), hashlib.md5).hexdigest(), sig):
        return None
    if body.startswith("refresh|"):
        body = body[len("refresh|"):]
    p = body.split(",")
    if len(p) != 7:
        return None
    return {"fed_id": p[0], "scope": p[1], "client_id": p[2], "expiry": float(p[3]), "credential": p[4], "device_id": p[5], "dc": p[6]}


def encrypt(token: str) -> str:
    raw = token.encode()
    mac = hmac.new(_key, b"enc" + raw, hashlib.sha256).digest()[:16]
    stream = hashlib.sha256(_key + mac).digest()
    ks = (stream * (len(raw) // len(stream) + 1))[:len(raw)]
    return base64.b64encode(mac + bytes(a ^ b for a, b in zip(raw, ks))).decode()


def decrypt(value: str):
    try:
        blob = base64.b64decode(value)
    except Exception:
        return None
    mac, enc = blob[:16], blob[16:]
    stream = hashlib.sha256(_key + mac).digest()
    ks = (stream * (len(enc) // len(stream) + 1))[:len(enc)]
    raw = bytes(a ^ b for a, b in zip(enc, ks))
    if not hmac.compare_digest(hmac.new(_key, b"enc" + raw, hashlib.sha256).digest()[:16], mac):
        return None
    return raw.decode()
