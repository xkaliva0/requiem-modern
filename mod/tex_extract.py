"""Extract Requiem's D3D textures (Art\\D3D\\ReqArtD3.art + .dat, read from the TEST COPY) to PNG.
Entry: u32 decoded size, u32 0, u32 compressed size, PKWARE DCL stream (blast.py). Decoded: u16 w, u16 h, ...,
byte +0xe = bytes per pixel, 256 x RGBA palette at +0x12, pixels at +0x412 (8-bit indices or 16-bit words).
Usage: py tex_extract.py OUTDIR [index ...]   -> OUTDIR\\NNNN.png and OUTDIR\\index.json (header fields per texture)"""
import json, os, struct, sys
from PIL import Image
import blast

LAB = os.environ.get("REQUIEM_LAB", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root by default
ART = os.environ.get("REQUIEM_ART", os.path.join(LAB, "testgame", "Art", "D3D", "orig_src"))   # untouched copy of the original archive

def entries():
    d = open(os.path.join(ART, "ReqArtD3.dat"), "rb").read(); a = open(os.path.join(ART, "ReqArtD3.art"), "rb").read()
    for i, o in enumerate(struct.unpack("<4001I", d)):
        if o == 0xFFFFFFFF: continue
        usize, _, csize = struct.unpack_from("<3I", a, o)
        out = blast.blast(a[o + 12:o + 12 + csize])
        assert len(out) == usize, (i, len(out), usize)
        yield i, out

def fmt16_of(raw):
    """16-bit textures: flag byte +0x10 bit 0x80 set = A1R5G5B5 (on/off alpha), clear = A4R4G4B4 (smooth alpha)."""
    return "1555" if raw[0x10] & 0x80 else "4444"

def pixel_start(raw):
    """Offset of the main image. Skins with animation frames (+0xc frames of +4 x +6) store the frames FIRST, then
    the atlas (upload path 4 at 0x506408 takes the frames at the pixel start and the atlas after them)."""
    fw, fh = struct.unpack_from("<2H", raw, 4)
    return 0x412 + raw[0xC] * fw * fh * raw[0xE]

def to_image(raw, fmt16=None):
    w, h = struct.unpack_from("<2H", raw, 0); bpp = raw[0xE]
    fmt16 = fmt16 or fmt16_of(raw)
    pal = raw[0x12:0x412]; o = pixel_start(raw)
    if bpp == 1:
        img = Image.frombytes("P", (w, h), raw[o:o + w * h])
        img.putpalette(bytes(b for k in range(256) for b in pal[4 * k:4 * k + 3]))
        return img.convert("RGB")
    px = struct.unpack_from(f"<{w * h}H", raw, o)
    if fmt16 == "565":
        data = bytes(c for p in px for c in (((p >> 11) & 31) * 255 // 31, ((p >> 5) & 63) * 255 // 63, (p & 31) * 255 // 31, 255))
    elif fmt16 == "1555":
        data = bytes(c for p in px for c in (((p >> 10) & 31) * 255 // 31, ((p >> 5) & 31) * 255 // 31, (p & 31) * 255 // 31, 255 if p >> 15 else 0))
    else:
        data = bytes(c for p in px for c in (((p >> 8) & 15) * 17, ((p >> 4) & 15) * 17, (p & 15) * 17, (p >> 12) * 17))
    return Image.frombytes("RGBA", (w, h), data)

if __name__ == "__main__":
    out = sys.argv[1]; want = {int(x) for x in sys.argv[2:]}
    os.makedirs(out, exist_ok=True); index = {}
    for i, raw in entries():
        if want and i not in want: continue
        index[i] = {"w": struct.unpack_from("<H", raw, 0)[0], "h": struct.unpack_from("<H", raw, 2)[0], "hdr": raw[:0x12].hex()}
        to_image(raw).save(os.path.join(out, f"{i:04d}.png"))
    json.dump(index, open(os.path.join(out, "index.json"), "w"), indent=0)
    print(len(index), "textures ->", out)
