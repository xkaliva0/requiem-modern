"""HD HUD art: upscale every 8-bit BMP under media\\DIBs\\HUD 4x with Real-ESRGAN and write it back as an 8-bit BMP
with the original palette (the game's 3D loader 0x509c20 only takes 8-bit, uncompressed, 256-colour BMPs).
Index 0xfd is the colour key (transparent): key pixels are filled from their neighbours before upscaling, and the
key mask is upscaled separately and kept 1-bit. The original size goes in the header for the patched loader:
biXPelsPerMeter = 'RQHD', biYPelsPerMeter = w | h << 16.
Usage: py hud_hd.py SRC_HUD_DIR DST_DIR"""
import os, shutil, struct, subprocess, sys, tempfile
from PIL import Image

LAB = os.environ.get("REQUIEM_LAB", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root by default
EXE = os.environ.get("REALESRGAN", os.path.join(LAB, "tools", "realesrgan", "realesrgan-ncnn-vulkan.exe"))
KEY, S, PAD = 0xFD, 4, 8

def fill_key(rgb, mask):
    """Replace key pixels with the average of non-key neighbours, growing inwards until none are left."""
    w, h = rgb.size; px = rgb.load(); m = [[mask.getpixel((x, y)) for x in range(w)] for y in range(h)]
    if all(all(r) for r in m): return rgb
    while any(any(r) for r in m):
        done = []
        for y in range(h):
            for x in range(w):
                if not m[y][x]: continue
                n = [px[i, j] for i in range(max(0, x - 1), min(w, x + 2)) for j in range(max(0, y - 1), min(h, y + 2))
                     if not m[j][i]]
                if n: done.append((x, y, tuple(sum(c[k] for c in n) // len(n) for k in range(3))))
        for x, y, c in done: px[x, y] = c; m[y][x] = 0
    return rgb

def edge_pad(img):
    """PAD pixels on every side, copied from the nearest edge pixel."""
    w, h = img.size; big = img.resize((w + 2 * PAD, h + 2 * PAD), Image.NEAREST)
    for x0, y0, x1, y1, box in ((0, PAD, PAD, PAD + h, (0, 0, 1, h)), (PAD + w, PAD, w + 2 * PAD, PAD + h, (w - 1, 0, w, h)),
                                (PAD, 0, PAD + w, PAD, (0, 0, w, 1)), (PAD, PAD + h, PAD + w, h + 2 * PAD, (0, h - 1, w, h))):
        big.paste(img.crop(box).resize((x1 - x0, y1 - y0), Image.NEAREST), (x0, y0))
    for cx, cy, p in ((0, 0, (0, 0)), (PAD + w, 0, (w - 1, 0)), (0, PAD + h, (0, h - 1)), (PAD + w, PAD + h, (w - 1, h - 1))):
        big.paste(img.getpixel(p), (cx, cy, cx + PAD, cy + PAD))
    big.paste(img, (PAD, PAD)); return big

def scale2x(im):
    """EPX / Scale2x: doubles pixel art without blurring it (keeps the tiny label lettering readable)."""
    w, h = im.size; p = im.load(); o = Image.new(im.mode, (2 * w, 2 * h)); q = o.load()
    g = lambda x, y: p[min(max(x, 0), w - 1), min(max(y, 0), h - 1)]
    for y in range(h):
        for x in range(w):
            P, A, B, C, D = g(x, y), g(x, y - 1), g(x + 1, y), g(x - 1, y), g(x, y + 1)
            q[2 * x, 2 * y] = A if C == A and C != D and A != B else P
            q[2 * x + 1, 2 * y] = B if A == B and A != C and B != D else P
            q[2 * x, 2 * y + 1] = C if D == C and D != B and C != A else P
            q[2 * x + 1, 2 * y + 1] = D if B == D and B != A and D != C else P
    return o

def label_band(rgb):
    """First row of the green / red pixel-font label along the bottom of a 32x32 icon (ENERGY, RAILGUN...), or None."""
    w, h = rgb.size
    if (w, h) != (32, 32): return None
    lab = lambda c: (c[1] > 180 and c[0] < 110 and c[2] < 110) or (c[0] > 180 and c[1] < 70 and c[2] < 70)
    rows = {y for y in range(16, 32) if sum(lab(rgb.getpixel((x, y))) for x in range(w)) >= 3}
    if not set(range(24, 29)) <= rows or (22 in rows and 23 in rows): return None   # heal's red cross is not a label
    return min(y for y in rows if y >= 22) - 1

def write_bmp(path, img, ow, oh):
    pal = img.getpalette()[:768]; pal += [0] * (768 - len(pal))
    w, h = img.size; row = (w + 3) & ~3; pix = img.tobytes()
    data = b"".join(pix[y * w:(y + 1) * w] + bytes(row - w) for y in range(h - 1, -1, -1))
    quad = b"".join(bytes((pal[3 * i + 2], pal[3 * i + 1], pal[3 * i], 0)) for i in range(256))
    off = 14 + 40 + 1024
    info = struct.pack("<IiiHHII4sIII", 40, w, h, 1, 8, 0, len(data), b"RQHD", ow | oh << 16, 0, 0)
    open(path, "wb").write(b"BM" + struct.pack("<IHHI", off + len(data), 0, 0, off) + info + quad + data)

def main(src, dst):
    files = [os.path.relpath(os.path.join(d, n), src) for d, _, ns in os.walk(src) for n in ns if n.lower().endswith(".bmp")]
    tin, tout = tempfile.mkdtemp(), tempfile.mkdtemp()
    for i, f in enumerate(files):
        im = Image.open(os.path.join(src, f)); assert im.mode == "P", f
        mask = im.point(lambda v: 255 if v == KEY else 0, "L")
        rgb = fill_key(im.convert("RGB"), mask)
        edge_pad(rgb).save(os.path.join(tin, f"{i:03}.png"))
    subprocess.run([EXE, "-i", tin, "-o", tout, "-n", "realesrgan-x4plus", "-s", str(S), "-f", "png"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=os.path.dirname(EXE))
    for i, f in enumerate(files):
        im = Image.open(os.path.join(src, f)); w, h = im.size
        up = Image.open(os.path.join(tout, f"{i:03}.png")).convert("RGB").crop((S * PAD, S * PAD, S * (PAD + w), S * (PAD + h)))
        band = label_band(im.convert("RGB"))
        if band is not None:   # the AI garbles 5 px lettering: Scale2x x2 for the label strip
            sx = scale2x(scale2x(fill_key(im.convert("RGB"), im.point(lambda v: 255 if v == KEY else 0, "L"))))
            up.paste(sx.crop((0, S * band, S * w, S * h)), (0, S * band))
        key = im.point(lambda v: 255 if v == KEY else 0, "L").resize(up.size, Image.BICUBIC).point(lambda v: 255 if v >= 128 else 0)
        pal = im.getpalette()[:768]; pal += [0] * (768 - len(pal))
        qp = list(pal); qp[3 * KEY:3 * KEY + 3] = qp[0:3] if KEY else qp[3:6]   # never dither into the key colour
        pimg = Image.new("P", (1, 1)); pimg.putpalette(qp)
        q = up.quantize(palette=pimg, dither=Image.Dither.FLOYDSTEINBERG)
        q.paste(KEY, mask=key); q.putpalette(pal)
        out = os.path.join(dst, f); os.makedirs(os.path.dirname(out), exist_ok=True)
        write_bmp(out, q, w, h)
    shutil.rmtree(tin); shutil.rmtree(tout)
    print(len(files), "HUD images ->", dst)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
