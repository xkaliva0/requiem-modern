"""Patch Requiem: Avenging Angel D3D.exe (GOG v1.2, built 2001-02-22) for modern Windows.

Usage: py patch_d3d.py "E:\\Requiem - Avenging Angel\\D3D.exe" [--aspect 16:9]
Saves D3D.exe.orig next to it on first run and always rebuilds from that, so re-running
(with the same or a different --aspect) is safe. Default aspect 4:3 = the game's own view.
"""
import argparse
import os
import shutil
import struct
import sys

import pefile

# (VA, original bytes, patched bytes, why)
PATCHES = [
    # DirectX version check opens HKLM\Software\Microsoft\DirectX with KEY_ALL_ACCESS,
    # which fails without admin rights -> "Sorry, DirectX 6 or later is required."
    (0x465950, (0xF003F).to_bytes(4, "little"), (0x20019).to_bytes(4, "little"), "RegOpenKeyEx KEY_ALL_ACCESS -> KEY_READ"),
    # D3D device enumeration does LoadLibrary("ddraw.dll"), which Win8+ resolves to System32 even when a
    # wrapper ddraw.dll sits in the game folder -> "Could not initialize 3-D graphics". Path-qualify it
    # (string has 6 bytes of zero padding, nothing points inside it).
    (0x52BE58, b"ddraw.dll\0\0\0", b".\\ddraw.dll\0", 'LoadLibrary("ddraw.dll") -> ".\\ddraw.dll"'),
    # DX manager calls IDirectDraw4::Initialize on an object DirectDrawCreate already initialized; it returns
    # DDERR_ALREADYINITIALIZED (0x88760005) and init aborts. Treat any result as success: jge -> jmp.
    (0x50BE07, b"\x7d\x12", b"\xeb\x12", "IDirectDraw4::Initialize result ignored"),
    # XLR8_DrawLine shows a leftover debug MessageBox(NULL, "DrawPrim failed!") when DrawPrimitive fails, which
    # it does for a moment after alt-tab (surfaces lost). The ownerless box steals focus and blocks mid-frame;
    # quitting the game while it's up tears 3D down, then the frame resumes and EndScene/DrawPrim hit a NULL
    # device (crashes at +0x107306 and +0x108453). Drop the box: call [MessageBoxA] -> add esp,16 (its 4 args).
    (0x50860F, b"\xff\x15\xe4\xf2\x51\x00", b"\x83\xc4\x10\x90\x90\x90", 'XLR8_DrawLine "DrawPrim failed!" box removed'),
]

# Renderer visibility pass 0x4bac80: its second loop unlinks each entry from the singly linked list [edi+4] by
# searching for the predecessor (0x4bae94), but the recursive check it then calls (0x4baef0) can move the saved
# next entry to another list. The search then runs off the end and reads [NULL+4] (crash +0xBAE9D, seen with
# dgVoodoo at 1080p and with DDrawCompat at 180 fps; dump 2026-11-06: entry 0x648a18 not in [edi+4]).
# Rewrite the search in place with an end-of-list check that skips the entry (0x4baed2 = next entry).
PATCHES.append((
    0x4BAE94,
    bytes.fromhex("8b41043bc674098bc88b41043bc675f7"),
    bytes.fromhex("85c9743a8b410439f0740589c1ebf190"),
    "renderer: no NULL walk when a visibility entry was already moved (crash +0xBAE9D)"))

# Menus (front end) only redraw dirty widgets, so with nothing changing nothing is presented. dgVoodoo draws its
# emulated cursor (needed whenever the 640x480 menu is scaled to 1080p) only on a present, so the cursor stuttered.
# 0x4d0a37 `jne full_redraw` (taken when [0x658d68] is set, e.g. after surface loss) -> always full redraw.
PATCHES.append((0x4D0A37, bytes.fromhex("0f8538010000"), bytes.fromhex("e93901000090"),
                "menu: full redraw every loop pass (smooth dgVoodoo cursor on the scaled menu)"))

# Code caves live in the .text slack after the --trace cave (which ends at 0x51e826).
# Entering 3D (0x4590d0) built the device at the current mode index [0x6b9dec] (the menu's 640x480), then 0x458dd0 ->
# 0x505550 saw the game's mode [0x65923c] differ and tore it down and rebuilt it: two device + texture builds in the
# black gap before gameplay. Set [0x6b9dec] = [0x65923c] first, so the first build is at the game mode and the
# second is skipped (0x505550 returns early when the index is unchanged). Same index space: 0x505500 copies it.
# (dgVoodoo AppControlledScreenMode=false would cut the remaining 1.6 s gap to ~0.1 s, but it breaks the mouse:
# dgVoodoo draws the cursor where you point while the game reads the unmapped position. Keep it true.)
_ENTER3D = 0x51EF00
_enter3d_code = (b"\xa1\x3c\x92\x65\x00" b"\xa3\xec\x9d\x6b\x00"       # mov eax,[0x65923c]; mov [0x6b9dec],eax
                 b"\x51" b"\xb9\x01\x00\x00\x00")                       # displaced: push ecx; mov ecx,1
_enter3d_code += b"\xe9" + struct.pack("<i", 0x4590D6 - (_ENTER3D + len(_enter3d_code) + 5))

# Busy-ring cursor on the first menu was dgVoodoo's cursor hook (its drawn copy); no exe patch fixed it. With
# DDrawCompat as the wrapper the cursor is a normal arrow from the first menu (2026-11-05).
PATCHES += [
    (_ENTER3D, bytes(len(_enter3d_code)), _enter3d_code, "enter 3D: build the device at the game mode code"),
    (0x4590D0, bytes.fromhex("51b901000000"), b"\xe9" + struct.pack("<i", _ENTER3D - 0x4590D5) + b"\x90",
     "enter 3D: build once at the game mode (no second device build)"),
]

HUD_RECT = 0x6BF3C0   # .data slack: scaled dst rect (int l, t, r, b)
HUD_CAVE = 0x51EA00   # between the --trace cave (ends 0x51e826) and the enter-3D cave (0x51ef00)


