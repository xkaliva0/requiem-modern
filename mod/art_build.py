"""Write a Requiem ReqArtD3.art/.dat pair. Each entry is u32 decoded size, u32 0, u32 stream size, then a PKWARE DCL
stream made of literals only (binary mode, 4 KB dictionary): 9 bits per byte, no compression search, but valid for
the game's explode() and for blast.py. Every 8 input bytes become exactly 9 output bytes, packed with byte planes.
Usage as a module: build(entries, out_dir) with entries = {index: decoded_bytes}."""
import os, struct
import blast

_SHL = [bytes(((b << (j + 1)) & 0xFF) for b in range(256)) for j in range(8)]
_SHR = [bytes((b >> (8 - j)) for b in range(256)) for j in range(9)]

def _or(a, b):
    return (int.from_bytes(a, "little") | int.from_bytes(b, "little")).to_bytes(len(a), "little")

def _code_bits(h, s):
    """Bits (in read order) that blast's decode() turns into symbol s: canonical code, MSB first, inverted."""
    count, sym = h
    code = first = index = 0
    for ln in range(1, 14):
        c = count[ln]
        if s in sym[index:index + c]:
            v = first + sym[index:index + c].index(s)
            return [1 - ((v >> (ln - 1 - k)) & 1) for k in range(ln)]
        index += c; first += c; first <<= 1
    raise ValueError(s)

_END = [1] + _code_bits(blast._LEN, 15) + [(255 >> k) & 1 for k in range(8)]   # length 519 = end of stream

def implode_literal(data):
    g = len(data) // 8; body = data[:g * 8]
    out = bytearray(9 * g)
    for j in range(9):
        lo = body[j::8].translate(_SHL[j]) if j < 8 else bytes(g)
        hi = body[j - 1::8].translate(_SHR[j]) if j > 0 else bytes(g)
        out[j::9] = _or(lo, hi)
    bits = []
    for b in data[g * 8:]: bits += [0] + [(b >> k) & 1 for k in range(8)]
    bits += _END
    bits += [0] * (-len(bits) % 8)
    out += bytes(sum(bits[i + k] << k for k in range(8)) for i in range(0, len(bits), 8))
    return b"\x00\x06" + bytes(out)

def build(entries, out_dir, slots=4001):
    os.makedirs(out_dir, exist_ok=True)
    offs = [0xFFFFFFFF] * slots
    with open(os.path.join(out_dir, "ReqArtD3.art"), "wb") as f:
        for i in sorted(entries):
            raw = entries[i]; z = implode_literal(raw)
            offs[i] = f.tell(); f.write(struct.pack("<3I", len(raw), 0, len(z)) + z)
    open(os.path.join(out_dir, "ReqArtD3.dat"), "wb").write(struct.pack(f"<{slots}I", *offs))

if __name__ == "__main__":
    import random
    for n in (0, 1, 7, 8, 9, 17, 1000, 17426):
        d = bytes(random.randrange(256) for _ in range(n))
        assert blast.blast(implode_literal(d)) == d, n
    print("round trip ok")
