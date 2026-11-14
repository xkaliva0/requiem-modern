"""Make Requiem Modern's HD art on the player's own PC, from their own copy of the game (the release ships no game
art). Same recipe as the hand-made set (docs/DEVLOG.md "HD textures", "1.6.2", "1.6.3", "1.7.0", "1.8.0"):
  textures: every texture 4x / 8x / 16x (a side > 256): AI (Real-ESRGAN x4plus, wrapped 16 px border; alpha kept
            separately) for walls, objects and skins (with their animation frames); Lanczos for the 106 16-bit effect
            textures (keeps their sparkle); the six water textures stay original (the game builds its ripples from
            them at their original size). Result: a payload (zlib) of decoded HD textures for the launcher's set_hd.
  HUD:      hud_hd.main (AI 4x, crisp label strips, original palette and colour key).
  menus:    menu_hd.masters (AI 4x masters), packed; the launcher resamples them to the screen scale.
EXE must point at realesrgan-ncnn-vulkan.exe (the launcher sets it to its bundled copy). If the AI upscaler cannot
run (no Vulkan GPU), Lanczos is used instead so the player still gets the art."""
import os, shutil, struct, subprocess, time, zlib
from PIL import Image
import blast, hd_build, hd_rest, hud_hd, menu_hd, tex_extract

EXE = None
WATER = {8, 9, 82, 1508, 1509, 1582}
# one flat colour in the GOG v1.2 archive (debris colours etc.): nothing to upscale, and the AI's faint variation came
# out as speckle after palette mapping (user: grainy debris). They stay original, like WATER.
FLAT = {1, 2, 3, 4, 5, 6, 7, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 469, 479, 480, 481, 948, 1088, 1089, 1090, 1091, 1092, 1093, 1094, 1095, 1096, 1097, 1098, 1099, 1100, 1106, 1107, 1108, 1109, 1501, 1502, 1503, 1504, 1505, 1506, 1507, 1510, 1511, 1512, 1513, 1514, 1515, 1516, 1517, 1518, 1519, 1520, 1521, 1522, 1523, 1524, 1892, 1893, 1894, 1895, 1896, 1897, 1898, 1899, 1976, 2083, 2084, 2085, 2086, 2087, 2088, 2089, 2090, 2091, 2092, 2093, 2094, 2095, 2096, 2097, 2098, 2170, 2171, 2172, 2550}
KEEP = WATER | FLAT
SKIN16 = {1166, 1167, 1168, 1169, 3001, 3016, 3053, 3248, 3260, 3271, 3280, 3318}
PAD = 16
NO_WINDOW = 0x08000000


def archive(art, dat):
    """(index, decoded texture) of an original ReqArtD3 archive."""
    a, d = open(art, "rb").read(), open(dat, "rb").read()
    for i, o in enumerate(struct.unpack("<4001I", d)):
        if o == 0xFFFFFFFF: continue
        usize, _, csize = struct.unpack_from("<3I", a, o)
        out = blast.blast(a[o + 12:o + 12 + csize])
        assert len(out) == usize, i
        yield i, out


def is_effect(i, raw):
    # 16-bit single-frame non-skins with soft alpha (A4R4G4B4); the six on/off-alpha ones (A1R5G5B5, flag 0x80:
    # 642/643/1002/1003/2253/2254) are grilles: AI, not Lanczos (Lanczos smeared their speckle into blotches).
    return raw[0xE] == 2 and raw[0xC] == 0 and not raw[0x10] & 0x80 and i not in SKIN16


def _wrap_pad(img):
    w, h = img.size; big = Image.new(img.mode, (w + 2 * PAD, h + 2 * PAD))
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1): big.paste(img, (PAD + dx * w, PAD + dy * h))
    return big


