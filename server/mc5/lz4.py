"""LZ4 block format (no frame), as used inside AH frames: `u32 BE compressed length + LZ4 block`.

pack() is a small compressor in pure Python (hash chains; no compression library: the server must also run inside the bridge APK):
needed because an AH frame length is 16 bits and the CRM config is ~500 KB of JSON. unpack() is a full block decoder (for tests and the seed tool).
"""


def pack(data: bytes) -> bytes:
    """One sequence with all bytes as literals (allowed as the last sequence of a block)."""
    n = len(data)
    if n < 15:
        return bytes([n << 4]) + data
    ext = bytearray()
    rest = n - 15
    while rest >= 255:
        ext.append(255)
        rest -= 255
    ext.append(rest)
    return bytes([0xF0]) + bytes(ext) + data


def _seq(out: bytearray, lit: bytes, mlen: int, off: int):
    """Append one sequence: literals, then a match of mlen bytes at distance off (mlen 0 = last sequence)."""
    ll = len(lit)
    ml = mlen - 4 if mlen else 0
    out.append((min(ll, 15) << 4) | (min(ml, 15) if mlen else 0))
    if ll >= 15:
        r = ll - 15
        while r >= 255:
            out.append(255)
            r -= 255
        out.append(r)
    out += lit
    if mlen:
        out += off.to_bytes(2, "little")
        if ml >= 15:
            r = ml - 15
            while r >= 255:
                out.append(255)
                r -= 255
            out.append(r)


def compress(data: bytes, depth: int = 64) -> bytes:
    """LZ4 block compressor with hash chains (longest of up to `depth` earlier 4-byte matches). Needed for bodies over 64 KB:
    an AH frame length is 16 bits (the CRM config is ~500 KB of JSON). Block rules kept: the last 5 bytes are literals,
    no match starts in the last 12 bytes."""
    n = len(data)
    out = bytearray()
    head = {}
    prev = [-1] * n
    anchor = i = 0
    limit = n - 12
    end = n - 5

    def insert(k):
        key = data[k:k + 4]
        prev[k] = head.get(key, -1)
        head[key] = k

    def best(i):
        cand = head.get(data[i:i + 4], -1)
        best_len, best_off, tries = 0, 0, depth
        while cand >= 0 and i - cand <= 0xFFFF and tries:
            if data[cand + best_len:cand + best_len + 1] == data[i + best_len:i + best_len + 1]:
                m = 4
                while i + m < end and data[cand + m] == data[i + m]:
                    m += 1
                if m > best_len:
                    best_len, best_off = m, i - cand
            cand = prev[cand]
            tries -= 1
        return best_len, best_off

    while i < limit:
        mlen, moff = best(i)
        insert(i)
        if mlen >= 4 and i + 1 < limit:
            nlen, noff = best(i + 1)   # lazy matching: a longer match one byte later wins
            if nlen > mlen + 1:
                i += 1
                insert(i)
                mlen, moff = nlen, noff
        if mlen >= 4:
            _seq(out, data[anchor:i], mlen, moff)
            for k in range(i + 1, min(i + mlen, limit)):
                insert(k)
            i += mlen
            anchor = i
        else:
            i += 1
    _seq(out, data[anchor:], 0, 0)
    return bytes(out)


def unpack(src: bytes) -> bytes:
    i, n, out = 0, len(src), bytearray()
    while i < n:
        t = src[i]
        i += 1
        lit = t >> 4
        if lit == 15:
            while True:
                b = src[i]
                i += 1
                lit += b
                if b != 255:
                    break
        out += src[i:i + lit]
        i += lit
        if i >= n:
            break
        off = src[i] | (src[i + 1] << 8)
        i += 2
        m = t & 15
        if m == 15:
            while True:
                b = src[i]
                i += 1
                m += b
                if b != 255:
                    break
        m += 4
        if off == 0 or off > len(out):
            raise ValueError("lz4: bad offset")
        start = len(out) - off
        for k in range(m):
            out.append(out[start + k])
    return bytes(out)


def pack_sized(data: bytes) -> bytes:
    """`u32 BE length of the block` + block (the layout inside AH frames)."""
    blk = pack(data) if len(data) < 4096 else compress(data)
    return len(blk).to_bytes(4, "big") + blk


def unpack_sized(payload: bytes) -> bytes:
    n = int.from_bytes(payload[:4], "big")
    if n != len(payload) - 4:
        raise ValueError("lz4: length %d != %d" % (n, len(payload) - 4))
    return unpack(payload[4:])
