# Requiem Modern

A launcher and set of fixes that make **Requiem: Avenging Angel** (1999, Cyclone Studios / 3DO; GOG version 1.2)
run properly on Windows 10/11: any resolution and frame rate, widescreen, menus at full resolution, borderless
alt-tab, EAX audio through DSOAL, the game's own options and key bindings in the launcher, and F10 to change them
while playing. Optional HD packs (AI-upscaled game art) are built from your own copy of the game.

**Download:** see [Releases](../../releases): one zip with the launcher and the HD art (AI-upscaled versions of the
game's art, packed inside the exe; each HD option can be switched off). Player documentation: the README inside it.

This repository holds the source only. It contains no game files: the launcher reads and patches the player's own
copy of the game, and everything it replaces is backed up and can be restored.

## How it works

| Part | What it does |
|---|---|
| `launcher/requiem_modern.py` | The launcher / installer (Tkinter). Installs DDrawCompat and DSOAL, writes their settings, rebuilds `D3D.exe` from the original with `mod/patch_d3d.py`, installs the HD art, edits the game's options file, and stays in the background while the game runs for F10. |
| `launcher/game_cfg.py` | Reads and writes the game's own options file `Gamers\latest.cfg` (flags, volumes, brightness, the 256-entry key table). |
| `mod/patch_d3d.py` | Byte patches and code caves for the GOG v1.2 `D3D.exe`: renderer and DirectInput crash fixes, widescreen camera, HUD scale, frame-rate independent physics and creature AI, HD texture and HUD support, 128 MB game memory, loading `RequiemMenu.dll`. Every patch checks the original bytes first. |
| `menu/rqmenu.c` | `RequiemMenu.dll`: draws the 2D front end (DirectDraw, 640x480, 8-bit) at the game resolution by scaling every draw call; maps the mouse; borderless alt-tab; F10 and live settings (shared memory, applied on the game's thread). |
| `mod/art_build.py`, `mod/blast.py` | The texture archive format (PKWARE DCL implode); `blast.py` is a Python port of zlib's blast.c. |
| `mod/menu_hd.py`, `mod/hud_hd.py` | HD menu art and HUD icons: upscale, back to the original palette and colour key, `RQHD` header with the original size. |
| `mod/tex_extract.py`, `mod/tex_upscale.py`, `mod/hd_rest.py`, `mod/hd_build.py`, `mod/hd_pack.py` | The HD texture pipeline: extract the game's textures, upscale (Real-ESRGAN), rebuild in the game's formats, pack the payload the launcher appends. |
| `docs/DEVLOG.md` | The full reverse-engineering and test log: every address, every fix, what was tried and how it was verified. |

## Building

Requirements: Windows, Python 3.12+ with `pyinstaller`, `pillow` and `pefile`; `ziglang` (`py -m pip install ziglang`)
for the DLL.

```bat
menu\build.bat            :: RequiemMenu.dll (32-bit, zig cc)
launcher\build.bat lite   :: launcher\dist_lite\Requiem Modern.exe, without HD art
launcher\build.bat        :: launcher\dist\Requiem Modern.exe, with the HD art if hd\ holds it
```

The HD art is not in this repository. To make it from your own copy of the game: extract the textures
(`mod/tex_extract.py`), upscale them with [Real-ESRGAN ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan)
(`mod/tex_upscale.py`, `mod/hd_rest.py`), build and pack them (`mod/hd_build.py`, `mod/hd_pack.py build`); the HUD
and menu art with `mod/hud_hd.py` and `mod/menu_hd.py masters` / `pack`. The scripts' folder constants at the top
point at the original development lab; set them to yours. `docs/DEVLOG.md` has the details.

## Antivirus warnings

`Requiem Modern.exe` is an unsigned PyInstaller one-file program, and a game mod necessarily does things some
antivirus heuristics associate with malware: it patches the game's exe, its DLL hooks Windows window functions
inside the game process, it watches the F10 key (only while the game window has the focus) and it shares a block of
memory with the game for the live settings. Some scanners flag such files by mistake. Everything it does is in this
repository's source; you can build the exe yourself (see Building).

## Credits

- [DDrawCompat](https://github.com/narzoul/DDrawCompat) by narzoul (0BSD), bundled in `launcher/ddrawcompat`.
- [DSOAL](https://github.com/kcat/dsoal) (LGPL 2.1) and [OpenAL Soft](https://github.com/kcat/openal-soft) (LGPL) by
  kcat, bundled in `launcher/dsoal` (DSOAL r697; licences and version alongside).
- blast.c by Mark Adler (zlib licence), ported in `mod/blast.py`.
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (BSD-3-Clause) for the HD art.
- Requiem: Avenging Angel (c) 1999 The 3DO Company / Cyclone Studios.

**How it was made:** reverse-engineered and written by Claude (Anthropic's AI model, Claude Opus, in Claude Code),
directed and play-tested by the repository owner. Each fix was verified in the running game; the log is in
`docs/DEVLOG.md`.

## License

MIT for the Requiem Modern code (`LICENSE`). Bundled third-party parts keep their own licences (`LICENSES/`,
`launcher/dsoal/`).