def hud_patches(design_h):
    """HUD scale. Every 2D widget drawn over the 3D view (HUD panels, digits, icons) goes through the quad function
    0x508aa0 (ecx = src rect, edx = dst rect, ints l,t,r,b; only caller is the widget draw 0x4ca901). Replace the dst
    rect with a scaled copy: S = screen height [0x6b9e00] / design_h (never below 1), per axis: elements in the first
    third grow from that edge, in the last third from the far edge, in the middle around the screen centre; elements
    bigger than half the screen are left alone. Returns (patches, asm) where asm is the cave as (label|bytes) items."""
    rel8 = {}
    asm = [
        "main",
        b"\x60",                                        # pushad
        b"\xa1" + struct.pack("<I", 0x6B9E00),          # mov eax, [screen h]
        b"\xc1\xe0\x08", b"\x31\xd2",                   # shl eax, 8 ; xor edx, edx
        b"\xb9" + struct.pack("<I", design_h),          # mov ecx, design_h
        b"\xf7\xf1",                                    # div ecx -> eax = S * 256
        b"\x3d\x00\x01\x00\x00", b"\x7d\x05",           # cmp eax, 256 ; jge +5
        b"\xb8\x00\x01\x00\x00",                        # mov eax, 256
        b"\x89\xc5",                                    # mov ebp, eax          ; ebp = S256
        b"\x8b\x74\x24\x14",                            # mov esi, [esp+20]     ; original edx (dst rect)
        b"\x8b\x06", b"\x8b\x4e\x08",                   # mov eax, [esi] ; mov ecx, [esi+8]
        b"\x8b\x1d" + struct.pack("<I", 0x6B9DFC),      # mov ebx, [screen w]
        ("call", "axis"),
        b"\xa3" + struct.pack("<I", HUD_RECT), b"\x89\x0d" + struct.pack("<I", HUD_RECT + 8),
        b"\x8b\x74\x24\x14",                            # mov esi, [esp+20]
        b"\x8b\x46\x04", b"\x8b\x4e\x0c",               # mov eax, [esi+4] ; mov ecx, [esi+12]
        b"\x8b\x1d" + struct.pack("<I", 0x6B9E00),      # mov ebx, [screen h]
        ("call", "axis"),
        b"\xa3" + struct.pack("<I", HUD_RECT + 4), b"\x89\x0d" + struct.pack("<I", HUD_RECT + 12),
        b"\x61",                                        # popad
        b"\xba" + struct.pack("<I", HUD_RECT),          # mov edx, HUD_RECT
        b"\x8b\x41\x08", b"\x81\xec\xa4\x00\x00\x00",   # displaced: mov eax,[ecx+8] ; sub esp,0xa4
        ("jmp", 0x508AA9),
        # axis(eax = lo, ecx = hi, ebx = D, ebp = S256) -> eax = lo', ecx = hi'; uses edx, esi, edi
        "axis",
        b"\x89\xcf", b"\x29\xc7",                       # mov edi, ecx ; sub edi, eax      ; w
        b"\x8d\x34\x3f", b"\x39\xde", ("jg8", "done"),  # lea esi,[edi+edi] ; cmp esi, ebx ; 2w > D -> leave
        b"\x0f\xaf\xfd", b"\xc1\xff\x08",               # imul edi, ebp ; sar edi, 8        ; w' = w*S
        b"\x8d\x34\x08",                                # lea esi, [eax+ecx]                ; c2 = lo+hi
        b"\x8d\x14\x76", b"\x29\xda", b"\x29\xda",      # lea edx,[esi+esi*2] ; sub edx,ebx x2 ; 3c2 - 2D
        ("jl8", "left"),
        b"\x29\xda", b"\x29\xda", ("jg8", "right"),     # 3c2 - 4D > 0 -> right third
        b"\x29\xde", b"\x0f\xaf\xf5", b"\xc1\xfe\x08",  # sub esi,ebx ; imul esi,ebp ; sar esi,8
        b"\x01\xde", b"\x29\xfe", b"\xd1\xfe",          # add esi,ebx ; sub esi,edi ; sar esi,1   ; lo'
        b"\x89\xf0", b"\x8d\x0c\x3e", b"\xc3",          # mov eax,esi ; lea ecx,[esi+edi] ; ret
        "left",
        b"\x0f\xaf\xc5", b"\xc1\xf8\x08",               # imul eax,ebp ; sar eax,8          ; lo' = lo*S
        b"\x8d\x0c\x38", b"\xc3",                       # lea ecx,[eax+edi] ; ret
        "right",
        b"\x89\xda", b"\x29\xca",                       # mov edx,ebx ; sub edx,ecx         ; D - hi
        b"\x0f\xaf\xd5", b"\xc1\xfa\x08",               # imul edx,ebp ; sar edx,8
        b"\x89\xd9", b"\x29\xd1",                       # mov ecx,ebx ; sub ecx,edx         ; hi'
        b"\x89\xc8", b"\x29\xf8", b"\xc3",              # mov eax,ecx ; sub eax,edi ; ret   ; lo' = hi' - w'
        "done",
        b"\xc3",
        # red slot highlight: 0x45d0f0 draws the HUD's three icon slots (scaled through the quad above), then a red
        # outline round the active one with 0x434fd0(ecx = l, edx = t, [esp+4] = r-1, [esp+8] = b-1) from the slot's
        # unscaled rect. Scale that rect the same way so the outline sits round the scaled icon.
        "redbox",
        b"\x60",                                        # pushad: [esp+20] = t, [esp+24] = l, [esp+36] = r-1, [esp+40] = b-1
        b"\xa1" + struct.pack("<I", 0x6B9E00), b"\xc1\xe0\x08", b"\x31\xd2",
        b"\xb9" + struct.pack("<I", design_h), b"\xf7\xf1",
        b"\x3d\x00\x01\x00\x00", b"\x7d\x05", b"\xb8\x00\x01\x00\x00",
        b"\x89\xc5",                                    # ebp = S256 (as in main)
        b"\x8b\x44\x24\x18", b"\x8b\x4c\x24\x24", b"\x41",                  # eax = l ; ecx = r
        b"\x8b\x1d" + struct.pack("<I", 0x6B9DFC), ("call", "axis"),
        b"\x89\x44\x24\x18", b"\x49", b"\x89\x4c\x24\x24",                  # l' ; r'-1
        b"\x8b\x44\x24\x14", b"\x8b\x4c\x24\x28", b"\x41",                  # eax = t ; ecx = b
        b"\x8b\x1d" + struct.pack("<I", 0x6B9E00), ("call", "axis"),
        b"\x89\x44\x24\x14", b"\x49", b"\x89\x4c\x24\x28",                  # t' ; b'-1
        b"\x61",                                        # popad
        b"\x53\x8b\x5c\x24\x08\x55",                    # displaced: push ebx; mov ebx,[esp+8]; push ebp
        ("jmp", 0x434FD6),
    ]
    # two-pass assemble
    def build(labels):
        out, pc = bytearray(), HUD_CAVE
        for it in asm:
            if isinstance(it, str):
                labels[it] = pc; continue
            if isinstance(it, tuple):
                op, tgt = it
                t = labels.get(tgt, tgt) if isinstance(tgt, str) else tgt
                t = t if isinstance(t, int) else pc
                if op == "call": enc = b"\xe8" + struct.pack("<i", t - (pc + 5))
                elif op == "jmp": enc = b"\xe9" + struct.pack("<i", t - (pc + 5))
                else: enc = bytes([{"jg8": 0x7F, "jl8": 0x7C}[op], (t - (pc + 2)) & 0xFF])
                out += enc; pc += len(enc); continue
            out += it; pc += len(it)
        return bytes(out)
    labels = {}
    build(labels); code = build(labels)
    assert HUD_CAVE + len(code) <= 0x51EC00   # the HD re-upload cave starts there
    return [
        (HUD_CAVE, bytes(len(code)), code, f"HUD scale code (screen height / {design_h})"),
        (0x508AA0, bytes.fromhex("8b410881eca4000000"), b"\xe9" + struct.pack("<i", HUD_CAVE - 0x508AA5) + b"\x90" * 4,
         "HUD scale: widget quads go through the scaled rect"),
        (0x434FD0, bytes.fromhex("538b5c240855"), b"\xe9" + struct.pack("<i", labels["redbox"] - 0x434FD5) + b"\x90",
         "HUD scale: red highlight round the active icon slot scaled too"),
    ], code


