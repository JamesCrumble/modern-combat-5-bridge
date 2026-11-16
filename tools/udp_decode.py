#!/usr/bin/env python3
"""Decodes the recorded battle UDP stream (kind `udp:<port>` in a trace's tcp.jsonl) into messages (documentation/protocol.md).

A datagram is a chain of messages: u32 BE length (counts itself) + 9 header bytes + u8 type + payload.
  python3 tools/udp_decode.py work/real/trace_full1/tcp.jsonl              -> text dump on stdout
  python3 tools/udp_decode.py work/real/trace_full1/tcp.jsonl --stats      -> per direction/type statistics
"""
import argparse
import collections
import json
import sys


def load(path, kind=None):
    rows = []
    with open(path) as f:
        for line in f:
            try:
                r = json.loads(line)
            except ValueError:
                continue
            k = r.get("kind", "")
            if k.startswith("udp:") and (kind is None or k == kind):
                rows.append(r)
    return rows


def split(data):
    """Messages of one datagram: [(header9, type, payload)]; raises ValueError when the chain does not close exactly."""
    out, o = [], 0
    while o < len(data):
        n = int.from_bytes(data[o:o + 4], "big")
        if n < 14 or o + n > len(data):
            raise ValueError("bad length %d at %d of %d" % (n, o, len(data)))
        body = data[o + 4:o + n]
        out.append((body[:9], body[9], body[10:]))
        o += n
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("trace")
    ap.add_argument("--kind")
    ap.add_argument("--stats", action="store_true")
    a = ap.parse_args()
    rows = load(a.trace, a.kind)
    if not rows:
        sys.exit("no udp records")
    t0 = rows[0]["t"]
    stats = collections.defaultdict(lambda: [0, 0, None])
    for i, r in enumerate(rows):
        d = r["dir"][0]
        try:
            msgs = split(bytes.fromhex(r["hex"]))
        except ValueError as e:
            print("dg%d %s BAD: %s" % (i, d, e))
            continue
        for h, t, p in msgs:
            s = stats[(d, t)]
            s[0] += 1
            s[1] += len(p)
            s[2] = s[2] or p[:24].hex(" ")
            if not a.stats:
                print("%8.3f %s dg%-5d rel=%d h1=%02x ack=%02x%02x bits=%s type=%02x len=%-3d %s" % (
                    r["t"] - t0, d, i, h[0], h[1], h[2], h[3], h[4:9].hex(), t, len(p), p[:48].hex(" ")))
    if a.stats:
        for (d, t), (n, size, ex) in sorted(stats.items(), key=lambda x: (x[0][0], -x[1][0])):
            print("%s type %02x  n=%-5d avg payload %6.1f  e.g. %s" % (d, t, n, size / n, ex))


if __name__ == "__main__":
    main()
