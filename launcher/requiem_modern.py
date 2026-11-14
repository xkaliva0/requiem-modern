"""Requiem Modern: installer + launcher for Requiem: Avenging Angel (GOG v1.2, D3D renderer).

Point it at the game folder once; it installs the modern setup (DDrawCompat wrapper, its settings, the patched
D3D.exe built from the original, backups of everything it replaces) and then works as the game's launcher with the
settings pages. Uses the game's own art and font from the chosen folder at run time. It carries none of the game's
art: MAKE HD ART upscales the player's own textures, HUD and menu art on their PC (mod/hd_make.py, bundled Real-ESRGAN).
Build: build.bat (PyInstaller one-file). Project log: docs/DEVLOG.md
"""
import ctypes
import hashlib
import io
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
import threading
import time
import tkinter as tk
import winreg
from tkinter import filedialog

from PIL import Image, ImageChops, ImageDraw, ImageTk

import game_cfg
import patch_d3d

APP, VERSION = "Requiem Modern", "2.1.1"
W, H = 1280, 720
CONF_DIR = os.environ.get("REQUIEM_MODERN_CONF") or os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), APP)
CONF = os.path.join(CONF_DIR, "launcher.json")
BACKUP = "Modern Backup"
INI = "DDrawCompat-D3D.ini"

GOG_D3D = "f472aa5f1ebf5a2b40346b6a530f9a97d2bce72fb1865fb3fd1b4be7fa990b76"     # D3D.exe, GOG v1.2
GOG_DDRAW = "700041952d3fb278b720f34c54f8f68625062f8996703ac40e4d103856f20af5"   # GOG's own ddraw.dll
DDC = "94895cf6ede8fd0f74ee1447fdc08b7044a9c65a1a25a49a4df893a0370975a3"         # DDrawCompat v0.7.2
DGV_D3DIMM = "85aa1d15d6880dbe927458f6a045a631264ba128528010b7296ec5c3a640e0ac"  # dgVoodoo D3DImm.dll
DSOAL = {"dsound.dll": "fd2e9ae650eedf0dcfdf79164af150286bd510245f9676ce8854daf5f016be62",          # DSOAL r697
         "dsoal-aldrv.dll": "741a040ecce56230e68ffd4913884fcae54158425fead328b2d0755797eeaab4"}    # OpenAL Soft
DSOAL_DOCS = ("DSOAL-License.txt", "OpenALSoft-License.txt", "DSOAL-Version.txt")
HRTF_INI = "[general]\nchannels=stereo\nstereo-mode=headphones\nstereo-encoding=hrtf\n"

# Every resolution offered to the game. The game sorts its list by height, then width, and Gamers\latest.cfg stores
# the chosen entry's index in that order. 640x480 must stay: the menus use it.
RESOLUTIONS = [(640, 480), (800, 600), (1024, 768), (1280, 720), (1600, 900), (1440, 1080), (1920, 1080),
               (2560, 1080), (2560, 1440), (3440, 1440), (3840, 2160)]

CHANGES = [("2.1.1", [
    "Fixed: with HD textures, characters with animated faces showed extra copies of their face on other parts of the body (side of the head, legs) when the face moved.",
    "Fixed: debris and other plain single-colour textures looked grainy with HD textures; they now stay plain, as in the original game.",
    "MAKE HD ART makes cleaner textures (no grain on smooth surfaces). If you made your HD art with 2.1.0, REMAKE HD ART (main menu) gives you the cleaner set; your current art keeps working meanwhile.",
    "The six see-through grilles (e.g. the skylight grates) are upscaled with the AI like other surfaces instead of being smoothed, which made their bars blotchy. (REMAKE HD ART.)",
]), ("2.1.0", [
    "MAKE HD ART (main menu): the launcher makes the HD textures, HUD icons and menu art itself, from your own game files, with the AI upscaler that comes with it (Real-ESRGAN). The download no longer carries any of the game's art, so it is much smaller.",
    "Fixed: with HD textures, textures the game animates from another texture (the stained-glass window at the end of the opening tunnel) came out as combed stripes. They are now drawn in HD too.",
]), ("2.0.2", [
    "Fixed: after the game was reinstalled (or GOG checked its files) over an HD install, HD textures and HD menu art were not put back. The launcher now checks the files themselves.",
]), ("2.0.1", [
    "The game's volumes and footsteps are on the Audio tab.",
    "Clicking the left arrow of a setting steps it down (clicking anywhere else on the row still steps it up).",
]), ("2.0.0", [
    "Settings now wait for Apply: change what you like, then Apply (A) installs it, or Discard (D) drops it. Play uses only applied settings.",
    "The game's own options are here: brightness, crosshairs, shadows, effects, subtitles, volumes, footsteps (Game tab), mouse and movement options and every key binding (Controls tab).",
    "F10 while you play opens these settings over the paused game. The game's own options change live; the rest take effect the next time you start the game.",
    "F10 belongs to these settings now: the game's own F10 (Take Screenshot) moves to F12 when F12 is free.",
]), ("1.9.8", [
    "Borderless alt-tab: the paused game keeps its picture behind your other windows, and clicking it (or alt-tab) brings the game back. Your other windows stay on top.",
]), ("1.9.7", [
    "Undid 1.9.6: the paused picture stayed on top of other windows while clicks went through it. Alt-tab keeps the game open again, with a black window while you are away.",
]), ("1.9.6", [
    "Borderless alt-tab: the paused game keeps showing its last picture behind your other windows instead of going black.",
]), ("1.9.5", [
    "Borderless alt-tab fix moved to the lowest level of Windows, so compatibility shims on the game cannot get around it.",
]), ("1.9.4", [
    "Borderless alt-tab fix now also works where Windows applies compatibility shims to the game.",
]), ("1.9.3", [
    "Borderless now really is borderless: alt-tab leaves the game on screen behind your other windows instead of minimising it.",
]), ("1.9.2", [
    "Fixed: the mouse did nothing in pop-up dialogs such as the quit confirmation.",
]), ("1.9.1", [
    "Fixed: the mouse did nothing in the full-resolution menus (only the keyboard worked).",
]), ("1.9.0", [
    "Each HD upgrade is its own option: HD textures, HD effects, HD HUD icons and HD menu art (Graphics). Your current choice carries over.",
]), ("1.8.0", [
    "Menus at the game resolution (new option, on by default): menus, briefings and videos are drawn at full resolution with AI-upscaled art and sharp text, instead of a stretched 640x480.",
]), ("1.7.0", [
    "HD HUD: the 63 HUD icons and digits are 4x sharper (part of the HD textures option). Item and weapon labels stay crisp pixel lettering.",
]), ("1.6.3", [
    "Water is smooth again: the game builds its ripples from the original water textures every frame, so those six stay original.",
    "Animated textures (water scroll, skin faces) re-upload at the full HD size.",
]), ("1.6.2", [
    "Water and effects (fire, lightning, explosions, glows) keep their original shimmer in HD: the AI upscaler had smoothed it away.",
]), ("1.6.1", [
    "Fixed striped character skins in HD (their face frames were read in the wrong order).",
    "The red highlight round the active HUD icon is scaled with the HUD instead of staying small.",
]), ("1.6.0", [
    "HD textures now cover all 2,686 textures: monster and character skins (with their animated faces), effects, glows and small details.",
    "The game's fixed memory area is 128 MB instead of 8 MB, so the HD skins fit.",
    "An older HD install is upgraded automatically.",
]), ("1.5.1", [
    "HD textures are an option (off by default): turning it on in Graphics > Textures installs them right away, turning it off puts the originals back.",
]), ("1.5.0", [
    "HD textures: 2,496 of the game's textures upscaled 4x (Real-ESRGAN), on by default in Graphics > Textures.",
]), ("1.4.0", [
    "New Display mode setting: Borderless (as before) or exclusive Fullscreen.",
]), ("1.3.4", [
    "Frame rate descriptions updated with new measurements: jumps are only 3-5% lower above 60 fps (180 fps was listed as 14%).",
]), ("1.3.3", [
    "Enemies running at you from a distance leap as often per second at 120 fps as at 60 (the chance was rolled per frame).",
]), ("1.3.2", [
    "Enemies lunge as often at 120 fps as at 60: a crouching enemy no longer loses its footing every other frame, which made it miss half its leaps.",
]), ("1.3.1", [
    "No more black screen when a level starts: the game no longer switches your monitor to another refresh rate; the frame rate is capped instead.",
]), ("1.3.0", [
    "Enemies attack and lunge as often at 120 fps and Unlimited as at 60: their footing no longer flickers more at high frame rates.",
]), ("1.2.1", [
    "Enemy leaps, knock-back and debris slow down per second, not per frame: lunges at 120 fps match 60 fps.",
]), ("1.2.0", [
    "High frame rates: enemy animations, an area-damage effect and slow motion no longer run slow or stall above 120 fps.",
]), ("1.1.0", [
    "Sound mixed at 44.1 kHz / 16-bit instead of Miles' low-quality default.",
    "EAX reverb and 3D positional sound restored through DSOAL, with a headphone (HRTF) mode.",
]), ("1.0.0", [
    "Runs on Windows 10/11: fixed the DirectX check, the wrapper loading and the 3D start-up.",
    "DDrawCompat wrapper: high resolutions without changing your display, clean alt-tab.",
    "Correct widescreen view for any screen shape (4:3, 16:9, 21:9).",
    "HUD scaling, so health and ammo are readable at high resolutions.",
    "Frame rates above 60, with jump and walking physics measured at each rate.",
    "Crash fixes: the 'DrawPrim failed' freeze, a renderer list crash, losing focus quitting the game.",
    "Faster switch into a level (the 3D device is built once, not twice).",
    "Smooth menus at 1080p with a normal mouse cursor.",
    "Settings for anti-aliasing, texture filtering and menu sharpness.",
    "No more 'DirectInput could not acquire keyboard' quits: input is picked up again when the game gets focus.",
])]


# ----------------------------------------------------------------------------------------------- game folder logic
def res_path(name):
    return os.path.join(getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__))), name)


def sha(path):
    try:
        return hashlib.sha256(open(path, "rb").read()).hexdigest()
    except OSError:
        return None


def find_ci(folder, *parts):
    """Case-insensitive path lookup inside the game folder (the game mixes BMP/bmp, Splash/splash)."""
    for part in parts:
        try:
            match = next((f for f in os.listdir(folder) if f.lower() == part.lower()), None)
        except OSError:
            return None
        if not match:
            return None
        folder = os.path.join(folder, match)
    return folder


def registry_game_folder():
    for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\3DO\Requiem", 0, winreg.KEY_READ | view) as k:
                return winreg.QueryValueEx(k, "AppPath")[0].rstrip("\\/")
        except OSError:
            pass
    return None