# Input poll 0x45dd50: if the mouse/keyboard can't be (re)acquired, e.g. focus lost at the wrong moment, it shows
# "DirectInput could not acquire/communicate with mouse/keyboard" and exits. Its joystick branch already handles
# the same failure by returning 0 (no input this frame) at 0x45dd61; send the four fatal blocks there instead.
# Sound: the game starts Miles with AIL_quick_startup(digital 1, MIDI 0, rate 0, bits 0, channels 2) (0x4eaf05),
# i.e. Miles' low default output (22 kHz). Ask for 44.1 kHz / 16-bit. The pushes move to a cave (44100 needs push imm32).
_MILES = 0x51EF40
_miles_code = b"\x6a\x02" b"\x6a\x10" b"\x68" + struct.pack("<I", 44100) + b"\x6a\x00" b"\x6a\x01"
_miles_code += b"\xe9" + struct.pack("<i", 0x4EAF0F - (_MILES + len(_miles_code) + 5))
PATCHES += [
    (_MILES, bytes(len(_miles_code)), _miles_code, "sound: Miles output 44.1 kHz / 16-bit code"),
    (0x4EAF05, bytes.fromhex("6a026a006a006a006a01"), b"\xe9" + struct.pack("<i", _MILES - 0x4EAF0A) + b"\x90" * 5,
     "sound: Miles mixes at 44.1 kHz / 16-bit instead of its low default"),
]

# Input setup (0x45d859 keyboard, 0x45d908 mouse) sets FOREGROUND cooperation and acquires at once; if the game window
# is not in front at that moment (e.g. a launcher window still has focus) it shows "DirectInput could not acquire
# keyboard/mouse" and exits. Make that acquire failure non-fatal, and let the per-frame poll re-acquire after ANY
# GetDeviceState failure (it only did so for DIERR_INPUTLOST, so a never-acquired device stayed dead).
PATCHES += [
    (0x45D88F, b"\x74\x17", b"\xeb\x17", "DirectInput setup: keyboard acquire failure not fatal"),
    (0x45D93E, b"\x74\x17", b"\xeb\x17", "DirectInput setup: mouse acquire failure not fatal"),
    (0x45DD82, bytes.fromhex("0f8589000000"), b"\x90" * 6, "DirectInput poll: mouse re-acquires after any failure"),
    (0x45DDD0, b"\x75\x6d", b"\x90\x90", "DirectInput poll: keyboard re-acquires after any failure"),
]
for va, msg in ((0x45DDFA, 0x533204), (0x45DE11, 0x5332B8), (0x45DE28, 0x533114), (0x45DE3F, 0x533284)):
    PATCHES.append((va, b"\x68" + struct.pack("<I", msg), b"\xE9" + struct.pack("<i", 0x45DD61 - (va + 5)),
                    f"DirectInput failure at {va:#x}: skip input this frame instead of quitting"))

# Frame time: the tick (0x448450) gives every system dt = whole ms since the last frame ([0x5404e8]). Four places
# divide it with a shift, dropping the remainder each frame: dt/2 for two character animation timers (0x472735,
# 0x49efa3), dt/4 for an area-damage effect (0x473b25) and dt/4 for the game-wide slow-motion flag (0x4c6be1).
# At 60 and 120 fps the loss is the same 4%, at 180 fps 10-28%, at ~1000 fps (dt 1) they stop. Carry the remainder:
# the tick works out dt/2 and dt/4 once per frame with carry, the three sites read those; slow motion keeps its own.
T_HALF, T_QUARTER, T_REMH, T_REMQ, T_REMS = 0x6BF3A0, 0x6BF3A4, 0x6BF3A8, 0x6BF3AC, 0x6BF3B0   # .data slack, zero
_TICK = 0x51EF60
_a = lambda v: struct.pack("<I", v)
_tick = (b"\xa3" + _a(0x5404E8) + b"\x89\x35" + _a(0x5404F4)            # the two stores the hook replaces
         + b"\x52"                                                       # push edx
         + b"\x8b\xd0\x03\x15" + _a(T_REMH) + b"\x89\x15" + _a(T_REMH)   # edx = dt + remH; remH = edx
         + b"\xd1\xea\x89\x15" + _a(T_HALF)                              # half = edx >> 1
         + b"\x83\x25" + _a(T_REMH) + b"\x01"                            # remH &= 1
         + b"\x8b\xd0\x03\x15" + _a(T_REMQ) + b"\x89\x15" + _a(T_REMQ)   # edx = dt + remQ; remQ = edx
         + b"\xc1\xea\x02\x89\x15" + _a(T_QUARTER)                       # quarter = edx >> 2
         + b"\x83\x25" + _a(T_REMQ) + b"\x03"                            # remQ &= 3
         + b"\x5a")                                                      # pop edx
_DECAY = 0x51E840   # free .text between the --trace cave (ends 0x51e826) and the HUD cave (0x51ea00)
_tick += b"\xe9" + struct.pack("<i", _DECAY - (_TICK + len(_tick) + 5))   # on to the decay factors, then back
_SLOW = _TICK + len(_tick)
_slow_body = (b"\x03\x05" + _a(T_REMS) + b"\xa3" + _a(T_REMS)          # eax += remS; remS = eax
              + b"\x83\x25" + _a(T_REMS) + b"\x03" + b"\xc1\xe8\x02")    # remS &= 3; eax >>= 2
_slow = b"\x8b\x44\x24\x0c" + b"\x74" + bytes([len(_slow_body)]) + _slow_body   # mov eax, [esp+0xc]; je (flag clear) out
_slow +=b"\xe9" + struct.pack("<i", 0x4C6BE4 - (_SLOW + len(_slow) + 5))
assert _SLOW + len(_slow) <= 0x51F000
PATCHES += [
    (_TICK, bytes(len(_tick)), _tick, "frame time: dt/2 and dt/4 with carried remainder, once per tick (code)"),
    (0x4484B3, bytes.fromhex("a3e80454008935f4045400"), b"\xe9" + struct.pack("<i", _TICK - 0x4484B8) + b"\x90" * 6,
     "frame time: tick hook"),
    (0x472735, bytes.fromhex("a1e8045400"), b"\xa1" + _a(T_HALF), "frame time: animation timer 0x472735 reads dt/2"),
    (0x47273D, b"\xd1\xe8", b"\x90\x90", "frame time: animation timer 0x472735 no own shift"),
    (0x49EFA3, bytes.fromhex("66a1e804540066d1f8"), b"\x66\xa1" + _a(T_HALF) + b"\x90" * 3,
     "frame time: character animation 0x49efa3 reads dt/2"),
    (0x473B25, bytes.fromhex("a1e8045400c1e802"), b"\xa1" + _a(T_QUARTER) + b"\x90" * 3,
     "frame time: area damage 0x473b25 reads dt/4"),
    (_SLOW, bytes(len(_slow)), _slow, "frame time: slow motion dt/4 with carried remainder (code)"),
    (0x4C6BDB, bytes.fromhex("8b44240c7403c1e802"), b"\xe9" + struct.pack("<i", _SLOW - 0x4C6BE0) + b"\x90" * 4,
     "frame time: slow motion hook"),
]

