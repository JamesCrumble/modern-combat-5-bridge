#!/usr/bin/env python3
"""server-data/ah/campaign.json from client memory (documentation/protocol.md, «Главы кампании»; documentation/development.md):

  campdump.txt   output of `run-as <pkg> ./campdump <pid>` (tools/campdump.c): chapters -> locations (type 0 = story) -> mission nodes
  xp_dump.txt    output of `run-as <pkg> ./ptrace_log <pid> libMC5.so 798b40:0:x` while the chapters screen is open: the XP table
                 (pairs u32 threshold, u32 id; the level is the number of thresholds <= xp)

Run: python3 tools/mk_campaign_json.py campdump.txt xp_dump.txt server/data/ah/campaign.json
"""
import json
import re
import struct
import sys


def campaign(path):
    chapters, cur = {}, None
    for line in open(path):
        m = re.match(r"entry chapter=(\d+) type=(\d+) .* missions=(\d+)", line)
        if m:
            cur = (int(m[1]), int(m[2]))
            continue
        m = re.match(r"\s+mission (\S+) node=(\d+)", line)
        if m and cur:
            chapters.setdefault(cur[0], {}).setdefault(cur[1], []).append([m[1], int(m[2])])
    return chapters


def xp_levels(path):
    line = next(l for l in open(path) if " bp0 " in l)
    b = bytes.fromhex(line.split()[3])
    th = []
    for i in range(0, len(b) - 7, 8):
        x, _ = struct.unpack("<II", b[i:i + 8])
        if th and x <= th[-1]:
            break
        th.append(x)
    return th


def main():
    camp, xp, out = sys.argv[1:4]
    ch = campaign(camp)
    data = {
        "_source": "libMC5.so 6.0.12a memory: campaign object **(base+0x1b9aed8), entries +0x30 (0x48 B: chapter, type 0 = story, location -> "
                   "missions +0x88, node +0x38); xp_levels: table at +0x108 of the 0x4e5f58 singleton (level = number of thresholds <= xp)",
        "story_nodes": {str(c): [n for _, n in ch[c].get(0, [])] for c in sorted(ch)},
        "nodes": {str(c): {str(t): v for t, v in ch[c].items()} for c in sorted(ch)},
        "xp_levels": xp_levels(xp),
    }
    json.dump(data, open(out, "w"), indent=1)
    print({k: len(v) for k, v in data["story_nodes"].items()}, len(data["xp_levels"]), "levels")


if __name__ == "__main__":
    main()
