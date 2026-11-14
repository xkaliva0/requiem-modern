"""HD menu art (media\\DIBs except HUD / HUDLoRes, 8-bit BMPs).
  py menu_hd.py masters DIBS_DIR OUT_DIR        Real-ESRGAN 4x of every image -> OUT_DIR\\<rel>.png (RGB, key filled)
  py menu_hd.py build DIBS_DIR MASTERS OUT S    resample the masters to round(w*S) x round(h*S), quantise to the
                                                original palette, colour key (0xfd) from the original, write 8-bit
                                                BMPs with the 'RQHD' header (logical size) to OUT\\<rel>
The menus are drawn by RequiemMenu.dll at S = min(W/640, H/480), so the art is written at exactly that scale and
copied 1:1 (8-bit surfaces cannot be filtered when stretched). The launcher runs build() for the chosen resolution."""
import os, shutil, subprocess, sys, tempfile
from PIL import Image

KEY, PAD = 0xFD, 8

def images(dibs):
    for d, _, ns in os.walk(dibs):
        rel_d = os.path.relpath(d, dibs)
        if rel_d.split(os.sep)[0].lower().startswith("hud"): continue   # HUD art: hud_hd.py (3D, fixed 4x)
        for n in sorted(ns):
            if n.lower().endswith(".bmp"):
                rel = os.path.normpath(os.path.join(rel_d, n))
                if Image.open(os.path.join(dibs, rel)).mode == "P": yield rel

def masters(dibs, out):
    import hud_hd as H
    files = list(images(dibs)); tin, tout = tempfile.mkdtemp(), tempfile.mkdtemp()
    for i, f in enumerate(files):
        im = Image.open(os.path.join(dibs, f))
        H.edge_pad(H.fill_key(im.convert("RGB"), im.point(lambda v: 255 if v == KEY else 0, "L"))).save(f"{tin}/{i:03}.png")
    subprocess.run([H.EXE, "-i", tin, "-o", tout, "-n", "realesrgan-x4plus", "-s", "4", "-f", "png"], check=True,
                   creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=os.path.dirname(H.EXE))
    for i, f in enumerate(files):
        w, h = Image.open(os.path.join(dibs, f)).size
        up = Image.open(f"{tout}/{i:03}.png").convert("RGB").crop((4 * PAD, 4 * PAD, 4 * (PAD + w), 4 * (PAD + h)))
        o = os.path.join(out, f + ".png"); os.makedirs(os.path.dirname(o), exist_ok=True); up.save(o, optimize=True)
    shutil.rmtree(tin); shutil.rmtree(tout)
    print(len(files), "menu masters ->", out)

def write_bmp(path, img, ow, oh):
    import struct
    pal = img.getpalette()[:768]; pal += [0] * (768 - len(pal))
    w, h = img.size; row = (w + 3) & ~3; pix = img.tobytes()
    data = b"".join(pix[y * w:(y + 1) * w] + bytes(row - w) for y in range(h - 1, -1, -1))
    quad = b"".join(bytes((pal[3 * i + 2], pal[3 * i + 1], pal[3 * i], 0)) for i in range(256))
    off = 14 + 40 + 1024
    info = struct.pack("<IiiHHII4sIII", 40, w, h, 1, 8, 0, len(data), b"RQHD", ow | oh << 16, 0, 0)
    open(path, "wb").write(b"BM" + struct.pack("<IHHI", off + len(data), 0, 0, off) + info + quad + data)

def build_one(src, master, out, s):
    im = Image.open(src); w, h = im.size
    size = (max(1, round(w * s)), max(1, round(h * s)))
    if master is None:   # no AI master: the original, resampled with the key as alpha (premultiplied, no fringe)
        a = im.convert("RGBA"); a.putalpha(im.point(lambda v: 0 if v == KEY else 255, "L"))
        a = a.resize(size, Image.LANCZOS)
        up, key = a.convert("RGB"), a.getchannel("A").point(lambda v: 255 if v < 128 else 0)
    else:
        up = Image.open(master).convert("RGB").resize(size, Image.LANCZOS)
        key = im.point(lambda v: 255 if v == KEY else 0, "L").resize(size, Image.BILINEAR).point(lambda v: 255 if v >= 128 else 0)
    pal = im.getpalette()[:768]; pal += [0] * (768 - len(pal))
    qp = list(pal); qp[3 * KEY:3 * KEY + 3] = qp[0:3]          # never dither into the key colour
    p = Image.new("P", (1, 1)); p.putpalette(qp)
    q = up.quantize(palette=p, dither=Image.Dither.FLOYDSTEINBERG)
    q.paste(KEY, mask=key); q.putpalette(pal)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    write_bmp(out, q, w, h)

def build(dibs, mdir, out, s):
    s = float(s); n = 0
    for f in images(dibs):
        m = os.path.join(mdir, f + ".png")
        if os.path.exists(m): build_one(os.path.join(dibs, f), m, os.path.join(out, f), s); n += 1
    print(n, "menu images at", s, "->", out)

MAGIC = b"RQMNPAK1"

def pack(mdir, out):
    """Masters payload for the launcher: u32 count, then per image u16 name length, name (rel path, '/'), u32 size, PNG."""
    import struct
    items = []
    for d, _, ns in os.walk(mdir):
        for n in sorted(ns):
            p = os.path.join(d, n); rel = os.path.relpath(p, mdir)[:-4].replace(os.sep, "/").encode()
            items.append(struct.pack("<H", len(rel)) + rel + struct.pack("<I", os.path.getsize(p)) + open(p, "rb").read())
    open(out, "wb").write(struct.pack("<I", len(items)) + b"".join(items))
    print(len(items), "menu masters ->", out, os.path.getsize(out), "bytes")

def unpack(data):
    """{rel path lower-case with '/': PNG bytes} from a pack() payload."""
    import struct
    out, pos = {}, 4
    for _ in range(struct.unpack_from("<I", data, 0)[0]):
        n = struct.unpack_from("<H", data, pos)[0]; name = data[pos + 2:pos + 2 + n].decode(); pos += 2 + n
        size = struct.unpack_from("<I", data, pos)[0]; out[name.lower()] = data[pos + 4:pos + 4 + size]; pos += 4 + size
    return out

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    {"masters": masters, "build": build, "pack": pack}[sys.argv[1]](*sys.argv[2:])
