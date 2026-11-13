r"""The game's own options (Gamers\latest.cfg, written by its Options screens) as launcher settings.
Layout (reverse-engineered, see MODLOG "Game options file"): u32 n, n bytes profile name; u32 flags; f32 mouse
sensitivity; u32 resolution index; u8 H/W device; f32 brightness; u8 3D audio provider; f32 sound, dialog, music
volume; 256-byte key table (DIK scancode -> action, 0x44 none, 0x46 reserved; 0xfc-0xfe mouse buttons, 0xff wheel)."""
import os, struct

FLAGS = {"g_run": 0x1, "g_freelook": 0x2, "g_invert": 0x4, "g_analog": 0x20, "g_trackball": 0x40,
         "g_crosshair": 0x10000, "g_dialogue": 0x40000, "g_shadows": 0x80000, "g_hideweapon": 0x100000,
         "g_fx": 0x200000, "g_footsteps": 0x1000000}
DEFAULT_FLAGS = 0x01290003
FLOATS = ("g_sens", "g_bright", "g_sound", "g_dialog", "g_music")   # 0..1, shown in steps of 10%
DEFAULT_FLOATS = {"g_sens": 5, "g_bright": 5, "g_sound": 10, "g_dialog": 10, "g_music": 10}
WHEEL = [("44", "Unused"), ("00", "Forward / back"), ("12", "Weapon up / down"), ("14", "Offensive power up / down"),
         ("16", "Defensive power up / down"), ("18", "Maneuver power up / down"), ("1a", "Interactive power up / down"),
         ("1c", "Inventory up / down")]
NONE, RESERVED = 0x44, 0x46

# action number -> name (the game numbers the non-empty names of its string table 0x640..)
ACTIONS = ["Forward", "Backward", "Move Left", "Move Right", "Jump/Up", "Crouch/Down", "Rotate Left", "Rotate Right",
           "Look Up", "Look Down", "Look Center", "Run", "Strafe", "Free Look", "Fire", "Use Defensive", "Use Maneuver",
           "Use Interactive", "Cycle Weapons", "Cycle Wpns Down", "Cycle Powers", "Cycle Off Down", "Cycle Defnsv Up",
           "Cycle Def Down", "Cycle Mnvr Up", "Cycle Mnvr Down", "Cycle Intrct Up", "Cycle Int Down", "Cycle Invtry Up",
           "Cycle Inv Down", "Talk/Activate", "Powers Menu", "Console Mode", "Handgun", "Assault Rifle", "Combat Shotgun",
           "GrenadeLauncher", "Rocket Launcher", "Sniper Rifle", "Railgun", "Hand", "Exorcist", "Pentecost", "Brimstone",
           "Bloodboil", "Lightning", "Locusts", "To Salt", "Apocalypse", "Heal", "Deflect", "Holy Light", "Banish",
           "Shockwave", "Haste", "Flight", "Warp Time", "Healer", "Insist", "Resurrect", "Possession", "Increase Screen",
           "Decrease Screen", "Quick Save", "Quick Load", "Take Screenshot", "Use Bound Power", "Journal/Info"]

_DIK = {0x01: "ESC", 0x0E: "BACKSPACE", 0x0F: "TAB", 0x1C: "ENTER", 0x1D: "LCTRL", 0x2A: "LSHIFT", 0x36: "RSHIFT",
        0x37: "NUM*", 0x38: "LALT", 0x39: "SPACE", 0x3A: "CAPS", 0x45: "NUMLOCK", 0x46: "SCROLL", 0x47: "NUM7",
        0x48: "NUM8", 0x49: "NUM9", 0x4A: "NUM-", 0x4B: "NUM4", 0x4C: "NUM5", 0x4D: "NUM6", 0x4E: "NUM+", 0x4F: "NUM1",
        0x50: "NUM2", 0x51: "NUM3", 0x52: "NUM0", 0x53: "NUM.", 0x9C: "NUMENTER", 0x9D: "RCTRL", 0xB5: "NUM/",
        0xB7: "PRTSC", 0xB8: "RALT", 0xC5: "PAUSE", 0xC7: "HOME", 0xC8: "UP", 0xC9: "PGUP", 0xCB: "LEFT", 0xCD: "RIGHT",
        0xCF: "END", 0xD0: "DOWN", 0xD1: "PGDN", 0xD2: "INSERT", 0xD3: "DELETE", 0xFC: "MOUSE1", 0xFD: "MOUSE2",
        0xFE: "MOUSE3", 0x0C: "-", 0x0D: "=", 0x1A: "[", 0x1B: "]", 0x27: ";", 0x28: "'", 0x29: "`", 0x2B: "\\",
        0x33: ",", 0x34: ".", 0x35: "/"}
for i, c in enumerate("1234567890"): _DIK[0x02 + i] = c
for row, start in (("QWERTYUIOP", 0x10), ("ASDFGHJKL", 0x1E), ("ZXCVBNM", 0x2C)):
    for i, c in enumerate(row): _DIK[start + i] = c