def ai_ok():
    """Real-ESRGAN runs here (a Vulkan GPU): a tiny test image comes back 4x."""
    if not EXE or not os.path.exists(EXE): return False
    d = None
    try:
        import tempfile
        d = tempfile.mkdtemp(); Image.new("RGB", (8, 8), (90, 60, 30)).save(os.path.join(d, "t.png"))
        subprocess.run([EXE, "-i", os.path.join(d, "t.png"), "-o", os.path.join(d, "o.png"), "-n", "realesrgan-x4plus", "-s", "4"],
                       cwd=os.path.dirname(EXE), capture_output=True, timeout=120, creationflags=NO_WINDOW)
        return Image.open(os.path.join(d, "o.png")).size == (32, 32)
    except Exception:
        return False
    finally:
        if d: shutil.rmtree(d, ignore_errors=True)


def upscale_dir(src, dst, progress=None, label="", use_ai=True):
    """Every PNG in src 4x into dst (tile-safe wrapped border; alpha upscaled separately and kept as it was)."""
    os.makedirs(dst, exist_ok=True)
    names = sorted(n for n in os.listdir(src) if n.endswith(".png"))
    if not names: return
    tin, tout = os.path.join(dst, "_in"), os.path.join(dst, "_out")
    os.makedirs(tin, exist_ok=True); os.makedirs(tout, exist_ok=True)
    for n in names:
        _wrap_pad(Image.open(os.path.join(src, n)).convert("RGB")).save(os.path.join(tin, n))
    if use_ai:
        p = subprocess.Popen([EXE, "-i", tin, "-o", tout, "-n", "realesrgan-x4plus", "-s", "4", "-f", "png"], cwd=os.path.dirname(EXE),
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW)
        try:
            while p.poll() is None:
                if progress: progress(label, 0.85 * len(os.listdir(tout)) / len(names))   # the AI: 0-85 %
                time.sleep(1)
        finally:
            if p.poll() is None: p.kill()   # cancelled (progress raised)
        if p.returncode or len(os.listdir(tout)) < len(names): use_ai = False   # fall back for whatever is missing
    for k, n in enumerate(names):
        img = Image.open(os.path.join(src, n)); w, h = img.size
        o = os.path.join(tout, n)
        if use_ai and os.path.exists(o):
            up = Image.open(o).convert("RGB").crop((4 * PAD, 4 * PAD, 4 * (PAD + w), 4 * (PAD + h)))
        else:
            up = img.convert("RGB").resize((4 * w, 4 * h), Image.LANCZOS)
        if img.mode == "RGBA":
            a = img.getchannel("A"); smooth = any(0 < v < 255 for v in set(a.getdata()))
            up = up.convert("RGBA"); up.putalpha(a.resize(up.size, Image.BICUBIC if smooth else Image.NEAREST))
        up.save(os.path.join(dst, n))
        if progress and k % 50 == 0: progress(label, (0.85 + 0.15 * k / len(names)) if use_ai else k / len(names))
    shutil.rmtree(tin, ignore_errors=True); shutil.rmtree(tout, ignore_errors=True)