# Per-frame drag: velocities are moved by dt but then multiplied by a fixed factor EVERY FRAME (v *= 0.95), so at
# 120 fps they lose speed twice as fast and a leap covers about half the distance (user: the first enemy lunges much
# more at 60 than at 120). Each tick now works out C^(dt / 16.667 ms) for every such constant - exactly C at 60 fps -
# and those multiplies read it instead. Factor = r^dt with r = C^(1/16.667) as a double, by repeated multiply.
_DECAY_F = 0x6BF3D0    # .data slack, one float per constant
_DRAG = {   # constant address: (value, the fmul sites using it in per-frame updates)
    0x527188: (0.95, (0x47F85B, 0x47F86D, 0x468B50, 0x468B62, 0x468B74)),   # actor leap (+0x88/+0x90), actor +0xf0..
    0x51F67C: (0.90, (0x482DE4, 0x482DF6, 0x482E08, 0x46A00F, 0x46A021, 0x46A033)),   # actor velocity, actor +0x208..
    0x520A7C: (0.97, (0x45EEB2, 0x45EEBE, 0x45EEE6)),                        # debris
    0x51F43C: (0.65, (0x43FFD8, 0x43FFE4, 0x43FFF0)),                        # particles
    0x520618: (0.972, (0x46BB7A, 0x46BD42)),
    0x5290BC: (0.98, (0x4C29F9, 0x4C2A05, 0x4C2A11)),
    0x5283DC: (0.74, (0x4B771E, 0x4B7730)),                                  # player physics
}
_decay, _rs = b"\x52", b""                                                  # push edx
_R = _DECAY + 0x100                                                         # the r doubles after the code
for k, (c, (v, _)) in enumerate(_DRAG.items()):
    _decay += (b"\xd9\xe8" b"\x8b\xd0" b"\x85\xd2" b"\x74\x09"              # fld1; mov edx, eax (dt); test; jz done
               + b"\xdc\x0d" + _a(_R + 8 * k) + b"\x4a" b"\x75\xf7"         # loop: fmul qword [r]; dec edx; jnz loop
               + b"\xd9\x1d" + _a(_DECAY_F + 4 * k))                        # done: fstp dword [F]
    _rs += struct.pack("<d", v ** (60 / 1000))
_decay += b"\x5a" + b"\xe9" + struct.pack("<i", 0x4484BE - (_DECAY + len(_decay) + 1 + 5))   # pop edx; jmp back
assert len(_decay) <= 0x100 and _R + len(_rs) <= 0x51EA00 and _DECAY_F + 4 * len(_DRAG) <= 0x6BF400
PATCHES += [(_DECAY, bytes(len(_decay)), _decay, "frame time: drag factors C^(dt/16.67) per tick (code)"),
            (_R, bytes(len(_rs)), _rs, "frame time: drag factors per-ms rates")]
for k, (c, (v, sites)) in enumerate(_DRAG.items()):
    for s in sites:
        PATCHES.append((s, b"\xd8\x0d" + _a(c), b"\xd8\x0d" + _a(_DECAY_F + 4 * k), f"frame time: drag {v} at {s:#x} per time, not per frame"))

# Ground flicker: Move (0x42ad40, actor, &target(x, centre y, z), half height, sector) clears the on-ground bit
# (+0x78 & 1) and only sets it when the move pushes into the floor, which snaps the actor 0.01 above it with vy
# (+0x70) = 0. So a resting actor is "airborne" on the next frame and lands again once gravity has pulled it 0.01
# down: on the very next frame at 60 fps (on/off/on/off), only after two frames at 120 (off/off/on). Creature AI
# (attack, contact damage, the pounce take-off check) only runs on grounded frames, so at 120 fps the first
# creature lunged and bit far less (user: "lunges much more at 60"). On entry, if the actor was airborne and has
# only just started falling from rest (0 > vy > -0.002 units/ms), probe the target 0.015 lower so it lands on that
# frame at any frame rate: the 60 fps pattern everywhere. A real fall or jump gets at most a few hundredths extra.
# Above ~1000 fps many frames have dt = 0 (nothing moves, gravity adds nothing) but Move still clears the bit, so on
# those frames Move runs through a wrapper that puts a grounded actor's bit back afterwards.
# 1.3.2: the user's own play at 60 fps showed a resting creature grounded on ~97% of frames after a grounded frame
# (one 60 fps frame of gravity reaches the floor), but only ~10% at 120 (on/off/on/off), so half the pounce take-offs
# were missed (80 vs 33 leaps a minute). So when frames are shorter than 60 fps (dt < 16 ms) the probe also applies
# to an actor that was grounded last frame; at 60 fps and slower nothing changes.
_GROUND = 0x51EE00    # free .text after the HUD cave, before the enter-3D cave
_g_body = (b"\x8b\x4c\x24\x10"                                  # mov ecx, [esp+0x10]   (&target)
           + b"\xd9\x41\x04" + b"\xd8\x25" + _a(0) + b"\xd9\x59\x04")   # fld [ecx+4]; fsub [PROBE]; fstp [ecx+4]
_g_tests = (b"\x8b\x44\x24\x0c"                                 # mov eax, [esp+0xc]    (actor)
            + b"\xf6\x40\x78\x01" + b"\x74\x09"                                      # airborne: test vy
            + b"\x83\x3d" + _a(0x5404E8) + b"\x10"                                   # grounded: dt vs 16 ms
            + b"\x73" + bytes([3 + 2 + 2 + 6 + 6 + 2 + len(_g_body)])                # 60 fps or slower: done
            + b"\x8b\x48\x70" + b"\x85\xc9" + b"\x79" + bytes([6 + 6 + 2 + len(_g_body)])    # vy >= +0: done
            + b"\x81\xe1\xff\xff\xff\x7f" + b"\x81\xf9" + _a(0x3B03126F)             # |vy| vs 0.002
            + b"\x73" + bytes([len(_g_body)]))                                       # jae done
_g_wrap = (b"\x50" b"\x8b\x44\x24\x08" b"\x8b\x40\x78" b"\x83\xe0\x01" b"\x87\x04\x24"   # [esp] = actor bit 0
           + b"\xff\x74\x24\x14" * 4                                             # copy the 4 arguments
           + b"\xe8" + _a(0)                                                     # call trampoline (fixed below)
           + b"\x5a" b"\x85\xd2" b"\x74\x08" b"\x8b\x54\x24\x04" b"\x80\x4a\x78\x01"   # pop bit; if set: actor |= 1
           + b"\xc2\x10\x00")                                                    # ret 0x10
_ground = (b"\x50\x51" + _g_tests + _g_body + b"\x59\x58"
           + b"\x83\x3d" + _a(0x5404E8) + b"\x00" + b"\x75" + bytes([len(_g_wrap)])  # dt != 0: straight on
           + _g_wrap)
