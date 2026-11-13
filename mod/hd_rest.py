r"""HD for the textures the first pass skipped: 16-bit (A4R4G4B4 / A1R5G5B5), small ones (8x/16x so a side > 256),
render-flagged 8-bit, and skins with animation frames (atlas + frames, frame size/position scaled with them).
  py hd_rest.py export   -> hd\frames_orig\NNNN_fKK.png, hd\rest.txt (indices), hd\frames.txt
  then tex_upscale.py on both lists -> hd\x4 (mains) and hd\x4_frames"""
import os, struct, sys
from PIL import Image
import tex_extract

LAB = os.environ.get("REQUIEM_LAB", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))   # repo root by default
HD = os.path.join(LAB, "hd")

def scale_of(w, h):
    return next(s for s in (4, 8, 16) if max(w, h) * s > 256)

def frames_of(raw):
    w, h = struct.unpack_from("<2H", raw, 0); fw, fh = struct.unpack_from("<2H", raw, 4); n, bpp = raw[0xC], raw[0xE]
    for k in range(n):                                        # frames come first, then the atlas
        o = 0x412 + k * fw * fh * bpp
        fake = struct.pack("<2H", fw, fh) + raw[4:0xC] + b"\x00" + raw[0xD:0x412] + raw[o:o + fw * fh * bpp]
        yield k, tex_extract.to_image(fake)

if __name__ == "__main__" and sys.argv[1] == "export":
    done = set(map(int, open(os.path.join(HD, "eligible.txt")).read().split()))
    rest, frames = [], []
    os.makedirs(os.path.join(HD, "frames_orig"), exist_ok=True)
    for i, raw in tex_extract.entries():
        if i in done: continue
        rest.append(i)
        if raw[0xC]:
            for k, img in frames_of(raw):
                img.save(os.path.join(HD, "frames_orig", f"{i:04d}_f{k:02d}.png")); frames.append(f"{i:04d}_f{k:02d}")
    open(os.path.join(HD, "rest.txt"), "w").write(" ".join(map(str, rest)))
    print(len(rest), "textures,", len(frames), "frames exported")
