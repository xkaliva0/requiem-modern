"""Build HD texture entries. For a texture with an upscaled PNG (HD_DIR\\NNNN.png, 4x; frames in
FRAMES_DIR\\NNNN_fKK.png): scale s = 4, 8 or 16 so a side > 256 (8x/16x = 4x AI then Lanczos), 8-bit textures mapped
back onto their own palette (Floyd-Steinberg), 16-bit packed back to A1R5G5B5 / A4R4G4B4, animation-frame size and
position (+4/+6, +8/+0xa) scaled with the image, then 'RQHD' + original u16 w, h after the data, which patch_d3d's
HD caves read so texture coordinates keep the original size.
Usage: py hd_build.py OUT_DIR   (archive of every texture, HD where a PNG exists)"""
import os, struct, sys
from PIL import Image, ImageChops, ImageFilter, ImageMath, ImageStat
import art_build, tex_extract

LAB = os.environ.get("REQUIEM_LAB", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root by default
HD_DIR, FRAMES_DIR = os.path.join(LAB, "hd", "x4"), os.path.join(LAB, "hd", "x4_frames")

def scale_of(w, h):
    return next(s for s in (4, 8, 16) if max(w, h) * s > 256)

def _fit(img, size):
    return img if img.size == size else img.resize(size, Image.LANCZOS)

def _pixels(raw, img, size):
    """HD image -> the texture's own pixel format (raw = original texture, for palette / 16-bit format)."""
    img = _fit(img, size)
    if raw[0xE] == 1:
        # Nearest palette colour: as close to the AI image as dithering and without its grain (Floyd-Steinberg turned
        # flat and smooth areas into speckle; user: grainy debris). Only smooth gradients the palette can't follow
        # (they band into blotches) are dithered.
        pal = raw[0x12:0x412]
        pimg = Image.new("P", (1, 1)); pimg.putpalette(bytes(b for k in range(256) for b in pal[4 * k:4 * k + 3]))
        rgb = img.convert("RGB"); q = rgb.quantize(palette=pimg, dither=Image.Dither.NONE)
        mean = lambda im: sum(ImageStat.Stat(im).mean[:3]) / 3
        if mean(ImageChops.difference(q.convert("RGB"), rgb)) > 10 and mean(ImageChops.difference(rgb, rgb.filter(ImageFilter.BoxBlur(1)))) < 1:
            q = rgb.quantize(palette=pimg, dither=Image.Dither.FLOYDSTEINBERG)
        return q.tobytes()
    r, g, b, a = (c.convert("I") for c in img.convert("RGBA").split())
    if tex_extract.fmt16_of(raw) == "1555":
        v = ImageMath.lambda_eval(lambda e: ((e["a"] >> 7) << 15) | ((e["r"] >> 3) << 10) | ((e["g"] >> 3) << 5) | (e["b"] >> 3), r=r, g=g, b=b, a=a)
    else:
        v = ImageMath.lambda_eval(lambda e: ((e["a"] >> 4) << 12) | ((e["r"] >> 4) << 8) | ((e["g"] >> 4) << 4) | (e["b"] >> 4), r=r, g=g, b=b, a=a)
    return v.convert("I;16").tobytes()

def hd_raw(raw, png=None):
    i_png = png
    w, h = struct.unpack_from("<2H", raw, 0); s = scale_of(w, h)
    hdr = bytearray(raw[:0x12]); struct.pack_into("<2H", hdr, 0, w * s, h * s)
    body = b""
    if raw[0xC]:                                              # skin: animation frames first, then the atlas
        fw, fh, fx, fy = struct.unpack_from("<4H", raw, 4)
        struct.pack_into("<4H", hdr, 4, fw * s, fh * s, fx * s, fy * s)
        stem = os.path.splitext(os.path.basename(i_png))[0]
        for k in range(raw[0xC]):
            fpng = os.path.join(FRAMES_DIR, f"{stem}_f{k:02d}.png")
            body += _pixels(raw, Image.open(fpng), (fw * s, fh * s))
    body += _pixels(raw, Image.open(i_png), (w * s, h * s))
    return bytes(hdr) + raw[0x12:0x412] + body + b"RQHD" + struct.pack("<2H", w, h)

def entries():
    """(index, decoded bytes) for the whole archive: HD where an upscaled PNG exists, else the original."""
    for i, raw in tex_extract.entries():
        png = os.path.join(HD_DIR, f"{i:04d}.png")
        yield i, (hd_raw(raw, png) if os.path.exists(png) else raw), os.path.exists(png)

if __name__ == "__main__":
    ents, n = {}, 0
    for i, data, is_hd in entries():
        ents[i] = data; n += is_hd
    art_build.build(ents, sys.argv[1])
    print(n, "HD of", len(ents), "->", sys.argv[1])