_G_TRAMP = _GROUND + len(_ground)
_call_at = _GROUND + _ground.index(b"\xe8" + _a(0))
_ground = _ground.replace(b"\xe8" + _a(0), b"\xe8" + struct.pack("<i", _G_TRAMP - (_call_at + 5)))
_ground += bytes.fromhex("558bec81ec70030000") + b"\xe9" + struct.pack("<i", 0x42AD49 - (_G_TRAMP + 9 + 5))
_G_PROBE = _GROUND + len(_ground)
_ground = _ground.replace(b"\xd8\x25" + _a(0), b"\xd8\x25" + _a(_G_PROBE)) + struct.pack("<f", 0.015)
assert _GROUND + len(_ground) <= 0x51EF00, hex(_GROUND + len(_ground))
PATCHES += [(_GROUND, bytes(len(_ground)), _ground, "ground: resting actors land on the first falling frame (code)"),
            (0x42AD40, bytes.fromhex("558bec81ec70030000"), b"\xe9" + struct.pack("<i", _GROUND - 0x42AD45) + b"\x90" * 4,
             "ground: on-ground flicker independent of frame rate, resting actors stay grounded above 60 fps (enemy lunges as at 60 fps)")]

# Long-range leap chance: the first creature's decision (0x47ab70) runs on every grounded, non-busy frame. Running at
# the player from > 28 units it rolls int(rand * 30) == 5 -> leap (0xb), else keep running (0x15), and running stops
# setting the busy bit after its first stride, so it rolls every frame: twice as often per second at 120 fps.
# Now: leap if rand * 500 < dt (ms), i.e. 1/30 per 60 fps frame and the same chance per second at any frame rate.
_LEAP = _GROUND + len(_ground) + 6    # after the ground cave
_leap = (b"\xd9\x04\x85" + _a(0x56F6E8)                      # fld [eax*4 + rand table]   (eax = table index)
         + b"\xd8\x0d" + _a(0)                               # fmul [500.0]
         + b"\xda\x1d" + _a(0x5404E8)                        # ficomp dword [dt]
         + b"\xdf\xe0" + b"\xf6\xc4\x01" + b"\x74\x05"       # fnstsw ax; test ah, 1 (rand*500 < dt); jz keep running
         + b"\xe9" + _a(0) + b"\xe9" + _a(0))                # jmp leap 0x47ac82; jmp run 0x47acb9
_l1 = _LEAP + len(_leap) - 10
_leap = (_leap[:-10] + b"\xe9" + struct.pack("<i", 0x47AC82 - (_l1 + 5)) + b"\xe9" + struct.pack("<i", 0x47ACB9 - (_l1 + 10)))
_leap = _leap.replace(b"\xd8\x0d" + _a(0), b"\xd8\x0d" + _a(_LEAP + len(_leap))) + struct.pack("<f", 500.0)
assert _LEAP + len(_leap) <= 0x51EF00, hex(_LEAP + len(_leap))
PATCHES += [(_LEAP, bytes(len(_leap)), _leap, "leap chance: long-range leap per second, not per frame (code)"),
            (0x47ACA2, bytes.fromhex("d90485e8f65600d80de0f95100e8f032090083f80574c9"),
             b"\xe9" + struct.pack("<i", _LEAP - 0x47ACA7) + b"\x90" * 18,
             "leap chance: first creature's long-range leap as often per second at any frame rate")]

# HD textures: the texture upload 0x505ee0 (ebp = decoded texture: u16 w [+0], u16 h [+2]) creates the surface at the
# header size and copies that size into the texture record ([ebx+4], [ebx+6]; one path stores float w, h/2 at
# [[ebx+0x14]+0x10/0x14]); the renderer scales texture coordinates by the record. Every original texture is <= 256 a
# side, so a side > 256 marks an HD texture: the surface gets the full HD size, the record gets the original size,
# and coordinates stay as designed. The original size comes from a marker after the pixel and animation-frame data:
# 'RQHD', u16 w, u16 h at +0x412 + bpp*(w*h + frames*fw*fh) (frames byte +0xc, frame size +4/+6). Small textures
# are upscaled 8x/16x so every HD texture has a side > 256 (the marker is only ever read in HD textures). No marker
# (1.5.0 archives) = 4x. Without HD textures the condition never holds, so this is inert.
_HDC = 0x51ED00       # free .text between the HUD cave (ends ~0x51eac8) and the ground cave (0x51ee00)
def _jmp(src, dst): return b"\xe9" + struct.pack("<i", dst - (src + 5))
def _hd_caves():
    # SUB: eax = original w | h << 16 of the texture at ebp (ecx, edx kept)
    sub = (b"\x51\x52" b"\x0f\xb7\x45\x00" b"\x0f\xb7\x4d\x02"              # push ecx/edx; eax = w; ecx = h
           b"\x3d\x00\x01\x00\x00" b"\x77\x0d"                              # w > 256 -> hd
           b"\x81\xf9\x00\x01\x00\x00" b"\x77\x05"                          # h > 256 -> hd
           b"\x8b\x45\x00" b"\xeb\x3f"                                      # eax = [ebp] (w | h<<16); done
           # hd:
           b"\x0f\xaf\xc1"                                                  # eax = w*h
           b"\x0f\xb7\x4d\x04" b"\x0f\xb7\x55\x06" b"\x0f\xaf\xca"          # ecx = fw*fh
           b"\x0f\xb6\x55\x0c" b"\x0f\xaf\xca" b"\x01\xc8"                  # ecx *= frames; eax += ecx
           b"\x0f\xb6\x4d\x0e" b"\x0f\xaf\xc1"                              # eax *= bytes per pixel
           b"\x81\xbc\x05\x12\x04\x00\x00" + b"RQHD"                        # cmp [ebp+eax+0x412], 'RQHD'
           + b"\x75\x09"                                                    # no marker -> /4
           b"\x8b\x84\x05\x16\x04\x00\x00" b"\xeb\x0b"                      # eax = [ebp+eax+0x416]; done
           b"\x8b\x45\x00" b"\xc1\xe8\x02" b"\x25\xff\x3f\xff\x3f"          # eax = ([ebp] >> 2) & 0x3fff3fff
           b"\x5a\x59\xc3")                                                 # done: pop edx/ecx; ret
    out, pc, pats = bytearray(sub), _HDC + len(sub), []
    call = None                                                             # placeholder: call SUB at its own position
    def site(at, orig, parts, back, label):
        nonlocal pc
        body = b""
        for p in parts:
            body += p if p is not None else b"\xe8" + struct.pack("<i", _HDC - (pc + len(body) + 5))
        code = body + _jmp(pc + len(body), back)
        pats.append((at, bytes.fromhex(orig), _jmp(at, pc) + b"\x90" * (len(bytes.fromhex(orig)) - 5), label))
        out.extend(code); pc += len(code)
    # path 0: cx = w, dx = h -> [ebx+4], [ebx+6]
    site(0x5062FC, "668b4d0066894b04668b550266895306",
         [call, b"\x66\x89\xc1\xc1\xe8\x10\x66\x89\xc2\x66\x89\x4b\x04\x66\x89\x53\x06"], 0x50630C, "HD textures: record size path 0")
    # path 5 (animated water etc.: double-height source, w x h/2 surface): same, height halved. Its float size at
    # [[ebx+0x14]+0x10/0x14] is the scroll effect's working size in the source buffer, so it stays the HD size.
    site(0x5063EA, "668b4d0066894b04668b550266d1ea66895306",
         [call, b"\x66\x89\xc1\xc1\xe8\x10\x66\x89\xc2\x66\x89\x4b\x04\x66\xd1\xea\x66\x89\x53\x06"], 0x5063FD, "HD textures: record size path 5")
    # path 4 (skins with animation frames): ax = w, cx = h
    site(0x506506, "668b450066894304668b4d0266894b06",
         [call, b"\x66\x89\x43\x04\xc1\xc8\x10\x66\x89\xc1\x66\x89\x4b\x06\xc1\xc8\x10"], 0x506516, "HD textures: record size path 4")
    assert pc <= _GROUND, hex(pc)
    return [(_HDC, bytes(len(out)), bytes(out), "HD textures: original sizes for HD textures (code)")] + pats