def check_folder(folder):
    """-> (state, message). state: 'missing' | 'unknown' | 'ready' | 'installed'."""
    if not folder or not os.path.isfile(os.path.join(folder, "D3D.exe")):
        return "missing", "No D3D.exe in this folder."
    exe = os.path.join(folder, "D3D.exe")
    orig = exe + ".orig"
    if sha(orig if os.path.exists(orig) else exe) != GOG_D3D:
        return "unknown", "This D3D.exe is not the GOG v1.2 version this mod is made for."
    installed = sha(os.path.join(folder, "ddraw.dll")) == DDC and os.path.exists(orig) and os.path.exists(os.path.join(folder, INI))
    return ("installed", "Modern setup installed.") if installed else ("ready", "Found the game. Not installed yet.")


def install(folder, settings):
    exe = os.path.join(folder, "D3D.exe")
    if not os.path.exists(exe + ".orig"):
        shutil.copy2(exe, exe + ".orig")
    bk = os.path.join(folder, BACKUP)
    os.makedirs(bk, exist_ok=True)
    for name in ("ddraw.dll", "D3DImm.dll", "dsound.dll", "dsoal-aldrv.dll", "alsoft.ini"):
        p = os.path.join(folder, name)
        if os.path.exists(p) and sha(p) not in (DDC, DSOAL.get(name)) and not ours_ini(p) and not os.path.exists(os.path.join(bk, name)):
            shutil.copy2(p, os.path.join(bk, name))
    shutil.copyfile(res_path(os.path.join("ddrawcompat", "ddraw.dll")), os.path.join(folder, "ddraw.dll"))
    imm = os.path.join(folder, "D3DImm.dll")
    if os.path.exists(imm) and sha(imm) == DGV_D3DIMM:      # dgVoodoo leftover: backed up above
        os.remove(imm)
    apply_settings(folder, settings)


def restore(folder):
    exe = os.path.join(folder, "D3D.exe")
    if os.path.exists(exe + ".orig"):
        shutil.copy2(exe + ".orig", exe)
        os.remove(exe + ".orig")
    bk = os.path.join(folder, BACKUP)
    set_audio(folder, "off")
    set_hd(folder, "00")
    set_hud(folder, False)
    set_menu(folder, {"res": "640x480", "menures": "640", "mode": "exclusive"})
    for name in (MENU_DLL, MENU_CFG, "RequiemMenu.log"):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    for name in ("ddraw.dll", "D3DImm.dll", "dsound.dll", "dsoal-aldrv.dll", "alsoft.ini"):
        p, b = os.path.join(folder, name), os.path.join(bk, name)
        if os.path.exists(b):
            shutil.copy2(b, p)
        elif name == "ddraw.dll" and sha(p) == DDC:
            os.remove(p)
    for name in (INI, "DDrawCompat-D3D.log"):
        try:
            os.remove(os.path.join(folder, name))
        except OSError:
            pass
    shutil.rmtree(bk, ignore_errors=True)


GOG_ART = "a9184c50747ade7d12fa374367d9939c535ca565f6e1dd7e7c238b963e7d88da"   # Art\D3D\ReqArtD3.art, GOG v1.2
GOG_DAT = "f1d921140e03584bc6c7424a1e00c5014d9d8755f7cc3e036b3b85674afa7a83"   # Art\D3D\ReqArtD3.dat
HD_MAGIC, HD_MARK = b"RQHDPAK1", "ReqArtD3.hd"


MENU_MAGIC, MENU_DLL, MENU_CFG, MENU_MARK = b"RQMNPAK1", "RequiemMenu.dll", "RequiemMenu.cfg", "RequiemMenu.art"
GEN = os.path.join(os.environ.get("LOCALAPPDATA") or CONF_DIR, APP, "HD art")   # the HD art made on this PC
UPSCALER = os.path.join("realesrgan", "realesrgan-ncnn-vulkan.exe")             # bundled: res_path(UPSCALER)


def art_made():
    """MAKE HD ART finished (done.txt is written last)."""
    return os.path.exists(os.path.join(GEN, "done.txt"))


def art_old():
    """The HD art was made by an older MAKE HD ART (done.txt without "v2": dithered palette textures)."""
    try:
        return art_made() and "v2" not in open(os.path.join(GEN, "done.txt")).read()
    except OSError:
        return False


def hud_src():
    return os.environ.get("REQUIEM_MODERN_HUD") or (os.path.join(GEN, "hud") if art_made() else "")


def art_avail():
    """The HD options are shown only once their art exists."""
    hd = bool(hd_payload())
    return {"hd": hd, "hdfx": hd, "hdhud": os.path.isdir(hud_src()), "hdmenu": bool(payload(MENU_MAGIC, "REQUIEM_MODERN_MENU"))}


def payload(magic, env):
    """(path, offset, size) of the HD texture (RQHDPAK1) or menu-master (RQMNPAK1) payload: the file named by env
    when run from source, else the one MAKE HD ART made on this PC; None if absent."""
    dev = os.environ.get(env)
    if dev and os.path.exists(dev):
        return dev, 0, os.path.getsize(dev)
    p = os.path.join(GEN, "textures.bin" if magic == HD_MAGIC else "menu.bin")
    return (p, 0, os.path.getsize(p)) if art_made() and os.path.exists(p) else None


def hd_payload():
    """The HD texture payload (REQUIEM_MODERN_HD when run from source)."""
    return payload(HD_MAGIC, "REQUIEM_MODERN_HD")


def hd_installed(folder):
    """HD textures are in the archive: the marker is there AND the archive is not the original. (A reinstall or
    GOG's file check puts the original archive back and leaves the marker; that marker is stale.)"""
    d = find_ci(folder, "Art", "D3D")
    if not d or not os.path.exists(os.path.join(d, HD_MARK)):
        return False
    art, bart = os.path.join(d, "ReqArtD3.art"), os.path.join(folder, BACKUP, "ReqArtD3.art")
    try:
        if os.path.getsize(art) == (os.path.getsize(bart) if os.path.exists(bart) else 24761756):   # GOG v1.2 size
            return False
    except OSError:
        return False
    return True


# 16-bit textures that are character skins, not effects (they stay with "HD textures")
SKIN16 = {1166, 1167, 1168, 1169, 3001, 3016, 3053, 3248, 3260, 3271, 3280, 3318}


def is_effect(i, tex):
    """Fire, lightning, explosions, glows: the 16-bit single-frame textures (decoded header: +0xc frames, +0xe bpp)."""
    return tex[0xE] == 2 and tex[0xC] == 0 and not tex[0x10] & 0x80 and i not in SKIN16   # 0x80: grilles (hd_make)


def hd_sel(s):
    """Which texture groups are wanted: 'TF' with T = HD textures (walls, objects, characters), F = HD effects."""
    return ("1" if s.get("hd", "0") == "1" else "0") + ("1" if s.get("hdfx", "0") == "1" else "0")


def hd_current(folder, sel):
    """The texture archive holds this launcher's payload with this selection (1.7 and older markers: both groups)."""
    p = hd_payload()
    if not hd_installed(folder):
        return False
    try:
        m = open(os.path.join(find_ci(folder, "Art", "D3D"), HD_MARK)).read()
        import hd_make
        return bool(p) and f"payload {p[2]}" in m and f"sel {sel}" in m and f"keep {len(hd_make.KEEP)}" in m
    except (OSError, TypeError):
        return False


def tex_update_needed(folder, s):
    sel = hd_sel(s)
    return (sel != "00" and bool(hd_payload()) and not hd_current(folder, sel)) or (sel == "00" and hd_installed(folder))


def set_hud(folder, on):
    """HD HUD icons and digits (media/DIBs/HUD, made by MAKE HD ART into GEN/hud): on backs up each original once and
    writes the HD BMP (its header carries the original size, read by patch_d3d's HD HUD caves); off restores them."""
    src, d = hud_src(), find_ci(folder, "media", "DIBs", "HUD")
    if not d or not os.path.isdir(src):
        return
    bk = os.path.join(folder, BACKUP, "HUD")
    for root, _, names in os.walk(src):
        for n in names:
            rel = os.path.relpath(os.path.join(root, n), src)
            parts = rel.split(os.sep); tgt = find_ci(d, *parts[:-1]) if len(parts) > 1 else d
            if not tgt:
                continue
            cur = find_ci(tgt, parts[-1]) or os.path.join(tgt, parts[-1]); b = os.path.join(bk, rel)
            try:
                is_hd = open(cur, "rb").read(42)[38:42] == b"RQHD"
            except OSError:
                continue
            if on:
                if not is_hd and not os.path.exists(b):
                    os.makedirs(os.path.dirname(b), exist_ok=True); shutil.copyfile(cur, b)
                if open(cur, "rb").read() != open(os.path.join(src, rel), "rb").read():
                    shutil.copyfile(os.path.join(src, rel), cur)
            elif is_hd and os.path.exists(b):
                shutil.copyfile(b, cur)


def set_menu(folder, s):
    r"""Menus at the game resolution: RequiemMenu.dll (loaded by the patched D3D.exe) draws the 640x480 front end at
    the scale S = min(W/640, H/480) when RequiemMenu.cfg says "W H"; the menu art (media\DIBs except the HUD) is
    rebuilt from the bundled AI-upscaled masters at exactly S, so it is copied 1:1. Originals are kept in Modern
    Backup\DIBs; media\DIBs\RequiemMenu.art records what was built. Off (or no masters): originals, no cfg."""
    import menu_hd
    dibs = find_ci(folder, "media", "DIBs")
    dll, cfg = os.path.join(folder, MENU_DLL), os.path.join(folder, MENU_CFG)
    src = res_path(MENU_DLL)
    if os.path.exists(src) and sha(dll) != sha(src):
        shutil.copyfile(src, dll)
    w, h, scale, on, key, p = menu_want(folder, s)
    bk = os.path.join(folder, BACKUP, "DIBs")
    mark = os.path.join(dibs, MENU_MARK) if dibs else None
    extra = "nominimize\n" if s.get("mode", "borderless") == "borderless" else ""   # alt-tab keeps it on screen
    if not on:
        open(cfg, "w").write("640 480\n" + extra)
        if mark and os.path.exists(mark):
            for root, _, names in os.walk(bk):
                for n in names:
                    b = os.path.join(root, n); shutil.copyfile(b, os.path.join(dibs, os.path.relpath(b, bk)))
            os.remove(mark)
        return
    if not (os.path.exists(mark) and open(mark).read().strip() == key and menu_art_built(folder)):
        masters = None
        if p:
            with open(p[0], "rb") as f:
                f.seek(p[1]); masters = menu_hd.unpack(f.read(p[2]))
        for rel in list(menu_hd.images(dibs)):
            cur, b = os.path.join(dibs, rel), os.path.join(bk, rel)
            m = masters.get(rel.replace(os.sep, "/").lower()) if masters else None
            if masters and not m: continue
            if not os.path.exists(b):
                if open(cur, "rb").read(42)[38:42] == b"RQHD": continue   # HD without a backup: leave it
                os.makedirs(os.path.dirname(b), exist_ok=True); shutil.copyfile(cur, b)
            menu_hd.build_one(b, io.BytesIO(m) if m else None, cur, scale)
        open(mark, "w").write(key + "\n")
    open(cfg, "w").write(f"{w} {h}\n" + extra)