def textures(art, dat, out_file, work, progress=None, use_ai=True):
    """The HD texture payload (u32 count, then per texture u32 index, u32 size, decoded bytes; zlib) -> out_file."""
    src, dst, fsrc, fdst = (os.path.join(work, n) for n in ("in", "x4", "frames_in", "frames_x4"))
    for d in (src, dst, fsrc, fdst): os.makedirs(d, exist_ok=True)
    raws = {}
    for i, raw in archive(art, dat):
        raws[i] = raw
        if progress and len(raws) % 50 == 0: progress("Reading your game's textures", i / 4001)
    for k, (i, raw) in enumerate(raws.items()):
        if progress and k % 100 == 0: progress("Reading your game's textures", k / len(raws))
        if i in KEEP: continue
        img = tex_extract.to_image(raw)
        if is_effect(i, raw):   # effects: smooth 4x
            img.resize((img.width * 4, img.height * 4), Image.LANCZOS).save(os.path.join(dst, f"{i:04d}.png"))
            continue
        img.save(os.path.join(src, f"{i:04d}.png"))
        if raw[0xC]:
            for f, fimg in hd_rest.frames_of(raw): fimg.save(os.path.join(fsrc, f"{i:04d}_f{f:02d}.png"))
    upscale_dir(src, dst, progress, "Upscaling textures", use_ai)
    upscale_dir(fsrc, fdst, progress, "Upscaling character faces", use_ai)
    hd_build.FRAMES_DIR = fdst
    z = zlib.compressobj(1); n = 0
    with open(out_file + ".tmp", "wb") as f:
        f.write(b"RQZ1"); f.write(z.compress(struct.pack("<I", len([i for i in raws if i not in KEEP]))))
        for k, (i, raw) in enumerate(raws.items()):
            if i in KEEP: continue
            data = hd_build.hd_raw(raw, os.path.join(dst, f"{i:04d}.png"))
            f.write(z.compress(struct.pack("<2I", i, len(data)) + data)); n += 1
            if progress and k % 100 == 0: progress("Building HD textures", k / len(raws))
        f.write(z.flush())
    os.replace(out_file + ".tmp", out_file)
    shutil.rmtree(work, ignore_errors=True)
    return n


def hud(src, out_dir):
    hud_hd.EXE = EXE
    hud_hd.main(src, out_dir)


def menus(dibs, out_file, work):
    hud_hd.EXE = EXE
    menu_hd.masters(dibs, work)
    menu_hd.pack(work, out_file)
    shutil.rmtree(work, ignore_errors=True)


def originals(dibs, backup, out):
    r"""media\DIBs as the game shipped it, in out: the folder's DIBs with the launcher's backups of the menu art and
    HUD put over them; an HD image with no backup is left out (it cannot be made again from itself)."""
    shutil.rmtree(out, ignore_errors=True); shutil.copytree(dibs, out)
    hud = next((n for n in os.listdir(out) if n.lower() == "hud"), "HUD")
    for b, dst in ((os.path.join(backup, "DIBs"), out), (os.path.join(backup, "HUD"), os.path.join(out, hud))):
        if os.path.isdir(b): shutil.copytree(b, dst, dirs_exist_ok=True)
    for d, _, ns in os.walk(out):
        for n in ns:
            p = os.path.join(d, n)
            if n.lower().endswith(".bmp") and open(p, "rb").read(42)[38:42] == b"RQHD": os.remove(p)
    return out


def make(art, dat, dibs, gen, progress=None):
    r"""Everything into gen: textures.bin, hud\, menu.bin, then done.txt (written last: the art is complete).
    dibs: the game's original media\DIBs (see originals). Returns False when the AI upscaler could not run (the
    textures were made with Lanczos; no HD HUD or menu masters)."""
    shutil.rmtree(gen, ignore_errors=True); os.makedirs(gen)
    if progress: progress("Checking the AI upscaler", 0)
    use_ai = ai_ok()
    textures(art, dat, os.path.join(gen, "textures.bin"), os.path.join(gen, "work"), progress, use_ai)
    if use_ai:
        if progress: progress("Upscaling the HUD", 0)
        hud(os.path.join(dibs, next(n for n in os.listdir(dibs) if n.lower() == "hud")), os.path.join(gen, "hud"))
        if progress: progress("Upscaling the menus", 0)
        menus(dibs, os.path.join(gen, "menu.bin"), os.path.join(gen, "work_menu"))
    open(os.path.join(gen, "done.txt"), "w").write(("ai" if use_ai else "lanczos") + " v2\n")
    return use_ai


def read_payload(path, off=0, size=None):
    """Decoded payload bytes: the launcher's own (RQZ1 + zlib) or the older shipped one (LZMA)."""
    import lzma
    with open(path, "rb") as f:
        f.seek(off); raw = f.read(size if size is not None else -1)
    return zlib.decompress(raw[4:]) if raw[:4] == b"RQZ1" else lzma.decompress(raw)