PATCHES += _hd_caves()

# Re-uploads: animated textures (path 5 water scroll, path 4 skin face frames) are flagged dirty (0x10000000) and
# copied again by 0x506900 / 0x506d70 / 0x5073f0 / 0x509240 through 0x5059c0 (ecx = surface, edx = source pixels,
# [esp+0x10] = w, [esp+0x14] = h) with the size from the texture RECORD, which for HD textures is the original size
# -> only a corner copied, at the wrong pitch (user: water "pixelated"). At 0x5059c0's entry: if the surface is exactly
# 4/8/16x the requested size on both axes and the requested size is an original one (<= 256), copy the surface size.
_HDCOPY = 0x51EC00    # free .text after the HUD cave (ends ~0x51eb2e)
_hdcopy = (b"\x60"                                                   # pushad (args now at esp+0x30 / +0x34)
           b"\x83\xec\x7c" b"\xc7\x04\x24\x7c\x00\x00\x00"            # DDSURFACEDESC2 on the stack, dwSize = 0x7c
           b"\x89\xce" b"\x8b\x06" b"\x54" b"\x56" b"\xff\x50\x58"     # surface->GetSurfaceDesc(&desc)
           b"\x85\xc0" b"\x75\x5d"                                     # failed -> leave
           b"\x8b\x9c\x24\xac\x00\x00\x00" b"\x8b\xbc\x24\xb0\x00\x00\x00"   # ebx = w, edi = h (requested)
           b"\x8d\x43\xff" b"\x3d\xff\x00\x00\x00" b"\x77\x45"         # w-1 > 255 (or w = 0) -> leave
           b"\x8d\x47\xff" b"\x3d\xff\x00\x00\x00" b"\x77\x3b"         # same for h
           b"\x8b\x44\x24\x0c" b"\x31\xd2" b"\xf7\xf3" b"\x85\xd2" b"\x75\x2f"   # rw = surface w / w, exact
           b"\x83\xf8\x04" b"\x72\x2a" b"\x89\xc5"                     # rw >= 4
           b"\x8b\x44\x24\x08" b"\x31\xd2" b"\xf7\xf7" b"\x85\xd2" b"\x75\x1c"   # rh = surface h / h, exact
           b"\x39\xe8" b"\x74\x02" b"\xeb\x16"                         # rh == rw -> use the surface size
           b"\x8b\x44\x24\x0c" b"\x89\x84\x24\xac\x00\x00\x00"         # w = surface w
           b"\x8b\x44\x24\x08" b"\x89\x84\x24\xb0\x00\x00\x00"         # h = surface h
           b"\x83\xc4\x7c" b"\x61"                                     # leave: drop desc, popad
           b"\x81\xec\x98\x00\x00\x00")                                # displaced: sub esp, 0x98
_hdcopy += _jmp(_HDCOPY + len(_hdcopy), 0x5059C6)
PATCHES += [(_HDCOPY, bytes(len(_hdcopy)), _hdcopy, "HD textures: re-uploads copy the full HD surface (code)"),
            (0x5059C0, bytes.fromhex("81ec98000000"), _jmp(0x5059C0, _HDCOPY) + b"\x90",
             "HD textures: animated textures (water, skin faces) re-upload at the HD size")]

# HD HUD art: HUD images (media\dibs\Hud, image class 0x4c9f10) load in 3D through 0x509c20 (8-bit BMP -> image
# record at [obj+0x100], surface at record+0x1c), then 0x4ca260 reads the surface size (GetSurfaceDesc into obj+0x124:
# height +0x12c, width +0x130) and lays the image out at that size. The quad 0x508aa0 always maps the whole surface
# (UV 0..1), so an HD surface only needs the original size in those two fields. HD BMPs carry it in the header:
# biXPelsPerMeter = 'RQHD', biYPelsPerMeter = w | h << 16. The loader puts it at record+4 (unused by image records;
# 0 when not HD), and after GetSurfaceDesc (3D path only) a non-zero value replaces the surface size.
_HUDHD = 0x51EC90     # free .text after the HD re-upload cave (ends 0x51ec84)
_hh_a = (b"\x31\xc0" b"\x81\x7c\x24\x2c" + b"RQHD" + b"\x75\x04"   # xor eax,eax; cmp [esp+0x2c] (biXPelsPerMeter), 'RQHD'
         b"\x8b\x44\x24\x30"                                       # eax = biYPelsPerMeter (w | h << 16)
         b"\x89\x46\x04"                                           # [record+4] = eax
         b"\x8b\x94\x24\x50\x01\x00\x00")                          # displaced: mov edx, [esp+0x150]
_hh_a += _jmp(_HUDHD + len(_hh_a), 0x509E42)
_HUDHD_B = _HUDHD + len(_hh_a)
_hh_b = (b"\x83\x3d\xc4\xb0\x6b\x00\x00" b"\x74\x1c"              # 2D load -> leave
         b"\x8b\x83\x04\x01\x00\x00" b"\x85\xc0" b"\x74\x12"       # eax = [obj+0x104] (record+4); 0 -> leave
         b"\x0f\xb7\xc8" b"\x89\x8b\x30\x01\x00\x00"               # width  = w
         b"\xc1\xe8\x10" b"\x89\x83\x2c\x01\x00\x00"               # height = h
         b"\x8b\x83\xf8\x00\x00\x00")                              # leave: displaced mov eax, [ebx+0xf8]
_hh_b += _jmp(_HUDHD_B + len(_hh_b), 0x4CA368)
assert _HUDHD_B + len(_hh_b) <= _HDC, hex(_HUDHD_B + len(_hh_b))
PATCHES += [(_HUDHD, bytes(len(_hh_a) + len(_hh_b)), _hh_a + _hh_b, "HD HUD: original size for HD HUD images (code)"),
            (0x509E3B, bytes.fromhex("8b942450010000"), _jmp(0x509E3B, _HUDHD) + b"\x90\x90",
             "HD HUD: BMP loader keeps the original size of an HD image"),
            (0x4CA362, bytes.fromhex("8b83f8000000"), _jmp(0x4CA362, _HUDHD_B) + b"\x90",
             "HD HUD: HD images laid out at their original size")]

