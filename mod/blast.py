"""PKWARE Data Compression Library 'explode' (implode decompressor), a Python port of zlib's contrib/blast/blast.c
(Mark Adler, zlib licence). Used by Requiem's ReqArtD3.art texture archive. Usage: blast(data) -> bytes."""

def _construct(rep):
    """Build (count per length, symbols) from blast.c's compact repeat-encoded code lengths."""
    lengths = []
    for b in rep:
        n, ln = (b >> 4) + 1, b & 15
        lengths += [ln] * n
    count = [0] * 14
    for ln in lengths: count[ln] += 1
    offs = [0] * 14
    for i in range(1, 13): offs[i + 1] = offs[i] + count[i]
    sym = [0] * len(lengths)
    for s, ln in enumerate(lengths):
        if ln: sym[offs[ln]] = s; offs[ln] += 1
    return count, sym

_LITLEN = bytes([11, 124, 8, 7, 28, 7, 188, 13, 76, 4, 10, 8, 12, 10, 12, 10, 8, 23, 8, 9, 7, 6, 7, 8, 7, 6, 55, 8, 23, 24,
                 12, 11, 7, 9, 11, 12, 6, 7, 22, 5, 7, 24, 6, 11, 9, 6, 7, 22, 7, 11, 38, 7, 9, 8, 25, 11, 8, 11, 9, 12, 8,
                 12, 5, 38, 5, 38, 5, 11, 7, 5, 6, 21, 6, 10, 53, 8, 7, 24, 10, 27, 44, 253, 253, 253, 252, 252, 252, 13, 12,
                 45, 12, 45, 12, 61, 12, 45, 44, 173])
_LENLEN = bytes([2, 35, 36, 53, 38, 23])
_DISTLEN = bytes([2, 20, 53, 230, 247, 151, 248])
_BASE = [3, 2, 4, 5, 6, 7, 8, 9, 10, 12, 16, 24, 40, 72, 136, 264]
_EXTRA = [0, 0, 0, 0, 0, 0, 0, 0, 1, 2, 3, 4, 5, 6, 7, 8]
_LIT, _LEN, _DIST = _construct(_LITLEN), _construct(_LENLEN), _construct(_DISTLEN)

def blast(data):
    pos = 0; bitbuf = 0; bitcnt = 0; out = bytearray()
    def bits(need):
        nonlocal pos, bitbuf, bitcnt
        val = bitbuf
        while bitcnt < need:
            if pos >= len(data): raise EOFError("compressed data ended early")
            val |= data[pos] << bitcnt; pos += 1; bitcnt += 8
        bitbuf = val >> need; bitcnt -= need
        return val & ((1 << need) - 1)
    def decode(h):
        nonlocal pos, bitbuf, bitcnt
        count, sym = h
        code = first = index = 0
        for ln in range(1, 14):
            code |= (bits(1) ^ 1)          # codes are stored bit-inverted
            c = count[ln]
            if code < first + c: return sym[index + (code - first)]
            index += c; first += c; first <<= 1; code <<= 1
        raise ValueError("bad code")
    lit = bits(8)
    if lit > 1: raise ValueError("bad literal flag")
    dictbits = bits(8)
    if not 4 <= dictbits <= 6: raise ValueError("bad dictionary size")
    while True:
        if bits(1):
            symbol = decode(_LEN)
            length = _BASE[symbol] + bits(_EXTRA[symbol])
            if length == 519: break        # end code
            sh = 2 if length == 2 else dictbits
            dist = (decode(_DIST) << sh) + bits(sh) + 1
            if dist > len(out): raise ValueError("distance too far back")
            for _ in range(length): out.append(out[-dist])
        else:
            out.append(decode(_LIT) if lit else bits(8))
    return bytes(out)