def menu_want(folder, s):
    """(w, h, scale, on, key, masters payload or None): what set_menu should put on disk. 'HD menu art' off = the
    original art resampled (Lanczos) to the scale."""
    w, h = map(int, s["res"].split("x")); scale = min(w / 640, h / 480)
    p = payload(MENU_MAGIC, "REQUIEM_MODERN_MENU") if s.get("hdmenu", "1") == "1" else None
    on = bool(s.get("menures", "game") == "game" and scale > 1 and find_ci(folder, "media", "DIBs"))
    return w, h, scale, on, f"{scale:.4f} " + (f"payload {p[2]}" if p else "original"), p


def menu_art_built(folder):
    """The menu art on disk really is the rebuilt one: the title screen carries the 'RQHD' header (a reinstall puts
    the originals back and leaves the marker)."""
    p = find_ci(folder, "media", "DIBs", "Splash01", "splash01.BMP")
    try:
        return bool(p) and open(p, "rb").read(42)[38:42] == b"RQHD"
    except OSError:
        return False


def menu_current(folder, s):
    """True when the menu art on disk matches these settings (no rebuild needed on Play)."""
    _, _, _, on, key, _ = menu_want(folder, s)
    dibs = find_ci(folder, "media", "DIBs")
    mark = os.path.join(dibs, MENU_MARK) if dibs else ""
    have = os.path.exists(mark) and menu_art_built(folder)
    return (not on and not have) or (on and have and open(mark).read().strip() == key)


def set_hd(folder, sel):
    """sel 'TF' (see hd_sel). Anything on: back up the GOG archive once, then write ReqArtD3.art/.dat with the
    payload's 4x textures of the chosen groups (literal-only PKWARE streams, which the game's explode() reads) and
    every other entry copied as it was. patch_d3d's HD caves keep texture coordinates at the original size.
    '00': put the backed-up originals back."""
    import art_build, hd_make
    on = sel != "00"
    d = find_ci(folder, "Art", "D3D")
    if not d:
        return
    art, dat, mark = (os.path.join(d, n) for n in ("ReqArtD3.art", "ReqArtD3.dat", HD_MARK))
    bk = os.path.join(folder, BACKUP); bart, bdat = os.path.join(bk, "ReqArtD3.art"), os.path.join(bk, "ReqArtD3.dat")
    if not on:
        if os.path.exists(mark) and os.path.exists(bart) and os.path.exists(bdat):
            shutil.copyfile(bart, art); shutil.copyfile(bdat, dat); os.remove(mark)
        return
    p = hd_payload()
    if not p or hd_current(folder, sel):
        return
    os.makedirs(bk, exist_ok=True)
    for src, dst, h in ((art, bart, GOG_ART), (dat, bdat, GOG_DAT)):
        if not os.path.exists(dst):
            if sha(src) != h:
                raise SystemExit(f"{os.path.basename(src)} is not the GOG original, so HD textures were not installed.")
            shutil.copyfile(src, dst)
    path, off, size = p
    data = hd_make.read_payload(path, off, size)
    hd, pos = {}, 4
    for _ in range(struct.unpack_from("<I", data, 0)[0]):
        i, n = struct.unpack_from("<2I", data, pos); t = data[pos + 8:pos + 8 + n]; pos += 8 + n
        if sel[1 if is_effect(i, t) else 0] == "1" and i not in hd_make.KEEP:   # KEEP: water, flat colours stay original
            hd[i] = t
    orig = open(bart, "rb").read(); offs = struct.unpack("<4001I", open(bdat, "rb").read())
    ends = sorted(o for o in offs if o != 0xFFFFFFFF) + [len(orig)]
    nxt = {o: ends[k + 1] for k, o in enumerate(ends[:-1])}
    new = [0xFFFFFFFF] * len(offs)
    with open(art + ".tmp", "wb") as f:
        for i, o in enumerate(offs):
            if o == 0xFFFFFFFF:
                continue
            new[i] = f.tell()
            if i in hd:
                z = art_build.implode_literal(hd[i]); f.write(struct.pack("<3I", len(hd[i]), 0, len(z)) + z)
            else:
                f.write(orig[o:nxt[o]])
    open(dat + ".tmp", "wb").write(struct.pack(f"<{len(new)}I", *new))
    os.replace(art + ".tmp", art); os.replace(dat + ".tmp", dat)
    open(mark, "w").write(f"{APP} {VERSION}: {len(hd)} HD textures, payload {size} sel {sel} keep {len(hd_make.KEEP)}\n")


def ours_ini(p):
    try:
        return open(p, "rb").read() == HRTF_INI.encode()
    except OSError:
        return False


def set_audio(folder, mode):
    """mode 'eax' / 'hrtf': DSOAL next to D3D.exe (Miles then finds EAX). 'off': only our copies are removed."""
    for name, h in DSOAL.items():
        p = os.path.join(folder, name)
        if mode == "off":
            if sha(p) == h: os.remove(p)
        elif sha(p) != h:
            shutil.copyfile(res_path(os.path.join("dsoal", name)), p)
    for name in DSOAL_DOCS:
        p = os.path.join(folder, name)
        if mode == "off":
            if os.path.exists(p): os.remove(p)
        else:
            shutil.copyfile(res_path(os.path.join("dsoal", name)), p)
    ini = os.path.join(folder, "alsoft.ini")
    if mode == "hrtf":
        open(ini, "w", encoding="utf-8", newline="\n").write(HRTF_INI)
    elif ours_ini(ini):
        os.remove(ini)


def aspect(w, h):
    g = math.gcd(w, h)
    return f"{w // g}:{h // g}"


def aspect_label(w, h):
    return "21:9" if 2.3 < w / h < 2.45 else aspect(w, h)   # 64:27 and 43:18 are both sold as 21:9


def write_ini(folder, s):
    path = os.path.join(folder, INI)
    lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
    managed = ("SupportedResolutions", "SupportedRefreshRates", "DisplayRefreshRate", "FpsLimiter", "VSync",
               "Antialiasing", "TextureFilter", "DisplayFilter", "FullscreenMode")
    keep = [l for l in lines if not l.startswith(";") and not re.match(r"\s*(%s)\s*=" % "|".join(managed), l)]
    out = [f"; DDrawCompat settings for D3D.exe, written by {APP} {VERSION}. Change them in {APP}.",
           f"Antialiasing = {s['aa']}", f"TextureFilter = {s['tex']}", f"DisplayFilter = {s['menu']}",
           f"FullscreenMode = {s.get('mode', 'borderless')}",
           "SupportedResolutions = " + ", ".join(f"{w}x{h}" for w, h in RESOLUTIONS),
           "SupportedRefreshRates = " + ("desktop" if s["fps"] == "unlimited" else s["fps"]),
           "DisplayRefreshRate = desktop"]   # never switch the monitor's rate: some go black at a non-desktop rate
    if s["fps"] == "unlimited":
        out.append("VSync = off")
    elif int(s["fps"]) != DHZ:   # the game vsyncs to the desktop rate, so cap it with the limiter instead
        out += ["VSync = off", f"FpsLimiter = flipend({s['fps']})"]
    open(path, "w", encoding="utf-8").write("\n".join(out + keep) + "\n")


def write_mode(folder, res):
    """Point Gamers\\latest.cfg's mode index (4 + n + 8: header skip, two 4-byte fields) at res."""
    cfg = os.path.join(folder, "Gamers", "latest.cfg")
    if not os.path.exists(cfg):
        return False
    data = bytearray(open(cfg, "rb").read())
    off = 4 + struct.unpack_from("<I", data, 0)[0] + 8
    if off + 4 > len(data):
        return False
    struct.pack_into("<I", data, off, sorted(RESOLUTIONS, key=lambda m: (m[1], m[0])).index(res))
    open(cfg, "wb").write(data)
    return True


def apply_settings(folder, s):
    w, h = map(int, s["res"].split("x"))
    write_ini(folder, s)
    set_audio(folder, s.get("audio", "eax"))
    set_hd(folder, hd_sel(s))
    set_hud(folder, s.get("hdhud", "0") == "1")
    set_menu(folder, s)
    game_cfg.write(folder, s)
    patch_d3d.build(os.path.join(folder, "D3D.exe"), aspect(w, h), int(s["hud"]))
    return write_mode(folder, (w, h))


LIVE_FMT = "<lII5f256s"   # RequiemMenu.dll's LIVE block: seq, flag mask, flags, sens, bright, sound, dialog, music, keys
F10_DIK = 0x44


def push_live(s):
    """Hand the game's own options to the running game (RequiemMenu.dll applies them when it gets the focus back)."""
    k = ctypes.windll.kernel32
    k.OpenFileMappingW.restype = k.MapViewOfFile.restype = ctypes.c_void_p
    k.MapViewOfFile.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_size_t]
    k.UnmapViewOfFile.argtypes = [ctypes.c_void_p]; k.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k.OpenFileMappingW(0xF001F, False, "Local\\RequiemModernLive")
    if not h:
        return False
    size = struct.calcsize(LIVE_FMT)
    v = k.MapViewOfFile(h, 0xF001F, 0, 0, size)
    if not v:
        k.CloseHandle(h); return False
    seq = struct.unpack_from("<l", ctypes.string_at(v, 4))[0]
    mask = flags = 0
    for key, bit in game_cfg.FLAGS.items():
        mask |= bit; flags |= bit if s.get(key) == "1" else 0
    keys = bytearray.fromhex(s["g_keys"]); keys[0xFF] = int(s["g_wheel"], 16)
    data = struct.pack(LIVE_FMT, seq + 1, mask, flags, *(int(s[f]) / 10 for f in ("g_sens", "g_bright", "g_sound", "g_dialog", "g_music")), bytes(keys))
    ctypes.memmove(v + 4, data[4:], size - 4); ctypes.memmove(v, data[:4], 4)   # seq last: the DLL sees a complete block
    k.UnmapViewOfFile(v); k.CloseHandle(h)
    return True


