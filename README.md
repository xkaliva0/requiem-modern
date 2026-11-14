# Requiem Modern

A launcher and set of fixes that make **Requiem: Avenging Angel** (1999, Cyclone Studios / 3DO; GOG version 1.2)
run properly on Windows 10/11: any resolution and frame rate, widescreen, menus at full resolution, borderless
alt-tab, EAX audio through DSOAL, the game's own options and key bindings in the launcher, and F10 to change them
while playing. Optional HD art (AI-upscaled textures, HUD icons and menu art) is made by the launcher on your own
PC, from your own copy of the game.

**Download:** see [Releases](../../releases): one zip with the launcher. It carries none of the game's art: **MAKE HD
ART** (main menu) upscales your own game's textures, HUD icons and menu art on your PC with the bundled
[Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) (needs a Vulkan graphics card; without one the textures are
enlarged smoothly instead). Player documentation: the README inside the zip.

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
| `mod/hd_make.py` | MAKE HD ART: the whole HD pipeline, run by the launcher on the player's PC (textures, skins' animation frames, effects, HUD, menu masters) from their original files. |
| `mod/tex_extract.py`, `mod/hd_rest.py`, `mod/hd_build.py` | The texture formats: extract, animation frames, rebuild in the game's own formats with the `RQHD` marker. (`tex_upscale.py`, `hd_pack.py`: the original development-time tools.) |
| `launcher/realesrgan` | realesrgan-ncnn-vulkan and the x4plus model, bundled for MAKE HD ART (licences in `LICENSES.txt` there). |
| `docs/DEVLOG.md` | The full reverse-engineering and test log: every address, every fix, what was tried and how it was verified. |

## Building

Requirements: Windows, Python 3.12+ with `pyinstaller`, `pillow` and `pefile`; `ziglang` (`py -m pip install ziglang`)
for the DLL.

```bat
menu\build.bat            :: RequiemMenu.dll (32-bit, zig cc)
launcher\build.bat        :: launcher\dist\Requiem Modern.exe
```

No game art is in this repository or in the release: the launcher makes it on the player's PC (`mod/hd_make.py`).
`docs/DEVLOG.md` has the details of every step.

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
- [Real-ESRGAN](https://github.com/xinntao/Real-ESRGAN) by Xintao Wang et al. (BSD-3-Clause) and
  [realesrgan-ncnn-vulkan](https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan) (MIT, on
  [ncnn](https://github.com/Tencent/ncnn) by Tencent, BSD-3-Clause), bundled in `launcher/realesrgan` for MAKE HD ART.
- Requiem: Avenging Angel (c) 1999 The 3DO Company / Cyclone Studios.

**How it was made:** reverse-engineered and written by Claude (Anthropic's AI model, Claude Opus, in Claude Code),
directed and play-tested by the repository owner. Each fix was verified in the running game; the log is in
`docs/DEVLOG.md`.

## License

MIT for the Requiem Modern code (`LICENSE`). Bundled third-party parts keep their own licences (`LICENSES/`,
`launcher/dsoal/`, `launcher/realesrgan/`).