for i in range(10): _DIK[0x3B + i] = f"F{i + 1}"
_DIK[0x57], _DIK[0x58] = "F11", "F12"


def key_name(dik):
    return _DIK.get(dik, f"KEY {dik:02X}")


def path(folder):
    p = os.path.join(folder, "Gamers", "latest.cfg")
    return p if os.path.exists(p) else None


def _fields(data):
    n = struct.unpack_from("<I", data, 0)[0]; o = 4 + n
    return {"flags": o, "sens": o + 4, "res": o + 8, "hw": o + 12, "bright": o + 13, "audio": o + 17,
            "sound": o + 18, "dialog": o + 22, "music": o + 26, "keys": o + 30}


def read(folder):
    """Launcher settings from the game's options file, or {} if the game has not written one yet."""
    p = path(folder)
    if not p:
        return {}
    data = open(p, "rb").read(); f = _fields(data)
    if len(data) < f["keys"] + 256:
        return {}
    flags = struct.unpack_from("<I", data, f["flags"])[0]
    s = {k: "1" if flags & bit else "0" for k, bit in FLAGS.items()}
    for k, off in (("g_sens", "sens"), ("g_bright", "bright"), ("g_sound", "sound"), ("g_dialog", "dialog"), ("g_music", "music")):
        s[k] = str(max(0, min(10, round(struct.unpack_from("<f", data, f[off])[0] * 10))))
    keys = data[f["keys"]:f["keys"] + 256]
    s["g_wheel"] = f"{keys[0xFF]:02x}" if f"{keys[0xFF]:02x}" in dict(WHEEL) else "44"
    s["g_keys"] = keys.hex()
    return s


def write(folder, s):
    """Write the game options in s into the game's options file (other fields untouched). Floats keep their exact
    value unless their 10% step changed."""
    p = path(folder)
    if not p or "g_keys" not in s:
        return False
    data = bytearray(open(p, "rb").read()); f = _fields(data)
    flags = struct.unpack_from("<I", data, f["flags"])[0]
    for k, bit in FLAGS.items():
        flags = flags | bit if s.get(k) == "1" else flags & ~bit
    struct.pack_into("<I", data, f["flags"], flags)
    for k, off in (("g_sens", "sens"), ("g_bright", "bright"), ("g_sound", "sound"), ("g_dialog", "dialog"), ("g_music", "music")):
        cur = struct.unpack_from("<f", data, f[off])[0]
        if round(cur * 10) != int(s[k]):
            struct.pack_into("<f", data, f[off], int(s[k]) / 10)
    keys = bytearray.fromhex(s["g_keys"]); keys[0xFF] = int(s["g_wheel"], 16)
    data[f["keys"]:f["keys"] + 256] = keys
    open(p, "wb").write(data)
    return True


def bindings(keys_hex):
    """{action: [dik, ...]} for the key table."""
    out = {}
    for dik, a in enumerate(bytes.fromhex(keys_hex)):
        if dik < 0xFF and a < len(ACTIONS):
            out.setdefault(a, []).append(dik)
    return out


def bind(keys_hex, dik, action):
    """Key table with dik bound to action (a key does one thing: it leaves its old action). Reserved keys stay."""
    t = bytearray.fromhex(keys_hex)
    if t[dik] != RESERVED:
        t[dik] = action
    return t.hex()


def unbind(keys_hex, action):
    t = bytearray.fromhex(keys_hex)
    for i in range(0xFF):
        if t[i] == action: t[i] = NONE
    return t.hex()


if __name__ == "__main__":   # self-check against a copy of a real options file
    import shutil, sys, tempfile
    if len(sys.argv) < 2: sys.exit("usage: py game_cfg.py <game folder>  (a copy: the self-check writes a temp copy only)")
    src = sys.argv[1]
    d = tempfile.mkdtemp(); os.makedirs(os.path.join(d, "Gamers"))
    shutil.copy(os.path.join(src, "Gamers", "latest.cfg"), os.path.join(d, "Gamers"))
    orig = open(path(d), "rb").read()
    s = read(d)
    assert s and write(d, s) and open(path(d), "rb").read() == orig, "round trip changed the file"
    t = dict(s); t["g_invert"] = "1"; t["g_music"] = "3"; t["g_keys"] = bind(t["g_keys"], 0x58, ACTIONS.index("Take Screenshot"))
    write(d, t); u = read(d)
    assert u["g_invert"] == "1" and u["g_music"] == "3" and 0x58 in bindings(u["g_keys"])[ACTIONS.index("Take Screenshot")]
    print("ok:", {k: s[k] for k in s if k != "g_keys"}, "|", {ACTIONS[a]: [key_name(k) for k in v] for a, v in list(bindings(s["g_keys"]).items())[:6]})
    shutil.rmtree(d)