# Menus at the game resolution: RequiemMenu.dll (menu\rqmenu.c) does the work in memory; the exe only loads it, first
# thing at the entry point (the 2D front end starts before the game's own LoadLibrary(".\ddraw.dll")). No DLL or no
# RequiemMenu.cfg = nothing changes.
_MENU = 0x51EDB4      # free .text after the HD texture caves (end 0x51edb4), before the ground cave (0x51ee00)
_menu = b"\x68" + struct.pack("<I", 0) + b"\xff\x15" + struct.pack("<I", 0x51F0A0)   # push dll name; call [LoadLibraryA]
_menu += b"\x55\x8b\xec\x6a\xff"                                                     # displaced: push ebp; mov ebp,esp; push -1
_menu += _jmp(_MENU + len(_menu), 0x5109A7)
_menu = _menu.replace(b"\x68" + struct.pack("<I", 0), b"\x68" + struct.pack("<I", _MENU + len(_menu)), 1) + b"RequiemMenu.dll\x00"
assert _MENU + len(_menu) <= _GROUND, hex(_MENU + len(_menu))
PATCHES += [(_MENU, bytes(len(_menu)), _menu, "menus: load RequiemMenu.dll at start-up (code)"),
            (0x5109A2, bytes.fromhex("558bec6aff"), _jmp(0x5109A2, _MENU), "menus: entry point loads RequiemMenu.dll first")]

# Game memory arena: one VirtualAlloc at the fixed address 0x6000000 of 0x852B40 bytes (~8.3 MB, bump allocator
# 0x4461d0 etc.) holds the level (JAM) and some textures (loader 0x4f5bf0, which does not check for a NULL result).
# HD skins (1024x1024 + frames) overflow it -> crash in the explode write callback 0x45fc43. Grow it to 128 MB
# (0x6000000-0xE000000; no game-folder DLL is based there). Every use of the size / end / -size is in 0x446130-0x4464a0.
_ARENA = 0x8000000
for _a in (0x44613D, 0x446154, 0x44618E, 0x44620E, 0x446263, 0x4462DF, 0x4463CE, 0x44641D, 0x446431, 0x44646C, 0x44649D):
    PATCHES.append((_a, struct.pack("<I", 0x852B40), struct.pack("<I", _ARENA), f"game memory arena 128 MB (size at {_a:#x})"))
PATCHES.append((0x446288, struct.pack("<I", 0x6852B40), struct.pack("<I", 0x6000000 + _ARENA), "game memory arena 128 MB (end)"))
for _a in (0x4461B1, 0x446232, 0x4463ED):
    PATCHES.append((_a, struct.pack("<I", -0x852B40 & 0xFFFFFFFF), struct.pack("<I", -_ARENA & 0xFFFFFFFF), f"game memory arena 128 MB (-size at {_a:#x})"))


def aspect_patches(aspect):
    # The camera's view window is x -100..100, y -75..75 (4:3); projection scales are 1/width and 1/height
    # of it, so other aspects get stretched. Keep y and widen x to 75*aspect (Hor+). Both constant sources:
    # camera init (0x4210e1) and camera reset (0x422233); every other write derives from these.
    # ponytail: aspect is baked in at patch time, re-run with --aspect after changing to a different-shaped resolution.
    half = struct.pack("<f", 75.0 * aspect)
    neg = struct.pack("<f", -75.0 * aspect)
    old_neg, old_pos = struct.pack("<f", -100.0), struct.pack("<f", 100.0)
    return [
        (0x4210E7, old_neg, neg, f"camera init view window x left = {-75 * aspect:.2f}"),
        (0x4210F1, old_pos, half, f"camera init view window x right = {75 * aspect:.2f}"),
        (0x422239, old_neg, neg, f"camera reset view window x left = {-75 * aspect:.2f}"),
        (0x422243, old_pos, half, f"camera reset view window x right = {75 * aspect:.2f}"),
    ]


CAVE = 0x51E760   # unused tail of .text (vsize ends 0x51e760, mapped to 0x51f000, zeros in the file)

# HD textures and the game's generated textures (stained glass, glows: upload paths 2/3 at 0x5060fa, record ebx,
# generator [ebx+0x14], its source record [gen+0x18]). The generator's set-up copies the source's pixels into new
# buffers and makes the target surface, all at the TARGET record's size (128x128; the effects 0x4f4f30 / 0x4f5180 /
# 0x4f53f0 are written for 128x128); with an HD source that copy was the first 1/16 of the HD pixels at the wrong
# row length (user: the opening tunnel's window "combed"). Here, when the source is HD at exactly 4x the target
# record, the record holds the HD size during the set-up (buffers, copies and surface all HD; the source keeps HD
# pixels to match its HD surface) and gets its original size back at the end (0x506601), so texture coordinates
# stay as designed. RequiemMenu.dll then redraws the effects at the HD size every frame (rqmenu.c gen_hd).
# Shares CAVE with the --trace diagnostics, so it is left out of --trace builds.
_GENSAVE = 0x6BF780   # .data slack (after the trace RING, which ends 0x6bf610): record being set up, its size
def gen_patches():
    a = (b"\x8b\x7b\x14" b"\x89\x7c\x24\x1c"              # displaced: edi = generator; [esp+0x1c] = edi
         b"\x8b\x47\x18" b"\x8b\x40\x08"                  # eax = source record -> its texture object
         b"\x8b\x48\x14" b"\x83\xe9\x12"                  # ecx = its decoded header (palette - 0x12)
         b"\x0f\xb7\x11" b"\x0f\xb7\x41\x02"              # edx = source w, eax = source h (both reloaded after the cave)
         b"\x0f\xb7\x4b\x04" b"\xc1\xe1\x02" b"\x39\xd1" b"\x75\x22"   # 4 * record w != w -> back
         b"\x0f\xb7\x4b\x06" b"\xc1\xe1\x02" b"\x39\xc1" b"\x75\x17"   # 4 * record h != h -> back
         b"\x8b\x4b\x04" b"\x89\x0d" + struct.pack("<I", _GENSAVE + 4)   # save the record size
         + b"\x89\x1d" + struct.pack("<I", _GENSAVE)                     # and the record
         + b"\x66\x89\x53\x04" b"\x66\x89\x43\x06")                     # record = HD size for the set-up
    a += _jmp(CAVE + len(a), 0x506101)
    b_at = CAVE + len(a)
    b = (b"\x3b\x1d" + struct.pack("<I", _GENSAVE) + b"\x75\x12"           # not the record being set up -> skip
         + b"\xa1" + struct.pack("<I", _GENSAVE + 4) + b"\x89\x43\x04"   # original size back
         + b"\xc7\x05" + struct.pack("<I", _GENSAVE) + b"\x00\x00\x00\x00"
         + b"\x0f\xbf\x43\x04" b"\x0f\xbf\x4b\x06")                     # displaced: movsx eax/ecx, [ebx+4]/[ebx+6]
    b += _jmp(b_at + len(b), 0x506609)
    # Face animation (skins, 0x4f58b0): each frame is copied into the atlas row by row with the pitch taken from the
    # texture RECORD width (the original 256), while an HD atlas is 1024 wide, so the face rows landed in other parts
    # of the skin (user: faces on the side of the head and on the legs). The pitch now comes from the texture's own
    # decoded header (frames start [anim+0xc] - 0x412), which is the record width when the texture is not HD.
    f_at = b_at + len(b)
    f = b"\x8b\x53\x0c" b"\x0f\xb7\x92\xee\xfb\xff\xff" b"\x0f\xaf\xee"   # edx = header w; displaced imul ebp, esi
    f += _jmp(f_at + len(f), 0x4F58FC)
    c = a + b + f
    assert CAVE + len(c) <= _DECAY
    return [(CAVE, bytes(len(c)), c, "HD textures: generated textures set up at the HD size (code)"),
            (0x5060FA, bytes.fromhex("8b7b14897c241c"), _jmp(0x5060FA, CAVE) + b"\x90\x90",
             "HD textures: generated textures (stained glass) set up at the HD size"),
            (0x506601, bytes.fromhex("0fbf43040fbf4b06"), _jmp(0x506601, b_at) + b"\x90\x90\x90",
             "HD textures: generated textures keep their original record size"),
            (0x4F58F5, bytes.fromhex("0fbf57040fafee"), _jmp(0x4F58F5, f_at) + b"\x90\x90",
             "HD textures: face animation frames copied at the atlas's own row length")]
