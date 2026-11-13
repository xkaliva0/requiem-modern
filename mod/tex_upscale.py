"""Upscale extracted textures 4x with Real-ESRGAN (ncnn-vulkan), tile-safe: each texture gets a wrapped 16 px border
(so tiling edges see their neighbours), is upscaled, then cropped back to exactly 4x. Alpha (16-bit textures) is
upscaled separately with nearest neighbour and kept 1-bit.
Usage: py tex_upscale.py SRC_DIR DST_DIR [model] [index ...]   model: realesrgan-x4plus (default) | realesrgan-x4plus-anime"""
import os, shutil, subprocess, sys, tempfile
from PIL import Image

LAB = os.environ.get("REQUIEM_LAB", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root by default
EXE = os.environ.get("REALESRGAN", os.path.join(LAB, "tools", "realesrgan", "realesrgan-ncnn-vulkan.exe"))
PAD = 16

def wrap_pad(img):
    w, h = img.size; big = Image.new(img.mode, (w + 2 * PAD, h + 2 * PAD))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1): big.paste(img, (PAD + dx * w, PAD + dy * h))
    return big

def main(src, dst, model="realesrgan-x4plus", only=()):
    os.makedirs(dst, exist_ok=True)
    names = [n for n in sorted(os.listdir(src)) if n.endswith(".png") and (not only or int(n[:4]) in only)]
    tmp_in, tmp_out = tempfile.mkdtemp(), tempfile.mkdtemp()
    alpha = {}
    for n in names:
        img = Image.open(os.path.join(src, n))
        if img.mode == "RGBA": alpha[n] = img.getchannel("A")
        wrap_pad(img.convert("RGB")).save(os.path.join(tmp_in, n))
    subprocess.run([EXE, "-i", tmp_in, "-o", tmp_out, "-n", model, "-s", "4", "-f", "png"], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=os.path.dirname(EXE))
    for n in names:
        up = Image.open(os.path.join(tmp_out, n)); w, h = Image.open(os.path.join(src, n)).size
        up = up.crop((4 * PAD, 4 * PAD, 4 * PAD + 4 * w, 4 * PAD + 4 * h))
        if n in alpha:
            a = alpha[n]; smooth = any(0 < v < 255 for v in set(a.getdata()))      # A4R4G4B4 glows: smooth alpha
            up = up.convert("RGBA"); up.putalpha(a.resize(up.size, Image.BICUBIC if smooth else Image.NEAREST))
        up.save(os.path.join(dst, n))
    shutil.rmtree(tmp_in); shutil.rmtree(tmp_out)
    print(len(names), "upscaled ->", dst)

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "realesrgan-x4plus", {int(x) for x in sys.argv[4:]})