def free_f10(folder):
    """F10 opens Requiem Modern's settings in game; the game's own F10 (Take Screenshot) moves to F12 if that is free."""
    s = game_cfg.read(folder)
    if not s:
        return
    t = bytearray.fromhex(s["g_keys"]); a = t[F10_DIK]
    if a in (game_cfg.NONE, game_cfg.RESERVED):
        return
    if t[0x58] == game_cfg.NONE:
        t[0x58] = a
    t[F10_DIK] = game_cfg.NONE
    s["g_keys"] = t.hex(); game_cfg.write(folder, s)


def game_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq D3D.exe", "/FO", "CSV", "/NH"], capture_output=True,
                         text=True, creationflags=0x08000000).stdout
    k = ctypes.WinDLL("kernel32")
    for line in out.splitlines():
        try:
            pid = int(line.split(",")[1].strip('"'))
        except (IndexError, ValueError):
            continue
        h = k.OpenProcess(0x1000, False, pid); code = ctypes.c_ulong()
        if h and k.GetExitCodeProcess(h, ctypes.byref(code)) and code.value == 259:   # STILL_ACTIVE
            return True
    return False


def desktop():
    u = ctypes.WinDLL("user32")
    def mode(i):
        dm = ctypes.create_string_buffer(220); ctypes.memmove(ctypes.byref(dm, 68), ctypes.byref(ctypes.c_uint16(220)), 2)
        return struct.unpack_from("<IIII", dm, 172) if u.EnumDisplaySettingsW(None, i, dm) else None
    w, h, _, hz = mode(-1)
    rates, i = set(), 0
    while (m := mode(i)) is not None:
        if m[:2] == (w, h) and m[3] >= 60: rates.add(m[3])
        i += 1
    return w, h, sorted(rates), hz


# --------------------------------------------------------------------------------------------------- the options
DW, DH, RATES, DHZ = desktop()


def option_table():
    res = []
    for w, h in RESOLUTIONS[1:]:
        note = "your screen" if (w, h) == (DW, DH) else ("downscaled to your screen: sharper, slower" if w * h > DW * DH else "")
        res.append((f"{w}x{h}", f"{w} x {h}", aspect_label(w, h) + (f", {note}" if note else "")))
    fps = []
    for r in RATES:
        fps.append((str(r), f"{r} fps", {60: "Original. Jumps as designed.",
                                         120: "Twice as smooth. Enemies as at 60; jumps about 3% lower (measured).",
                                         180: "Very smooth. Enemies as at 60; jumps about 4% lower (measured)."}.get(
                    r, "Enemies as at 60; jumps about 3-4% lower (estimated).")))
    fps.append(("unlimited", "Unlimited", "Thousands of fps. Jumps about 5% lower. Heavy on the graphics card."))
    return [
        ("Display", "SCREEN", "res", "Resolution", res, f"{DW}x{DH}",
         "The size the game renders at. It is shown full screen at your desktop resolution without changing your "
         "display, and the view is widened to match the screen shape.", ["Applies when the game starts", "Higher = slower"]),
        ("Display", "SCREEN", "mode", "Display mode", [
            ("borderless", "Borderless", "A screen-sized window: instant alt-tab, the game stays visible behind other windows, overlays and recorders work."),
            ("exclusive", "Fullscreen", "Exclusive fullscreen: the game owns the screen. Alt-tab is slower; below your "
                                        "refresh rate the picture may tear.")], "borderless",
         "How the game takes over the screen. Neither changes your monitor's resolution or refresh rate. "
         "(A movable window isn't available: the game's own windowed mode is a broken developer leftover.)",
         ["Applies when the game starts"]),
        ("Display", "FRAME RATE", "fps", "Frame rate", fps, "120" if 120 in RATES else str(RATES[0]),
         "How many frames per second the game runs at. The game clock and enemies behave the same at every rate; "
         "jumps get slightly lower as the rate rises (3-5%, measured).", ["Applies when the game starts"]),
        ("Display", "INTERFACE", "menures", "Menu resolution", [
            ("game", "Game resolution", "Menus drawn at the game's resolution: AI-upscaled art and sharp text."),
            ("640", "640 x 480", "The original 640x480 menus, stretched to the screen.")], "game",
         "The resolution the menus, briefings and videos are drawn at. The menus keep their 4:3 shape, with black "
         "bars at the sides.", ["Applies when the game starts"]),
        ("Display", "INTERFACE", "hud", "HUD size", [("0", "Off", "Original size: small at high resolutions."),
                                                     ("720", "Medium", "1.5x at 1080p."), ("600", "Large", "1.8x at 1080p."),
                                                     ("480", "Extra large", "2.25x at 1080p: the size it had at 640x480.")], "720",
         "Makes the health, ammo and spell display bigger. It grows from its corners, so nothing moves to the "
         "middle of the screen.", ["Applies when the game starts"]),
        ("Graphics", "SMOOTHING", "aa", "Anti-aliasing", [("off", "Off", "Jagged edges, fastest."), ("msaa2x", "2x MSAA", "Light smoothing."),
                                                           ("msaa4x", "4x MSAA", "Smooth edges."), ("msaa8x", "8x MSAA", "Smoothest edges, slowest.")], "msaa4x",
         "Smooths the jagged, stair-stepped edges of 3D objects.", ["Applies when the game starts", "Higher = slower"]),
        ("Graphics", "SMOOTHING", "tex", "Texture filtering", [("app", "Game default", "As the game asks for."), ("bilinear", "Bilinear", "Smooth, blurry at a distance."),
                                                               ("trilinear", "Trilinear", "Smoother transitions between detail levels."),
                                                               ("af4x", "Anisotropic 4x", "Sharper surfaces seen at an angle."),
                                                               ("af8x", "Anisotropic 8x", "Sharper still."), ("af16x", "Anisotropic 16x", "Sharpest walls and floors.")], "af16x",
         "How sharp textures stay when you look along walls and floors.", ["Applies when the game starts"]),
        ("Graphics", "HD", "hd", "HD textures", [("0", "Off", "The original 1999 textures."),
                                                 ("1", "On", "2,574 textures in HD: walls, floors, objects, monsters and characters "
                                                         "(about 30 seconds to install, ~1 GB on disk).")], "0",
         "AI-upscaled (Real-ESRGAN) versions of the game's own textures, four times sharper or more, in their original "
         "colours. Changing it installs or removes them straight away; the originals are kept.",
         ["Applies when the game starts"]),
        ("Graphics", "HD", "hdfx", "HD effects", [("0", "Off", "The original effects."),
                                                  ("1", "On", "106 effect textures in HD: fire, lightning, explosions, glows.")], "0",
         "Effect textures upscaled 4x (smoothly, without AI, so they keep their original sparkle). The animated water "
         "always stays original.", ["Applies when the game starts"]),
        ("Graphics", "HD", "hdhud", "HD HUD icons", [("0", "Off", "The original HUD icons."),
                                                     ("1", "On", "The 63 HUD icons and digits 4x sharper; item labels stay crisp.")], "0",
         "The health, ammo, spell and weapon icons at the bottom of the screen.", ["Applies when the game starts"]),
        ("Graphics", "HD", "hdmenu", "HD menu art", [("1", "On", "AI-upscaled menu art at your resolution."),
                                                     ("0", "Off", "The original menu art, smoothly enlarged.")], "1",
         "The pictures in the menus, briefings and loading screens. Used when Menu resolution is Game resolution.",
         ["Applies when the game starts"]),
        ("Graphics", "MENUS", "menu", "Menu sharpness", [("point", "Point", "Pixel-sharp, slightly uneven pixels."), ("bilinear", "Bilinear", "Soft."),
                                                          ("bicubic", "Bicubic", "Soft, a little crisper."), ("lanczos", "Lanczos", "Sharp with smooth edges."),
                                                          ("spline", "Spline", "Similar to Lanczos.")], "lanczos",
         "How the picture is smoothed when it is stretched: the 640x480 menus, or a game resolution below your screen's.", ["Applies when the game starts"]),
        ("Audio", "3D SOUND", "audio", "3D audio", [("eax", "EAX (speakers)", "Reverb for each room and 3D positioning, as on a Sound Blaster."),
                                                    ("hrtf", "Headphones", "EAX plus HRTF: sounds placed around your head. Use with headphones."),
                                                    ("off", "Original", "Windows DirectSound, no reverb.")], "eax",
         "The game was made for Creative EAX sound cards: echoes in halls, damp tunnels and so on. DSOAL rebuilds "
         "EAX in software, so you hear it on any sound card.", ["Applies when the game starts"]),
        ("Gameplay", "START", "nomovies", "Skip intro videos", [("0", "Off", "Play the logo videos at start."), ("1", "On", "Go straight to the main menu.")], "0",
         "Skips the company logo videos when the game starts.", ["Applies when the game starts"]),
    ]


def game_options():
    """The game's own Options screens (Gamers/latest.cfg via game_cfg). Values None = a page of its own (keys)."""
    onoff = lambda off, on: [("0", "Off", off), ("1", "On", on)]
    steps = [(str(i), f"{i * 10}%", "") for i in range(11)]
    fl = lambda k: "1" if game_cfg.DEFAULT_FLAGS & game_cfg.FLAGS[k] else "0"
    df = lambda k: str(game_cfg.DEFAULT_FLOATS[k])
    note = ["The game's own option", "Changes live in game (F10)"]
    return [
        ("Game", "PICTURE", "g_bright", "Brightness", steps, df("g_bright"), "The game's brightness (gamma).", note),
        ("Game", "PICTURE", "g_crosshair", "Show crosshairs", onoff("No aiming cross.", "An aiming cross in the middle."), fl("g_crosshair"),
         "The aiming cross in the middle of the screen.", note),
        ("Game", "PICTURE", "g_hideweapon", "Hide weapon", onoff("You see the weapon in your hand.", "No weapon on screen."), fl("g_hideweapon"),
         "Hides the weapon model in front of you.", note),
        ("Game", "PICTURE", "g_shadows", "Show shadows", onoff("No shadows under characters.", "Shadows under characters."), fl("g_shadows"),
         "Shadows under characters and creatures.", note),
        ("Game", "PICTURE", "g_fx", "Special effects", onoff("Fewer particles and glows.", "All particles and glows."), fl("g_fx"),
         "The game's extra particle and light effects.", note),
        ("Game", "PICTURE", "g_dialogue", "Dialogue text", onoff("Spoken lines only.", "Subtitles for spoken lines."), fl("g_dialogue"),
         "Shows what characters say as text.", note),
        ("Audio", "GAME VOLUME", "g_sound", "Sound volume", steps, df("g_sound"), "Sound effects.", note),
        ("Audio", "GAME VOLUME", "g_dialog", "Dialogue volume", steps, df("g_dialog"), "Spoken lines.", note),
        ("Audio", "GAME VOLUME", "g_music", "Music volume", steps, df("g_music"), "The soundtrack.", note),
        ("Audio", "GAME VOLUME", "g_footsteps", "Footsteps", onoff("Silent footsteps.", "You hear your own footsteps."), fl("g_footsteps"),
         "Your own footstep sounds.", note),
        ("Controls", "MOUSE", "g_sens", "Mouse sensitivity", steps, df("g_sens"), "How far the view turns for a mouse movement.", note),
        ("Controls", "MOUSE", "g_freelook", "Mouse free look", onoff("The mouse turns left and right only.", "The mouse also looks up and down."),
         fl("g_freelook"), "Look around freely with the mouse.", note),
        ("Controls", "MOUSE", "g_invert", "Invert mouse", onoff("Mouse forward looks up.", "Mouse forward looks down."), fl("g_invert"),
         "Flips up and down for mouse look.", note),
        ("Controls", "MOUSE", "g_wheel", "Mouse wheel", [(v, n, "") for v, n in game_cfg.WHEEL], "44",
         "What the mouse wheel does (the game's Mouse Z Control).", note),
        ("Controls", "MOVEMENT", "g_run", "Always run", onoff("Walk unless Run is held.", "Run unless Run is held."), fl("g_run"),
         "Run by default.", note),
        ("Controls", "MOVEMENT", "g_analog", "Analog movement", onoff("Digital movement.", "Joystick moves with analog speed."), fl("g_analog"),
         "Analog movement with a joystick.", note),
        ("Controls", "MOVEMENT", "g_trackball", "Use trackball", onoff("Normal mouse.", "Trackball mode."), fl("g_trackball"),
         "The game's trackball mode.", note),
        ("Controls", "KEYS", "g_keys", "Key bindings", None, None,
         "Which key does what. Opens a list of every action: choose one and press the key you want for it.", note),
    ]