RING = 0x6BF400   # unused tail of .data (vsize ends 0x6bf2f8, mapped to 0x6c0000): dword index, then 32 x 16-byte entries
FRAME = 0x531FD8  # frame counter, incremented at the top of the frame function 0x448450
DEVICE = 0x6B9F74  # IDirect3DDevice3*


def trace_patches():
    """Diagnostics for the NULL-device crash (device torn down mid-frame, then EndScene/DrawPrim uses it).
    Records each 3D teardown / rebuild / menu switch / error box into a ring buffer: entry = (frame << 8 | tag,
    caller, first stack arg, ecx). Read it from a dump or the live game at RING. Also guards BeginScene and
    EndScene (0x5072b0, 0x507300) against a NULL device, logging tags 5 and 6 instead of crashing.
    ponytail: temporary, remove once the trigger is known and fixed at its source."""
    code = bytearray()
    pc = lambda: CAVE + len(code)
    rel = lambda target, end: struct.pack("<i", target - end)

    # log(edx = tag), called right after pushad: [esp+28] ecx, [esp+36] hooked function's return address, [esp+40] arg1
    log = pc()
    code += b"\xA1" + struct.pack("<I", RING)                 # mov eax, [RING]
    code += b"\x83\xE0\x1F\xC1\xE0\x04"                       # and eax, 31; shl eax, 4
    code += b"\x8D\x88" + struct.pack("<I", RING + 0x10)      # lea ecx, [eax + RING+0x10]
    code += b"\x8B\x1D" + struct.pack("<I", FRAME)            # mov ebx, [FRAME]
    code += b"\xC1\xE3\x08\x09\xD3\x89\x19"                   # shl ebx, 8; or ebx, edx; mov [ecx], ebx
    code += b"\x8B\x54\x24\x24\x89\x51\x04"                   # mov edx, [esp+36]; mov [ecx+4], edx
    code += b"\x8B\x54\x24\x28\x89\x51\x08"                   # mov edx, [esp+40]; mov [ecx+8], edx
    code += b"\x8B\x54\x24\x1C\x89\x51\x0C"                   # mov edx, [esp+28]; mov [ecx+12], edx
    code += b"\xFF\x05" + struct.pack("<I", RING)             # inc dword [RING]
    code += b"\xC3"

    patches = []

    def hook(addr, orig, tag, why):  # log, then run the 5 displaced bytes and continue
        start = pc()
        code.extend(b"\x60\xBA" + struct.pack("<I", tag))     # pushad; mov edx, tag
        code.extend(b"\xE8" + rel(log, pc() + 5))             # call log
        code.extend(b"\x61" + orig)                           # popad; original instruction
        code.extend(b"\xE9" + rel(addr + 5, pc() + 5))        # jmp back
        patches.append((addr, orig, b"\xE9" + rel(start, addr + 5), why))

    def guard(addr, tag, why):  # wrapper starts with mov eax,[DEVICE]: if NULL, log and return to the caller
        orig = b"\xA1" + struct.pack("<I", DEVICE)
        start = pc()
        code.extend(orig + b"\x85\xC0")                       # mov eax, [DEVICE]; test eax, eax
        code.extend(b"\x0F\x85" + rel(addr + 5, pc() + 6))    # jnz back
        code.extend(b"\x60\xBA" + struct.pack("<I", tag))
        code.extend(b"\xE8" + rel(log, pc() + 5))
        code.extend(b"\x61\xC3")                              # popad; ret (wrapper has pushed nothing yet)
        patches.append((addr, orig, b"\xE9" + rel(start, addr + 5), why))

    hook(0x505130, b"\xA1\xC4\xB0\x6B\x00", 1, "trace: 3D teardown")
    hook(0x5051D0, b"\xA1\xC4\xB0\x6B\x00", 2, "trace: 3D rebuild")
    hook(0x459080, b"\xA1\x38\x77\x5C\x00", 3, "trace: switch to 640x480 menu")
    hook(0x491980, b"\xB8\x00\x10\x00\x00", 4, "trace: ATTENTION! error box (arg1 = message)")
    guard(0x5072B0, 5, "guard: BeginScene with NULL device")
    guard(0x507300, 6, "guard: EndScene with NULL device")
    assert len(code) <= 0x8A0
    return [(CAVE, bytes(len(code)), bytes(code), f"trace code cave ({len(code)} bytes)")] + patches


def apply(data, pe, patches):
    for va, old, new, why in patches:
        off = pe.get_offset_from_rva(va - pe.OPTIONAL_HEADER.ImageBase)
        if bytes(data[off:off + len(old)]) != old:
            sys.exit(f"unexpected bytes at {va:#x}: not the GOG v1.2 D3D.exe, nothing written")
        data[off:off + len(old)] = new
        print(f"patched: {why}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--aspect", default="4:3", help="screen shape as W:H, e.g. 16:9, 21:9, 16:10")
    ap.add_argument("--trace", action="store_true", help="add the 3D teardown trace + NULL-device guards")
    ap.add_argument("--hud", type=int, default=0, metavar="H",
                    help="scale the HUD as if designed for an H-pixel-high screen (480 = full proportional; 0 = off)")
    a = ap.parse_args()
    build(a.exe, a.aspect, a.hud, a.trace)


def build(exe, aspect="4:3", hud=0, trace=False):
    """Rebuild exe from exe.orig with all fixes, the given screen shape (W:H) and HUD scale (0 = off)."""
    w, h = (float(x) for x in aspect.split(":"))
    orig = exe + ".orig"
    if not os.path.exists(orig):
        shutil.copyfile(exe, orig)
    pe = pefile.PE(orig, fast_load=True)
    data = bytearray(open(orig, "rb").read())
    apply(data, pe, PATCHES + aspect_patches(w / h) + (trace_patches() if trace else gen_patches())
          + (hud_patches(hud)[0] if hud else []))
    pe.close()
    open(exe, "wb").write(data)


if __name__ == "__main__":
    main()