OPTIONS = option_table() + game_options()
TABS = ["Display", "Graphics", "Audio", "Gameplay", "Game", "Controls", "About"]


def load_conf():
    try:
        c = json.load(open(CONF, encoding="utf-8"))
    except (OSError, ValueError):
        c = {}
    s = c.setdefault("settings", {})
    if "hd" in s and "hdfx" not in s:   # 1.8 and older: one switch for textures, effects and the HUD
        s["hdfx"] = s["hdhud"] = s["hd"]
    for _, _, key, _, values, default, _, _ in OPTIONS:
        if values is not None and s.get(key) not in [v[0] for v in values]:
            s[key] = default
    return c


def save_conf(c):
    os.makedirs(CONF_DIR, exist_ok=True)
    json.dump(c, open(CONF, "w", encoding="utf-8"), indent=1)


# ------------------------------------------------------------------------------------------------------- the UI
GOLD, TEXT, DIM, PANEL = "#c9a24a", "#ece7dc", "#9c968c", "#e9e4d8"


class App:
    def __init__(self):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except OSError:
            pass
        self.conf = load_conf()
        self.game = self.conf.get("game") or registry_game_folder()
        self.read_game_options()
        self.pending = dict(self.conf["settings"])   # edited on the settings page; Apply installs them
        self.keys_row = self.keys_top = 0; self.capture = False
        self.ingame, self.game_proc, self.f10_event = False, None, None
        self.avail = art_avail()   # HD options only once MAKE HD ART has made the art
        self.making = None
        ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\RequiemModernLauncher")   # tells the game F10 works
        self.head_font = self.load_game_font()
        self.root = tk.Tk(); self.root.title(f"Requiem: Avenging Angel - {APP} {VERSION}"); self.root.resizable(False, False)
        self.root.geometry(f"{W}x{H}+{max(0, (DW - W) // 2)}+{max(0, (DH - H) // 2)}")
        self.c = tk.Canvas(self.root, width=W, height=H, highlightthickness=0, bg="#0c0b0a"); self.c.pack()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self.page, self.sel, self.tab, self.row, self.msg = "main", 0, 0, 0, None
        self.images = {}
        for key in ("<Up>", "<Down>", "<Left>", "<Right>", "<Return>", "<Escape>", "<q>", "<e>", "<p>", "<Delete>", "<r>", "<a>", "<d>"):
            self.root.bind(key, self.on_key)
        self.root.bind("<KeyPress>", self.on_any_key)
        self.c.bind("<Button-1>", lambda e: self.on_click(e, +1, 1)); self.c.bind("<Button-3>", lambda e: self.on_click(e, -1, 3))
        self.c.bind("<Button-2>", lambda e: self.on_click(e, +1, 2))
        self.c.bind("<Motion>", self.on_move)
        self.state, self.state_msg = check_folder(self.game)
        if self.state == "missing" or "game" not in self.conf:
            self.page = "setup"
        self.draw()

    def read_game_options(self):
        """The game's own options as the game last saved them (its Options screens write the same file)."""
        gs = game_cfg.read(self.game) if self.game else {}
        self.game_opts = bool(gs)
        self.conf["settings"].update(gs)

    # -- assets from the game folder
    def load_game_font(self):
        f = find_ci(self.game, "media", "fonts", "SMASH.TTF") if self.game else None
        if f and ctypes.windll.gdi32.AddFontResourceExW(f, 0x10, None):   # FR_PRIVATE
            return "Smash"
        return "Georgia"

    def background(self, key, splash, darken, art_scale=None):
        """Game art as the page background. art_scale: draw the art at that scale in the top-left (keeps the title
        art's logo a sensible size), over a blurred, darkened cover-fill of the same art, faded together."""
        tag = (key, self.game)
        if tag not in self.images:
            path = find_ci(self.game, "media", "dibs", splash.split("/")[0], splash.split("/")[1]) if self.game else None
            src = Image.open(path).convert("RGB") if path else Image.new("RGB", (640, 480), "#1a1612")
            hd = open(path, "rb").read(46) if path else b""
            if art_scale and hd[38:42] == b"RQHD":   # HD menu art: drawn at its original (logical) size
                art_scale *= struct.unpack_from("<H", hd, 42)[0] / src.width
            cover = max(W / src.width, H / src.height)
            im = src.resize((round(src.width * cover), round(src.height * cover)), Image.LANCZOS).crop((0, 0, W, H))
            if art_scale:
                from PIL import ImageFilter
                im = Image.blend(im.filter(ImageFilter.GaussianBlur(18)), Image.new("RGB", (W, H), "#08070a"), 0.45)
                src = src.crop((0, 0, src.width, round(src.height * 0.82)))     # title art: drop its copyright line
                art = src.resize((round(src.width * art_scale), round(src.height * art_scale)), Image.LANCZOS)
                F = 170   # fade the art's right and bottom edges into the blurred fill
                fx = Image.linear_gradient("L").rotate(270).resize((F, art.height))         # 255 -> 0 left to right
                fy = Image.linear_gradient("L").rotate(180).resize((art.width, F))          # 255 -> 0 top to bottom
                fade = Image.new("L", art.size, 255)
                fade.paste(fx, (art.width - F, 0))
                fade = ImageChops.darker(fade, Image.new("L", art.size, 255))
                bottom = Image.new("L", art.size, 255); bottom.paste(fy, (0, art.height - F))
                fade = ImageChops.darker(fade, bottom)
                im.paste(art, (0, 0), fade)
            # darkness: overall `darken`, more on the left (menu side, main page) and towards the bottom (status row)
            base = Image.new("L", (W, H), int(255 * darken))
            left = Image.linear_gradient("L").rotate(270).resize((round(W * 0.55), H)).point(lambda v: int(v * 0.55))
            side = Image.new("L", (W, H), 0)
            if key == "main":
                side.paste(left, (0, 0))
            low = Image.new("L", (W, H), 0)
            low.paste(Image.linear_gradient("L").resize((W, 200)).point(lambda v: int(v * 0.7)), (0, H - 200))
            shade = ImageChops.lighter(ImageChops.lighter(base, side), low)
            im = Image.composite(Image.new("RGB", (W, H), "#08070a"), im, shade)
            self.images[tag] = ImageTk.PhotoImage(im)
        return self.images[tag]

    # -- drawing
    def text(self, x, y, s, size=14, color=TEXT, anchor="nw", head=False, **kw):
        return self.c.create_text(x, y, text=s, fill=color, anchor=anchor, font=(self.head_font if head else "Segoe UI", size), **kw)

    def hints(self, items):
        x = W - 48
        for key, label in reversed(items):
            t = self.text(x, H - 40, label, 11, DIM, "e"); x = self.c.bbox(t)[0] - 10
            b = self.text(x, H - 40, key, 10, "#111", "e"); bb = self.c.bbox(b)
            r = self.c.create_rectangle(bb[0] - 6, bb[1] - 3, bb[2] + 6, bb[3] + 3, fill="#cfc9bd", outline=""); self.c.tag_raise(b)
            x = bb[0] - 30

    def main_items(self):
        installed = self.state == "installed"
        return [("PLAY", self.play, "Starts the game with your applied settings. While you play, F10 opens the settings."),
                ("SETTINGS", lambda: self.goto("settings"), "Resolution, frame rate, HUD size and picture options."
                 + ("  You have changes that are not applied yet." if self.dirty() else "")),
                ("REPAIR" if installed else "INSTALL", self.do_install,
                 "Puts the modern files back (wrapper, its settings, patched D3D.exe) if something replaced them, "
                 "e.g. a GOG update or file check. Your settings are kept." if installed else
                 "Installs the modern setup into the game folder. Everything it replaces is backed up first."),
                *([("MAKE HD ART", self.make_art,
                    "Makes HD textures, HUD icons and menu art from your own game files with the bundled AI upscaler "
                    "(Real-ESRGAN). Done once; then turn the HD options on in Settings, Graphics.")] if self.state in ("ready", "installed") and not art_made() else
                  [("REMAKE HD ART", self.make_art,
                    "This version makes cleaner HD textures (no grain on smooth surfaces). Takes 15 to 20 minutes; your "
                    "current HD art keeps working until it is done.")] if self.state in ("ready", "installed") and art_old() else []),
                ("RESTORE ORIGINAL GAME", self.do_restore, "Removes the modern setup and puts every original file back."),
                ("GAME FOLDER", lambda: self.goto("setup"), "Choose a different Requiem folder."),
                ("QUIT", self.quit, "Close the launcher.")]

    def draw(self):
        self.c.delete("all"); self.hits = []
        getattr(self, "draw_" + self.page)()
        if self.msg:
            self.c.create_rectangle(0, 0, W, H, fill="#000", stipple="gray50", outline="")
            self.c.create_rectangle(W / 2 - 330, H / 2 - 110, W / 2 + 330, H / 2 + 110, fill="#16130f", outline=GOLD, width=2)
            self.text(W / 2, H / 2 - 70, self.msg[0], 22, GOLD, "n", head=True)
            self.text(W / 2, H / 2 - 20, self.msg[1], 12, TEXT, "n", width=600, justify="center")
            self.text(W / 2, H / 2 + 80, "Enter / click to continue", 10, DIM, "n")

    def draw_main(self):
        self.c.create_image(0, 0, image=self.background("main", "Splash01/splash01.BMP", 0.05, 1.25), anchor="nw")
        items = self.main_items(); step = 46 if len(items) <= 6 else 41
        self.text(76, 258 + len(items) * step + 8, items[self.sel][2], 11, DIM, width=760)
        for i, (label, _, _) in enumerate(items):
            y = 258 + i * step
            if i == self.sel:
                self.c.create_rectangle(56, y + 6, 61, y + 40, fill=GOLD, outline="")
            t = self.text(76, y, label, 26, TEXT if i == self.sel else "#bdb6aa", head=True)
            self.hits.append((self.c.bbox(t), ("main", i)))
        cells = [("GAME", {"installed": "Ready to play", "ready": "Not installed", "unknown": "Unsupported version",
                           "missing": "Folder not set"}[self.state]),
                 ("WRAPPER", "DDrawCompat 0.7.2"), ("VERSION", f"{APP} {VERSION}")]
        for i, (k, v) in enumerate(cells):
            self.text(76 + i * 230, H - 120, k, 10, DIM); self.text(76 + i * 230, H - 98, v, 12)
        self.text(76, H - 62, self.game or "", 9, DIM)
        self.hints([("Enter", "Select"), ("Esc", "Quit")])

    def draw_making(self):
        m = self.making
        self.c.create_image(0, 0, image=self.background("setup", "Splash01/splash01.BMP", 0.25, 1.25), anchor="nw")
        self.text(76, 262, "MAKING HD ART", 30, GOLD, head=True)
        self.text(76, 314, "Your game's textures, HUD icons and menu art are being upscaled on this PC with Real-ESRGAN. "
                           "This is done once. You can use your PC meanwhile; the graphics card is busy.", 12, width=760)
        self.text(76, 392, m["label"], 13)
        x0, y0, x1 = 76, 424, 836
        self.c.create_rectangle(x0, y0, x1, y0 + 12, outline="#5a5245", fill="#16130f")
        self.c.create_rectangle(x0, y0, x0 + (x1 - x0) * min(1.0, m["frac"]), y0 + 12, outline="", fill=GOLD)
        e = int(time.time() - m["t0"])
        self.text(76, 446, f"{int(m['frac'] * 100)}%      {e // 3600}:{e // 60 % 60:02d}:{e % 60:02d} so far", 11, DIM)
        self.hints([("Esc", "Cancel")])

    def make_art(self):
        """MAKE HD ART: hd_make.make on a worker thread from the game's original files (the launcher's backups where
        it has replaced them) into GEN; this page shows its progress."""
        if game_running():
            self.say("GAME IS RUNNING", "Close Requiem first, then try again."); return
        d, bk = find_ci(self.game, "Art", "D3D"), os.path.join(self.game, BACKUP)
        art = next((p for p in (os.path.join(bk, "ReqArtD3.art"), os.path.join(d or "", "ReqArtD3.art"))
                    if os.path.exists(p) and sha(p) == GOG_ART), None)
        dibs = find_ci(self.game, "media", "DIBs")
        if not art or not dibs:
            self.say("CANNOT MAKE HD ART", "The game's original textures (Art\\D3D\\ReqArtD3.art from GOG v1.2) are not in "
                                           "this folder. Reinstall the game or let GOG check its files, then try again."); return
        os.makedirs(os.path.dirname(GEN), exist_ok=True)
        if shutil.disk_usage(os.path.dirname(GEN)).free < 5e9:
            self.say("NOT ENOUGH SPACE", "Making the HD art needs about 5 GB free on " + os.path.splitdrive(GEN)[0]
                     + " while it works (about 1 GB once it is done)."); return
        m = self.making = {"label": "Starting", "frac": 0.0, "t0": time.time(), "done": None, "cancel": False, "quit": False}
        work = os.path.join(os.path.dirname(GEN), "HD art work")

        def progress(label, frac):
            if m["cancel"]: raise InterruptedError("cancelled")
            m["label"], m["frac"] = label, frac

        def run():
            import hd_make
            try:
                hd_make.EXE = res_path(UPSCALER)
                src = hd_make.originals(dibs, bk, os.path.join(work, "DIBs"))
                ok = hd_make.make(art, art[:-4] + ".dat", src, GEN + " new", progress)   # the old art stays until done
                shutil.rmtree(GEN, ignore_errors=True); os.replace(GEN + " new", GEN)
                m["done"] = ("ok", ok)
            except BaseException as ex:
                shutil.rmtree(GEN + " new", ignore_errors=True)
                m["done"] = ("cancel" if m["cancel"] else "error", f"{type(ex).__name__}: {ex}")
            finally:
                shutil.rmtree(work, ignore_errors=True)
        threading.Thread(target=run, daemon=True).start()
        self.page = "making"; self.draw()
        self.root.after(500, self.watch_making)

    def watch_making(self):
        m = self.making
        if m["done"] is None:
            self.draw(); self.root.after(500, self.watch_making); return
        if m["quit"]:
            self.root.destroy(); return
        kind, info = m["done"]
        self.making, self.avail, self.page, self.sel = None, art_avail(), "main", 0
        if kind == "ok":
            self.say("HD ART READY", "Turn on the HD options in Settings, Graphics, and Apply." + ("" if info else
                     " Your graphics card could not run the AI upscaler, so the textures were enlarged smoothly instead "
                     "and HD HUD icons and HD menu art are not available."))
        elif kind == "cancel":
            self.say("CANCELLED", "No new HD art was made." + (" Your existing HD art is unchanged." if art_made() else ""))
        else:
            self.say("COULD NOT MAKE HD ART", info)

    def quit(self):
        if self.making:   # stop the upscaler first; watch_making closes the window when it has
            self.making["cancel"] = self.making["quit"] = True; self.making["label"] = "Cancelling"; return
        self.root.destroy()

    def draw_setup(self):
        self.c.create_image(0, 0, image=self.background("setup", "Splash01/splash01.BMP", 0.25, 1.25), anchor="nw")
        self.text(76, 262, "GAME FOLDER", 30, GOLD, head=True)
        self.text(76, 314, "Point this at your Requiem: Avenging Angel folder (the one with D3D.exe). The modern setup "
                           "is installed there; everything it replaces is backed up first and can be restored.", 12, width=760)
        self.text(76, 382, self.game or "(not set)", 13, TEXT)
        self.text(76, 410, self.state_msg, 11, GOLD if self.state in ("ready", "installed") else "#e07a5f")
        items = [("BROWSE...", self.browse)]
        if self.state in ("ready", "installed"):
            items.insert(0, ("USE THIS FOLDER", self.use_folder))
        for i, (label, _) in enumerate(items):
            y = 462 + i * 50
            if i == self.sel:
                self.c.create_rectangle(56, y + 6, 61, y + 38, fill=GOLD, outline="")
            t = self.text(76, y, label, 22, TEXT if i == self.sel else "#bdb6aa", head=True)
            self.hits.append((self.c.bbox(t), ("setup", i)))
        self.setup_items = items
        self.hints([("Enter", "Select")] + ([("Esc", "Back")] if "game" in self.conf else []))

    def tab_rows(self):   # the game's own options (g_*) only once the game has written its options file
        return [o for o in OPTIONS if o[0] == TABS[self.tab] and (self.game_opts or not o[2].startswith("g_"))
                and self.avail.get(o[2], True)]

    def draw_settings(self):
        self.c.create_image(0, 0, image=self.background("settings", "Splash06/splash06.BMP", 0.8), anchor="nw")
        x = 48
        b = self.text(x, 30, "Q", 10, "#111"); bb = self.c.bbox(b)
        self.c.create_rectangle(bb[0] - 6, bb[1] - 3, bb[2] + 6, bb[3] + 3, fill="#cfc9bd", outline=""); self.c.tag_raise(b)
        x = bb[2] + 24
        for i, name in enumerate(TABS):
            t = self.text(x, 26, name.upper(), 15, TEXT if i == self.tab else DIM, head=True)
            bb = self.c.bbox(t)
            if i == self.tab:
                self.c.create_rectangle(bb[0], bb[3] + 4, bb[2], bb[3] + 6, fill=GOLD, outline="")
            self.hits.append((bb, ("tab", i))); x = bb[2] + 34
        b = self.text(x, 30, "E", 10, "#111"); bb = self.c.bbox(b)
        self.c.create_rectangle(bb[0] - 6, bb[1] - 3, bb[2] + 6, bb[3] + 3, fill="#cfc9bd", outline=""); self.c.tag_raise(b)
        self.text(W - 48, 26, "IN GAME" if self.ingame else "SETTINGS", 18, GOLD if self.ingame else TEXT, "ne", head=True)
        self.c.create_line(48, 68, W - 48, 68, fill="#3a352d")
        if TABS[self.tab] == "About":
            self.draw_about()
        else:
            self.draw_option_rows()
        if self.dirty():   # Apply / Discard, bottom left
            self.text(64, H - 74, f"{len(self.changed())} CHANGE{'S' if len(self.changed()) > 1 else ''} NOT APPLIED", 11, GOLD)
            x = 64
            for label, kind in (("APPLY", "apply"), ("DISCARD", "discard")):
                t = self.text(x + 14, H - 52, label, 13, "#1a1712" if kind == "apply" else TEXT, head=True); bb = self.c.bbox(t)
                r = self.c.create_rectangle(bb[0] - 14, bb[1] - 6, bb[2] + 14, bb[3] + 6, fill=GOLD if kind == "apply" else "",
                                            outline=GOLD); self.c.tag_raise(t)
                self.hits.append(((bb[0] - 14, bb[1] - 6, bb[2] + 14, bb[3] + 6), (kind, 0))); x = bb[2] + 40
            self.hints([("< >", "Change"), ("Del", "Default"), ("A", "Apply"), ("D", "Discard"), ("Esc", "Back")])
        elif self.ingame:
            self.hints([("< >", "Change"), ("Del", "Default"), ("R", "Reset page"), ("Esc", "Back to game")])
        else:
            self.hints([("< >", "Change"), ("Del", "Default"), ("R", "Reset page"), ("P", "Play"), ("Esc", "Back")])

    def draw_option_rows(self):
        rows, s = self.tab_rows(), self.pending
        if not rows and TABS[self.tab] in ("Game", "Controls"):
            self.text(64, 100, "Start the game once first", 16, GOLD, head=True)
            self.text(64, 140, "These are the game's own options (its Options screens). The game creates its options "
                               "file the first time it runs; after that you can change them here.", 12, width=620)
            return
        groups = len({r[1] for r in rows})
        step = min(50, int((H - 200 - groups * 30) / max(1, len(rows))))
        y, group = 96, None
        for i, (_, grp, key, label, values, default, desc, tags) in enumerate(rows):
            if grp != group:
                self.text(64, y, grp, 13, GOLD, head=True); y += 30; group = grp
                self.c.create_line(64, y - 4, 690, y - 4, fill="#3a352d")
            sel = i == self.row
            if sel:
                self.c.create_rectangle(56, y, 690, y + step - 6, fill=PANEL, outline="")
            col = "#1a1712" if sel else TEXT
            changed = s.get(key) != self.conf["settings"].get(key)
            self.text(76, y + (step - 6) // 2, label + ("  \u2022" if changed else ""), 13, col, "w")
            if values is None:   # a page of its own
                self.text(674, y + (step - 6) // 2, "Edit  \u25b6", 12, GOLD if changed and not sel else col, "e")
                self.hits.append(((56, y, 690, y + step - 6), ("row", i))); y += step
                continue
            idx = [v[0] for v in values].index(s[key])
            vt = self.text(650, y + (step - 6) // 2 - 10, values[idx][1], 12, GOLD if changed and not sel else col, "ne")
            vb = self.c.bbox(vt)
            if sel:   # the arrows are buttons: < steps down, > steps up (generous click areas)
                ay = y + (step - 6) // 2 - 10
                lb = self.c.bbox(self.text(vb[0] - 14, ay, "\u25c0", 11, col, "ne"))
                rb = self.c.bbox(self.text(674, ay, "\u25b6", 11, col, "ne"))
                self.hits.append(((lb[0] - 10, y, lb[2] + 6, y + step - 6), ("dec", i)))
                self.hits.append(((rb[0] - 6, y, 690, y + step - 6), ("inc", i)))
            dots_w = 10 * len(values); dx = 650 - dots_w
            for j in range(len(values)):
                self.c.create_rectangle(dx + j * 10, y + step - 16, dx + j * 10 + 7, y + step - 14, fill=(col if j == idx else "#77716a"), outline="")
            self.hits.append(((56, y, 690, y + step - 6), ("row", i)))
            y += step
        if rows:
            self.draw_info(rows[min(self.row, len(rows) - 1)])

    def keys_page_info(self, x):
        b = game_cfg.bindings(self.pending["g_keys"]); applied = game_cfg.bindings(self.conf["settings"]["g_keys"])
        n = sum(1 for a in range(len(game_cfg.ACTIONS)) if b.get(a, []) != applied.get(a, []))
        self.text(x, 220, f"{len(game_cfg.ACTIONS)} actions, {sum(len(v) for v in b.values())} keys bound."
                  + (f"\n{n} changed, not applied yet." if n else ""), 11, GOLD if n else TEXT, width=460)

    def draw_info(self, opt):
        _, _, key, label, values, default, desc, tags = opt
        if values is None:
            self.c.create_line(730, 90, 730, H - 90, fill="#3a352d")
            self.text(760, 96, label, 24, TEXT, head=True)
            self.text(760, 146, desc, 11, "#d8d2c6", width=460)
            self.keys_page_info(760)
            return
        x, cur = 760, self.pending[key]
        self.c.create_line(730, 90, 730, H - 90, fill="#3a352d")
        self.text(x, 96, label, 24, TEXT, head=True)
        t = self.text(x, 146, desc, 11, "#d8d2c6", width=460); y = self.c.bbox(t)[3] + 16
        for v, name, note in values:
            if v == cur:
                self.c.create_rectangle(x - 10, y + 2, x - 7, y + 18, fill=GOLD, outline="")
            self.text(x, y, name, 11, GOLD if v == cur else TEXT)
            t = self.text(x + 150, y, note, 10, DIM, width=310); y = max(y + 22, self.c.bbox(t)[3] + 6)
        y += 8
        for tag in tags:
            t = self.text(x + 8, y + 4, tag, 9, "#cfc9bd"); bb = self.c.bbox(t)
            r = self.c.create_rectangle(bb[0] - 8, bb[1] - 4, bb[2] + 8, bb[3] + 4, outline="#5a544a"); x2 = bb[2] + 24
            x = x2
        self.text(760, y + 40, "Default: " + next(n for v, n, _ in values if v == default), 10, DIM)
        if cur != self.conf["settings"].get(key):
            self.text(760, y + 62, "Applied now: " + next((n for v, n, _ in values if v == self.conf["settings"].get(key)), "?")
                      + "   (press Apply to use the new choice)", 10, GOLD)

    def draw_about(self):
        y = 96
        for ver, items in CHANGES:
            self.text(64, y, f"VERSION {ver}", 13, GOLD, head=True); y += 32
            for it in items:
                t = self.text(76, y, "\u2022  " + it, 11, TEXT, width=620); y = self.c.bbox(t)[3] + 8
        x = 760
        self.c.create_line(730, 90, 730, H - 90, fill="#3a352d")
        self.text(x, 96, APP, 24, TEXT, head=True)
        self.text(x, 146, f"Version {VERSION} for Requiem: Avenging Angel (GOG v1.2, Direct3D).\n\nGame folder:\n{self.game}\n\n"
                          "Uses DDrawCompat 0.7.2 by narzoul (0BSD licence). HD art is made on your PC with Real-ESRGAN "
                          "by Xintao Wang et al. (realesrgan-ncnn-vulkan, MIT; ncnn by Tencent, BSD-3). The menus here use the game's own art and font, "
                          "read from your game folder.\n\nRestore original game (main menu) puts back every file this "
                          "mod replaced.", 11, "#d8d2c6", width=460)

    # -- input
    def on_move(self, e):
        for bb, (kind, i) in self.hits:
            if bb and bb[0] <= e.x <= bb[2] and bb[1] <= e.y <= bb[3]:
                if kind in ("main", "setup") and self.sel != i: self.sel = i; self.draw()
                if kind == "row" and self.row != i: self.row = i; self.draw()
                return

    def on_click(self, e, step, button=None):
        if self.msg:
            self.msg = None; self.draw(); return
        if self.page == "keys" and self.capture:
            dik = {1: 0xFC, 3: 0xFD, 2: 0xFE}.get(button or (1 if step > 0 else 3))
            self.pending["g_keys"] = game_cfg.bind(self.pending["g_keys"], dik, self.keys_row)
            self.capture = False; self.draw(); return
        for bb, (kind, i) in self.hits:
            if bb and bb[0] <= e.x <= bb[2] and bb[1] <= e.y <= bb[3]:
                if kind == "main": self.sel = i; self.main_items()[i][1]()
                elif kind == "setup": self.sel = i; self.setup_items[i][1]()
                elif kind == "tab": self.tab, self.row = i, 0; self.draw()
                elif kind in ("dec", "inc"): self.row = i; self.change(-1 if kind == "dec" else 1)
                elif kind == "row":
                    self.row = i
                    if self.tab_rows()[i][4] is None: self.goto_keys()
                    else: self.change(step)
                elif kind == "key": self.keys_row = i; self.capture = True; self.draw()
                elif kind == "apply": self.apply()
                elif kind == "discard": self.discard()
                return

    def on_key(self, e):
        k = e.keysym
        if self.page == "making":
            if k == "Escape": self.making["cancel"] = True; self.making["label"] = "Cancelling"
            return
        if self.page == "keys" and not self.msg:
            self.keys_input(k, e); return
        if self.msg:
            if k in ("Return", "Escape"): self.msg = None; self.draw()
            return
        if self.page in ("main", "setup"):
            items = self.main_items() if self.page == "main" else self.setup_items
            if k == "Up": self.sel = (self.sel - 1) % len(items)
            elif k == "Down": self.sel = (self.sel + 1) % len(items)
            elif k == "Return": items[self.sel][1](); return
            elif k == "Escape":
                if self.page == "main": self.quit(); return
                if "game" in self.conf: self.goto("main"); return
            self.draw(); return
        rows = self.tab_rows()
        if k == "Escape":
            if self.ingame: self.back_to_game()
            else: self.goto("main")
            return
        if k == "a" and self.dirty(): self.apply(); return
        if k == "d" and self.dirty(): self.discard(); return
        if k in ("q", "e"): self.tab, self.row = (self.tab + (1 if k == "e" else -1)) % len(TABS), 0
        elif k == "Up" and rows: self.row = (self.row - 1) % len(rows)
        elif k == "Down" and rows: self.row = (self.row + 1) % len(rows)
        elif k in ("Left", "Right") and rows and rows[self.row][4] is not None: self.change(1 if k == "Right" else -1); return
        elif k in ("Return", "Right") and rows and rows[self.row][4] is None: self.goto_keys(); return
        elif k == "Delete" and rows and rows[self.row][4] is not None: self.pending[rows[self.row][2]] = rows[self.row][5]
        elif k == "r":
            for o in rows:
                if o[4] is not None: self.pending[o[2]] = o[5]
        elif k == "p" and not self.ingame: self.play(); return
        self.draw()

    def change(self, step):
        _, _, key, _, values, _, _, _ = self.tab_rows()[self.row]
        keys = [v[0] for v in values]
        self.pending[key] = keys[(keys.index(self.pending[key]) + step) % len(keys)]
        self.draw()

    def changed(self):
        return [k for k, v in self.pending.items() if v != self.conf["settings"].get(k)]

    def dirty(self):
        return bool(self.changed())

    def discard(self):
        self.pending = dict(self.conf["settings"]); self.draw()

    def apply(self):
        """Install the pending settings into the game folder (wrapper settings, exe patches, HD textures, HUD, menu
        art) and make them the applied ones. In game (F10): the game's own options go in live (RequiemMenu.dll), the
        rest is saved and installed by the next Play."""
        if self.ingame:
            changed = self.changed()
            live = [k for k in changed if k.startswith("g_")]
            game_cfg.write(self.game, self.pending)
            ok = push_live(self.pending) if live else True
            self.conf["settings"] = dict(self.pending); save_conf(self.conf)
            later = len(changed) - len(live)
            self.say("CHANGES APPLIED", (f"{len(live)} game option{'s' if len(live) != 1 else ''} changed live; they take hold "
                                         "when you return to the game (Escape). " if live and ok else "")
                     + (f"{later} other change{'s' if later != 1 else ''} take{'s' if later == 1 else ''} effect the next time you start the game from here."
                        if later else ""))
            return
        if self.state != "installed":
            self.say("NOT INSTALLED", "Install the modern setup first (main menu)."); return
        if game_running():
            self.say("GAME IS RUNNING", "Close Requiem first, then apply your changes."); return
        s = self.pending
        if tex_update_needed(self.game, s):
            self.say("APPLYING", "Writing the texture archive. This takes about half a minute.")
        elif not menu_current(self.game, s):
            self.say("APPLYING", "Drawing the menu art for " + s["res"].replace("x", " x ") + ". This takes a few seconds.")
        else:
            self.say("APPLYING", "Writing your settings.")
        self.root.update()
        try:
            apply_settings(self.game, s)
        except (Exception, SystemExit) as ex:
            self.say("COULD NOT APPLY", str(ex)); return
        n = len(self.changed())
        self.conf["settings"] = dict(s); save_conf(self.conf)
        self.say("CHANGES APPLIED", f"{n} change{'s' if n > 1 else ''} installed in the game folder. They take effect "
                                    "the next time the game starts.")

    # -- key bindings page
    def goto_keys(self):
        if not self.game_opts: return
        self.page, self.capture = "keys", False; self.draw()

    def draw_keys(self):
        self.c.create_image(0, 0, image=self.background("settings", "Splash06/splash06.BMP", 0.8), anchor="nw")
        self.text(48, 26, "KEY BINDINGS", 18, TEXT, head=True)
        self.text(W - 48, 26, "CONTROLS", 15, DIM, "ne", head=True)
        self.c.create_line(48, 68, W - 48, 68, fill="#3a352d")
        b = game_cfg.bindings(self.pending["g_keys"]); applied = game_cfg.bindings(self.conf["settings"]["g_keys"])
        n, vis = len(game_cfg.ACTIONS), 12
        self.keys_row = max(0, min(self.keys_row, n - 1))
        self.keys_top = max(0, min(self.keys_top, n - vis))
        if self.keys_row < self.keys_top: self.keys_top = self.keys_row
        if self.keys_row >= self.keys_top + vis: self.keys_top = self.keys_row - vis + 1
        y = 86
        for a in range(self.keys_top, min(n, self.keys_top + vis)):
            sel = a == self.keys_row
            if sel: self.c.create_rectangle(56, y, 900, y + 38, fill=PANEL, outline="")
            col = "#1a1712" if sel else TEXT
            changed = b.get(a, []) != applied.get(a, [])
            self.text(76, y + 19, game_cfg.ACTIONS[a] + ("  \u2022" if changed else ""), 13, col, "w")
            keys = "   ".join(game_cfg.key_name(k) for k in b.get(a, [])) or "(none)"
            if sel and self.capture: keys = "Press a key or mouse button...  (Esc cancels)"
            self.text(880, y + 19, keys, 12, GOLD if (changed and not sel) or (sel and self.capture) else col, "e")
            self.hits.append(((56, y, 900, y + 38), ("key", a))); y += 44
        self.c.create_rectangle(912, 86 + self.keys_top * 44 * vis // n, 916, 86 + (self.keys_top + vis) * 44 * vis // n, fill=GOLD, outline="")
        self.text(940, 96, "Choose an action and press the key you want for it. A key does one thing, so it leaves "
                           "the action it had. Delete clears an action's keys. Escape and a few other keys are reserved "
                           "by the game.", 11, "#d8d2c6", width=300)
        if self.dirty():
            self.text(940, 250, "Changes are applied from the Settings page (Apply).", 11, GOLD, width=300)
        self.hints([("Enter", "Change key"), ("Del", "Clear"), ("Esc", "Back")])

    def keys_input(self, k, e=None):
        if self.capture:
            if k == "Escape": self.capture = False; self.draw(); return
            if e is None: return
            vsc = ctypes.windll.user32.MapVirtualKeyW(e.keycode, 4)   # MAPVK_VK_TO_VSC_EX
            dik = (vsc & 0x7F) | (0x80 if vsc >> 8 in (0xE0, 0xE1) else 0)
            self.capture = False
            if dik == F10_DIK:
                self.say("F10 IS TAKEN", "F10 opens these settings while you play. Choose another key."); return
            if dik:
                self.pending["g_keys"] = game_cfg.bind(self.pending["g_keys"], dik, self.keys_row)
            self.draw(); return
        n = len(game_cfg.ACTIONS)
        if k == "Escape": self.page = "settings"; self.draw(); return
        if k == "Up": self.keys_row = (self.keys_row - 1) % n
        elif k == "Down": self.keys_row = (self.keys_row + 1) % n
        elif k == "Return": self.capture = True
        elif k == "Delete": self.pending["g_keys"] = game_cfg.unbind(self.pending["g_keys"], self.keys_row)
        self.draw()

    def on_any_key(self, e):
        if self.page == "keys" and self.capture and e.keysym not in ("Up", "Down", "Left", "Right", "Return", "Escape", "q", "e", "p", "Delete", "r", "a", "d"):
            self.keys_input(e.keysym, e)

    # -- actions
    def goto(self, page):
        self.page, self.sel, self.row = page, 0, 0
        if page == "setup": self.state, self.state_msg = check_folder(self.game)
        self.draw()

    def say(self, title, text):
        self.msg = (title, text); self.draw()

    def browse(self):
        d = filedialog.askdirectory(title="Choose the Requiem: Avenging Angel folder", initialdir=self.game or "C:\\")
        if d:
            self.game = os.path.normpath(d); self.state, self.state_msg = check_folder(self.game); self.sel = 0; self.draw()

    def use_folder(self):
        old = os.path.join(self.game, "Requiem Launcher.json")   # choices from the earlier .pyw launcher
        if "game" not in self.conf and os.path.exists(old):
            try:
                o = json.load(open(old, encoding="utf-8"))
                for k in ("res", "fps", "aa", "tex", "menu"):
                    if k in o: self.conf["settings"][k] = str(o[k])
                if "hud" in o: self.conf["settings"]["hud"] = str(o["hud"])
                if "nomovies" in o: self.conf["settings"]["nomovies"] = "1" if o["nomovies"] else "0"
            except (OSError, ValueError):
                pass
        self.conf["game"] = self.game; save_conf(self.conf)
        self.read_game_options()
        self.pending = dict(self.conf["settings"])
        self.head_font = self.load_game_font(); self.images.clear()
        self.goto("main")
        if self.state == "ready":
            self.do_install()

    def do_install(self):
        if self.state not in ("ready", "installed"):
            self.goto("setup"); return
        if game_running():
            self.say("GAME IS RUNNING", "Close Requiem first, then try again."); return
        try:
            install(self.game, self.conf["settings"])
        except (Exception, SystemExit) as ex:
            self.say("INSTALL FAILED", str(ex)); return
        self.state, self.state_msg = check_folder(self.game)
        self.say("INSTALLED", "The modern setup is installed. Choose PLAY to start, or SETTINGS to adjust it first.")

    def do_restore(self):
        if self.state != "installed":
            self.say("NOTHING TO RESTORE", "The modern setup is not installed in this folder."); return
        if game_running():
            self.say("GAME IS RUNNING", "Close Requiem first, then try again."); return
        try:
            restore(self.game)
        except (Exception, SystemExit) as ex:
            self.say("RESTORE FAILED", str(ex)); return
        self.state, self.state_msg = check_folder(self.game)
        self.say("ORIGINAL GAME RESTORED", "Every file the modern setup replaced has been put back.")

    def play(self):
        if self.state != "installed":
            self.do_install()
            if self.state != "installed": return
        if game_running():
            self.say("GAME IS RUNNING", "Requiem is already running."); return
        if self.dirty():
            self.say("CHANGES NOT APPLIED", "You changed settings without applying them. Open Settings and choose "
                                            "Apply (A) to use them, or Discard (D) to keep what is installed."); return
        s = self.conf["settings"]
        if tex_update_needed(self.game, s):
            self.say("UPDATING TEXTURES", "Writing the texture archive. This takes about half a minute."); self.root.update()
        elif not menu_current(self.game, s):
            self.say("UPDATING MENUS", "Drawing the menu art for " + s["res"].replace("x", " x ")
                     + ". This takes a few seconds."); self.root.update()
        try:
            mode_ok = apply_settings(self.game, s)
        except (Exception, SystemExit) as ex:
            self.say("COULD NOT APPLY SETTINGS", str(ex)); return
        free_f10(self.game)
        self.root.withdraw(); self.root.update()   # out of the way first: the game must own the foreground for its input
        self.game_proc = subprocess.Popen([os.path.join(self.game, "D3D.exe")] + (["nomovies"] if s["nomovies"] == "1" else []), cwd=self.game)
        if not mode_ok:
            self.root.deiconify()
            self.say("ONE MORE STEP", "No saved game settings yet: pick the resolution once in the game's Options. "
                                      "This launcher sets it from then on.")
        self.root.after(500, self.watch_game)   # stays in the background: F10 in game opens these settings

    # -- in game: F10
    def watch_game(self):
        if self.game_proc.poll() is not None:   # the game has closed: so does the launcher
            self.root.destroy(); return
        k = ctypes.windll.kernel32
        if not self.f10_event:
            k.OpenEventW.restype = ctypes.c_void_p
            self.f10_event = k.OpenEventW(0x00100002, False, "Local\\RequiemModernF10")   # SYNCHRONIZE | EVENT_MODIFY_STATE
        if self.f10_event and k.WaitForSingleObject(ctypes.c_void_p(self.f10_event), 0) == 0 and not self.ingame:
            self.show_ingame()
        self.root.after(150, self.watch_game)

    def game_window(self):
        u = ctypes.windll.user32; found = []
        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def cb(h, _):
            p = ctypes.c_ulong(); u.GetWindowThreadProcessId(ctypes.c_void_p(h), ctypes.byref(p))
            b = ctypes.create_unicode_buffer(64); u.GetClassNameW(ctypes.c_void_p(h), b, 64)
            if p.value == self.game_proc.pid and b.value == "Requiem" and u.IsWindowVisible(ctypes.c_void_p(h)): found.append(h)
            return True
        u.EnumWindows(cb, None)
        return found[0] if found else None

    def show_ingame(self):
        self.ingame, self.page, self.msg = True, "settings", None
        self.pending = dict(self.conf["settings"]); self.read_game_options(); self.pending.update(game_cfg.read(self.game))
        self.root.deiconify(); self.root.attributes("-topmost", True); self.root.lift(); self.root.focus_force()
        self.draw()

    def back_to_game(self):
        if self.dirty():
            self.say("CHANGES NOT APPLIED", "Apply (A) or discard (D) your changes first, then Escape to return to the game."); return
        self.ingame = False; self.msg = None
        self.root.attributes("-topmost", False); self.root.withdraw(); self.root.update()
        h = self.game_window()
        if h: ctypes.windll.user32.SetForegroundWindow(ctypes.c_void_p(h))


if __name__ == "__main__":
    App().root.mainloop()
