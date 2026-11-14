# Requiem: Avenging Angel — mod log

Lab folder: the development folder; `mod\`, `launcher\`, `menu\`, `hd\` and `testgame\` below are relative to it.

## State when first paused (2026-11-02, superseded by Installed state below)
- Game folder = pristine GOG install except `D3D.exe` (patched; original at `D3D.exe.orig`).
- Full backup: `backups\requiem-pristine\20261102-205528.zip` (2394 files, verified) + `3DO-registry.reg`.
  Restore: unzip over the game folder (`um backup restore` can't find it since it was moved off C:;
  use `um backup restore requiem-pristine --snapshot <zip>`).
- dgVoodoo2 2.87.6 release + debug builds in `downloads\dgvoodoo\`; configured conf + Cpl parked in `parked-from-game\`
  (FullScreenMode=false, VRAM=1024, Filtering=16, AA=4x, ExtraEnumeratedResolutions up to 3840x2160,
  watermark currently ON and MaxTraceLevel=1 for debugging — turn both back off for play).
- `3DFX.exe` (GOG default, nGlide) also imports DDRAW.dll, so wrapper DLLs in the game folder affect it too.

## D3D.exe patches (`mod\patch_d3d.py`, checks original bytes, idempotent)
1. VA 0x465950: RegOpenKeyEx(HKLM\Software\Microsoft\DirectX, KEY_ALL_ACCESS) -> KEY_READ.
   Without admin it failed -> "Sorry, DirectX 6 or later is required." Confirmed fixed in game.
2. VA 0x52BE58: LoadLibrary("ddraw.dll") -> ".\ddraw.dll" (DX SDK D3DEnum code at 0x50b70f).
   Win8+ resolved the bare name to System32. Confirmed: enumeration now goes through dgVoodoo.

## 3D init: FIXED (2026-11-03)
3. VA 0x50BE07: `jge` -> `jmp` after IDirectDraw4::Initialize (call at 0x50be00). The object comes from
   DirectDrawCreate already initialized, so Initialize returns DDERR_ALREADYINITIALIZED (0x88760005) and the
   DX manager (vtable 0x52bdd8, +0x58 at 0x50bd36) aborted -> "Could not initialize 3-D graphics".
   Verified with `mod\bp.py`: all three init stages return 1, 256 display modes enumerated.
   ponytail: ignores Initialize's GUID, so only the primary display is honoured; fine for the default device.

## D3D.exe reaches the main menu (2026-11-03, confirmed in play)
- The "DirectInput could not acquire keyboard" error came from Windows' "needs DirectPlay" compatibility prompt
  stealing focus from the game window (keyboard uses NONEXCLUSIVE|FOREGROUND, flags 6 at 0x45d861).
  Tester installed the DirectPlay optional feature, and the game now starts to the 640x480 menu with dgVoodoo.
- Untested: alt-tab mid-game. The re-acquire path (0x45ddd0..0x45de28) is fatal after 16 failed tries;
  fallback patch is `push 6` -> `push 0xA` (BACKGROUND) at 0x45d861.

## Resolution list (2026-11-03)
- The game's mode buffer at 0x6b8560 holds 256 entries of 16 bytes (w, h, bpp, Hz), sorted ascending, and is
  filled through EnumDisplayModes(DDEDM_REFRESHRATES). dgVoodoo's "all" list with every refresh rate overflowed it,
  so the list stopped at 1440x900. Fix (conf only): DefaultEnumeratedResolutions = classics,
  ExtraEnumeratedResolutions = 1280x720@60 ... 3840x2160@60. Now 43 modes enumerated, 14 kept by the game,
  1920x1080 included (checked with `mod\peek.py 6bb0c8:4 6b8560:1000`).

## Cutscene crashes (2026-11-03/04)
- Release dgVoodoo: crash at 1080p (D3D.exe+0xBAE9D, list walk in renderer, unchecked pool at 0x648938) and at 720p
  after maybe alt-tabbing ("XLR8_DrawLine: DrawPrim failed!", then NULL device [0x6b9f74] at 0x508453).
  MP3DEC.ASI+0x18E5 crash follows each one during teardown.
- Debug dgVoodoo + dbwin log, 720p: opening cutscene finished both without and with alt-tab (confirmed in play).
  Alt-tab makes dgVoodoo mark the render target lost (game uses exclusive coop 0x911); 6 BeginScene failures,
  and the game recovered. Each menu<->game switch does SetDisplayMode + a new CreateDevice (7 per session).
  "Failed to Init DXMgr!" appears only during shutdown.
- So the crash is intermittent: probably a race when restoring lost surfaces, or a 1080p-only problem.
- 1080p with debug build: opening cutscene finished (confirmed in play). Release build reinstalled for play;
  if a crash comes back, swap in the debug DLLs and run `py mod\dbwin.py 3600 > dbwin-play.log`.
  Log of the good 720p session: dbwin-game.log.gz

## Widescreen FOV (2026-11-04)
- Camera object at 0x57a4b8: FOV (console `FOV n`, default 120, max 250) at +0x938; view window x0,x1,y0,y1 at
  +0x95c..+0x968; projection scales xs = 1/(x1-x0) at +0x974 (0x57ae2c), ys = 1/(y1-y0) at +0x978 (0x57ae30).
  Window is hard-coded x +/-100, y +/-75 (4:3) at camera init 0x4210e1 and reset 0x422233; all other writes derive from it,
  so 16:9 was stretched sideways.
- Patch (patch_d3d.py --aspect W:H): x window = +/-75*aspect. 16:9 -> +/-133.33 (Hor+). Running game shows
  xs=0.00375, ys=0.00667 (ratio 16:9). Tester confirmed in game at 1080p: proportions correct.
- patch_d3d.py now always rebuilds from D3D.exe.orig, so `--aspect 4:3` returns to the stock view.

## Tools in mod\
- `patch_d3d.py exe [--aspect 16:9]`: all D3D.exe patches, rebuilt from D3D.exe.orig each run.
- `bp.py 15 addr...`: one-shot int3 tracer (WOW64 debugger), prints eax/edx/ecx at each address.
  Frida does NOT work: its agent collides with the game's fixed VirtualAlloc pool at 0x6000000, and
  Defender blocked its helper (error 225). Uninstalled.
- `peek.py addr:len...`: read globals while the game is running. `dbwin.py`: OutputDebugString capture.
- `fps_sample.py [secs]`: attaches to a running D3D.exe, prints fps plus peak renderer section/node counts each second.
- `catch_crash.py` (or `Requiem (crash catcher).bat`): launches the game under a minimal debugger and appends to
  crash.log (game debug text, first-chance AVs, crash registers + game return addresses). On a crash it writes a
  full-memory dump to dumps\. Never caught a crash (the debugger seems to hide it).
- `crash_watch.py` (what the .bat runs now): plain launch, dumps the game from outside when WerFault.exe starts.
- `dmp.py dump find-ctx EIP | read ADDR LEN`: reads full-memory minidumps (no WinDbg needed); find-ctx locates the
  x86 CONTEXT/EXCEPTION_RECORD the crash left on the stack.

## Installed state (2026-11-04)
- Game folder: GOG original except patched D3D.exe (3 fixes + 16:9 view; original in D3D.exe.orig) and dgVoodoo 2.87.6
  release build: ddraw.dll, D3DImm.dll, dgVoodooCpl.exe, dgVoodoo.conf (windowed, 16x AF, 4x MSAA,
  watermark off, MaxTraceLevel 0).
- 3DFX.exe (GOG Galaxy's default) also imports DDRAW.dll, so it now gets dgVoodoo's instead of GOG's.
  If 3DFX.exe breaks: copy orig\ddraw.dll back (GOG's) and launch D3D.exe only when dgVoodoo is in place.
- Debug build for tracing: downloads\dgvoodoo\dbg\MS\x86 (set MaxTraceLevel=2 when using it).

## FPS (2026-11-04)
- Game's own counter (0x5c6d7c, see `mod\fps_sample.py`): steady 61 fps at 1080p, game speed correct (confirmed in play).
  It is already capped, so no limiter needed.

## Intermittent in-level crash (2026-11-04, open)
- Release dgVoodoo crashes so far: D3D.exe+0xBAE9D (x2, renderer list walk at 0x4bac80), +0x108453 (NULL device
  after DrawPrim failed), +0x57AFC (bad `this` in ecx at 0x457af0 entry). MP3DEC.ASI+0x18E5 is teardown fallout each time.
- Ruled out: renderer table overflow. Peak sections 15/140 and nodes 154/560 during play; peaks didn't line up with crashes.
- Pattern: 4/4 crashes with release dgVoodoo; 0/3 with the debug build; 0/1 (11 min) under `catch_crash.py` while
  it still used the debug heap. Points to heap corruption or use-after-free that a changed memory layout hides.
- catch_crash.py now sets `_NO_DEBUG_HEAP=1` so the run matches a plain launch. Next: play under it until a crash, then
  read crash.log and dumps\*.dmp. If it still won't crash, PageHeap (IFEO GlobalFlag 0x02000000, needs admin) is next.
  Clean session log: crash-session1-nocrash.log.
- Second session under catch_crash.py with _NO_DEBUG_HEAP: 7 min, no crash. So 0/5 runs with anything attached
  (debugger, or dbwin.py capturing OutputDebugString, which also pauses the game on each log line) vs 4/4 crashes
  with nothing attached. Suspect a timing race, not just heap layout.
- Switched the launcher .bat to `mod\crash_watch.py`: starts the game plainly and, when WerFault.exe appears
  (crashed process still frozen), writes a full dump from outside. Smoke-tested with a deliberately crashing process.

### First captured crash (2026-11-05, crash_watch.py, dumps\D3D-20261105-112708.dmp)
- D3D.exe+0x107306 after 76 s of play: EndScene wrapper 0x507300 read through a NULL device [0x6b9f74]
  (read of 0x0, eax=ecx=0). Called from the frame function 0x448450 at 0x448671 via thunk 0x459db0.
  Same failure class as the earlier +0x108453 (XLR8_DrawLine on a NULL device).
- Dump state: 3D-up flag [0x6bb0c4]=0, device-created [0x6b9e5c]=0, D3D/device/0x6b9f78 all NULL, DD manager
  [0x6b9ea8] still alive. The rebuild 0x5051d0 sets [0x6bb0c4]=1 first thing, so the last 3D event was a
  teardown (0x505130) with no rebuild. BeginScene (0x5072b0, frame call at 0x44854e) also derefs the device and
  didn't crash, so the teardown happened mid-frame, between BeginScene and EndScene.
- Teardown callers: 0x45908f (in 0x459080 "switch to 640x480 menu", called only from the front end 0x4d2xxx/0x4d98b3),
  0x4597fb (WM_CLOSE "Quit?" box, rebuilds on No), 0x4919c7 (ATTENTION! error box 0x491980, rebuilds after),
  0x505571 (mode change 0x505550, rebuilds), 0x465d0a / 0x4664f4 (startup), 0x505104 (shutdown).
  The only direct path from inside the frame: 0x4c67b0 -> ... -> 0x45bbb0 -> 0x491980 (error box, which rebuilds).
  So the trigger is an indirect call; static call graph can't see it.
- 0x4027b0 (the game's debug print) is a bare `ret` in this release build: no message text in memory to recover.
- Window proc 0x4597c0: WM_ACTIVATEAPP only sets [0x5c6fb4]; main loop 0x459c70 pumps messages between frames.
- `patch_d3d.py --trace` (installed now): ring buffer at 0x6bf400 (index) / 0x6bf410 (32 x 16 bytes:
  frame<<8|tag, caller, arg1, ecx). Tags 1 teardown, 2 rebuild, 3 menu switch, 4 error box (arg1 = message),
  5/6 BeginScene/EndScene skipped because device NULL (guards, so that path no longer crashes). Code cave 0x51e760.
  Verified at startup: 1@0x465d0f, 1@0x4664f9, 3@0x4d98b8, 1@0x459094, all frame 1.
- The crashed process stayed as an unkillable zombie (one thread stuck in the kernel) holding D3D.exe, so the old
  exe was renamed to D3D.exe.stuck in the game folder; delete it after a reboot.

### ROOT CAUSE FOUND AND FIXED (2026-11-05, reproduced by me in game)
- Dump also showed frame counter [0x531fd8]=2 (counter starts at 1, so first gameplay frame), active [0x5c6fb4]=0,
  game-loop flag [0x5c774c]=0.
- Reproduced: alt-tab out and back during play -> DrawPrimitive fails briefly (surfaces lost) -> XLR8_DrawLine
  (0x5085fc) calls MessageBoxA(NULL, "DrawPrim failed!", "XLR8_DrawLine") at 0x50860f: a debug box left in the
  release build. Ownerless, so it steals focus (active=0) and blocks the frame mid-way (frame counter froze at 549;
  two boxes in a row; OK x2 resumed). Quitting while it's up (X / Alt+F4 -> "Quit?" Yes) runs the WM_CLOSE path:
  3D teardown + loop flag 0. The box returns, the frame resumes and EndScene/DrawPrim use the NULL device.
  Matches every value in the dump, and an earlier "DrawPrim failed!" screenshot before a crash.
- Fix (permanent, in PATCHES): 0x50860f `call [MessageBoxA]` -> `add esp,0x10; nop x3`. A failed line draw is just
  skipped for that frame. Other MessageBox sites (Quit, About, ATTENTION fatal box, front end) are not mid-frame.
- Verified: new game, 5 rounds of alt-tab out 4 s and back during play: no box, frames kept running (~60 fps),
  rendering correct, no crash; then WM_CLOSE + "Quit?" Yes mid-game: clean exit code 0x1.
- The earlier crash sites +0xBAE9D / +0x57AFC were probably the same box/quit sequence corrupting state; watch for them.
- The `--trace` build (ring + NULL guards) was used for testing only; the installed exe no longer has it.

### Driving the game myself (for future tests)
- Launch `py mod\crash_watch.py nomovies` (skips intro videos; menu in ~18 s). Other args seen: nosound, nocd, window,
  clipmouse, nolines, fullbright.
- Menus react to plain virtual keys (`um win drive --proc D3D "focus" "key 0x28"`), NOT scanmode; mouse clicks don't
  register (hover highlights). From the main menu: click 5 5 (activate), Down, Enter (Single Player), Down, Down, Enter
  (New Game). 3D comes up ~60-70 s later; opening cutscene ~2000 frames.
- In game, movement needs `scanmode on` (DirectInput): `hold 0x57 1500`, `rel 300 0`.
- Screens: static menus present no frames, so gfxcapture (`um win shot`) needs a key/mouse nudge during capture;
  `mod\pwshot.py` (PrintWindow) works on the 1920 menu but is black in 3D and on the 640x480 menu.
- `mod\ring.py [dump]` decodes the trace ring (live or from a dump); `mod\ring_watch.py secs` polls it.
  `mod\cycle.sh` / `mod\focus_test.sh` are first attempts at full-cycle scripts (navigation timing needs the notes above).

## Quick polish (2026-11-05)
- Menus: dgVoodoo.conf `ScalingMode = stretched_ar`, `WindowedAttributes = borderless, fullscreensize` (still
  FullScreenMode=false, the mode alt-tab was tested in). Window is always desktop-size; the 640x480 menus show 4:3
  with side bars instead of stretched, gameplay at 1920x1080 is unaffected. Backup: dgVoodoo.conf.before-polish.
- DirectInput: input poll 0x45dd50 showed "DirectInput could not acquire/communicate with mouse/keyboard" and exited
  (0x50f711) when (re)acquire failed, e.g. focus lost at the wrong moment. The four fatal blocks (0x45ddfa, 0x45de11,
  0x45de28, 0x45de3f) now jmp 0x45dd61, the function's own "return 0 = no input this frame" (its joystick branch
  already did that). In PATCHES.
- Verified (me, nomovies run): menu 4:3 pillarboxed in a 1920x1080 window; cutscene/level full 16:9; 5 alt-tab rounds
  with movement, frames kept running, no dialog; WM_CLOSE + Quit? Yes -> clean exit 0x1.
- Tester saw a flickering second cursor in the menu after this (dgVoodoo emulates a scaled cursor once the 640x480
  menu is scaled, and the real cursor shows too). Set `SystemHookFlags = cursor` (dgVoodoo's documented fix for double
  cursors). Tester confirmed the double cursor is gone (2026-11-05).
- Tester then reported the menu feels very low fps when navigating, cursor shows the "loading" shape.
  `mod\menu_fps.sh` (gfxcapture frame count, 5 s) can't tell configs apart: the menu only presents on changes and the
  capture excludes the cursor (scaled+hook 8, scaled no hook 8, unscaled 5 frames with mouse sweep; idle 3 with
  FastVideoMemoryAccess false or true). Suspect dgVoodoo's cursor emulation on the scaled menu (full re-present per
  mouse move). Set FastVideoMemoryAccess = true (harmless). Tester: still slow, with the scaled and the unscaled menu.
- `mod\sample.py` (suspend main thread briefly, read EIP + game stack, 50x) on the tester's running menu: main thread
  mostly inside system/dgVoodoo code under 0x4d093f, the menu's IDirectDrawSurface::BltFast(..., DDBLTFAST_WAIT)
  (fallback Blt DDBLT_WAIT), called via 0x460b38. The menu draws to the primary with many small blits, and
  dgVoodoo had `PrimarySurfaceBatchedUpdate = false` ("each change is instantly presented, debug-like mode"),
  so it presented after every blit: <1 fps menu (idle gfxcapture count 3 frames/5 s; menu overlay animates).
- Set `PrimarySurfaceBatchedUpdate = true`, restored stretched_ar + borderless,fullscreensize + SystemHookFlags=cursor
  (the slowness was independent of them). Tester: still slow.
- Re-sampled with batched update on, mouse moving: the menu's main thread is 100% idle in PeekMessage (0x4d9808), so
  the game is not the slow part. Conclusion: with the menu scaled, dgVoodoo emulates the cursor inside the image, and
  the menu only presents on changes, so the cursor itself moves at a low frame rate (and copies the busy shape).
- Switched to real fullscreen: `FullScreenMode = true`, `ScalingMode = unspecified`, no WindowedAttributes, no
  SystemHookFlags (kept PrimarySurfaceBatchedUpdate/FastVideoMemoryAccess = true). Menu = real 640x480 display mode
  with the normal Windows cursor; game switches to 1920x1080. Verified: modes switch correctly, 3 alt-tab rounds in
  the level fine, Quit -> exit 0x1, desktop back to 1920x1080. Previous conf: dgVoodoo.conf.scaled-menu.
- Tester: smooth, but wants the menu at 1920x1080 too. Final setting: `FullScreenMode = true`, `ScalingMode = stretched_ar`
  (no WindowedAttributes, no SystemHookFlags). Display stays 1920x1080 the whole time; menu scaled 4:3 with side bars.
  dgVoodoo emulates the cursor in fullscreen scaling too, but `mod\cursor_test.sh` (cursor moved 120x/s for 3 s,
  frames counted incl. cursor) gave 529 frames/4 s vs 261 for the windowed scaled setup. Captures show one normal
  arrow at the right mapped spot (GetCursorInfo reports app-space coords, e.g. clamped to 639,479), no second cursor.
  Gameplay 16:9 full screen, quit clean, desktop stays 1920x1080.
- Tester: still slow + duplicate cursor back (launches via the crash catcher .bat, i.e. plain D3D.exe; cursor stutters).
  Root cause found with a constant-redraw menu:
  - Patch 0x4d0a37 `jne` -> `jmp` (front end 0x4d0970: always take the full-redraw path that [0x658d68] normally
    gates), so the menu presents every loop pass and dgVoodoo's emulated cursor has frames to move on.
  - That exposed the real bottleneck: each menu widget BltFast (0x4ca9bb, DDBLTFAST_WAIT) blocked in a wait,
    ~1 refresh per blit, so a full menu redraw took ~170 ms (~6 fps). Not MSAA (same with Antialiasing off).
    `PresentationModel = auto` (behaves like discard): 5 fps; `seqflip`/`flip`: 240 fps (capture limit).
  - WRONG CONCLUSION, corrected below: `flip`/`seqflip` are not valid values, so dgVoodoo ignored the WHOLE conf and
    ran on defaults (fullscreen with real 640x480 mode switch, "all" resolutions -> list overflow, no 1920x1080 in
    Options). Tester reported exactly that. Valid PresentationModel values: auto, discard, seq, flip_discard, flip_seq.
    LESSON: a single invalid value silently disables dgVoodoo.conf; check with `mod\conf_check.sh` after every edit
    (display stays 1920x1080, 14 modes incl. 1920x1080).
  - With the conf actually read, every presentation model gave ~7 fps menu redraws. Bisecting against the stock conf:
    `PrimarySurfaceBatchedUpdate = true` (my earlier change) was the blocker. With it false: 954 frames/4 s.
- FINAL (2026-11-05): FullScreenMode=false, WindowedAttributes=borderless,fullscreensize, ScalingMode=stretched_ar,
  SystemHookFlags=cursor, PresentationModel=auto, PrimarySurfaceBatchedUpdate=false, FastVideoMemoryAccess=true,
  FPSLimit=0 + exe patch 0x4d0a37 (menu full redraw every pass). Checked: menu display 1920x1080, 14 modes incl.
  1920x1080, menu ~240 fps idle and with cursor moving (947 frames/4 s), gameplay 60 fps, clock x1.000, alt-tab x3,
  clean quit. Gameplay at 180 fps (seen on the default conf, monitor is 180 Hz) is the separate "above 60" task:
  clock was correct at 165 fps there too.
- Tester: mouse now smooth. Remaining: "loading" cursor on the first menu (gone after playing a level), black screen
  switching to gameplay.
  - Cursor: the game never sets a cursor before the first level, so dgVoodoo's emulated cursor keeps Windows'
    app-starting shape from launch. Patch: hook front-end loop entry 0x4d97e5 -> cave 0x51ef00:
    SetCursor(LoadCursorA(NULL, IDC_ARROW)), displaced `mov ebx,[PeekMessageA]`, jmp back. Can't see the drawn cursor
    in my captures (GetCursorInfo returns dgVoodoo's own handle), so this needs the tester's eyes.
  - Black screen: recorded the New Game switch at 8 fps (brightness per frame). The dark start is the story crawl's
    own backdrop; the only pure black was 3.75 s between the crawl's end and the first 3D frame. Crash-catcher log
    shows SwitchTo3D twice there. Cause: 0x4590d0 built the 3D device at the current mode [0x6b9dec] (menu 640x480),
    then 0x458dd0 -> 0x505550 saw game mode [0x65923c] != it and tore down + rebuilt (textures uploaded twice).
    Patch: hook 0x4590d0 -> cave 0x51ef1f: [0x6b9dec] = [0x65923c] before the build, so it builds once at the game
    mode and 0x505550 returns early. Trace build: one rebuild instead of rebuild/teardown/rebuild; pure black 1.62 s.
    Render mode 1920x1080; Esc/resume also builds once. View window A/B identical with/without the patch at the same
    frames (the opening tunnel animates FOV 111->100, y window +/-99 there in both).
  - The remaining ~1.6 s is the single device + texture build; removing it entirely would need the game to keep
    presenting during the load.
- Tools: `mod\conf_check.sh` (validates dgVoodoo.conf is really read), `mod\black_probe.sh`.
- Tester: busy cursor still there; wants the black gap gone entirely.
  - Cursor: monitor capture (gfxcapture monitor_idx=0, capture_cursor=1) shows the drawn cursor is a blue busy RING.
    `mod\api_trace.py` (int3 on SysWOW64 user32 SetCursor/LoadCursorA/W): the game never calls SetCursor before
    a level, no IDC_WAIT anywhere. Not the startup-feedback cursor (STARTF_FORCEOFFFEEDBACK: same ring), not hung
    (IsHungAppWindow false). With SystemHookFlags=cursor the real cursor is dgVoodoo's blank one and the ring is
    dgVoodoo's drawn copy; SetCursor + ShowCursor toggles at menu entry don't refresh it. With the hook OFF (and the
    menu now redrawing every pass) captures show ONE normal arrow that follows the mouse. Fix: SystemHookFlags empty.
    Removed the menu-entry cursor patch and the sound-init restore patch (neither helped).
  - Black gap: `mod\gap_sample.py` (1 ms memory poll, samples from 3D-up until the frame counter moves): 1687 ms,
    mostly in win32u under 0x458f30 (2D DDTerm: SetCooperativeLevel(hwnd, NORMAL) on the menu DD object, then the 3D
    side takes exclusive again). Skipping that call crashes (3D can't get exclusive). dgVoodoo
    `AppControlledScreenMode = false`: gap 109 ms, pure black 0.12 s (one frame at 8 fps). But then the window stayed
    640x480 in gameplay (the 2D shutdown restores the original window size). Fix in the enter-3D cave (0x51ef00):
    after the single build, MoveWindow(hwnd, 0, 0, GetSystemMetrics(SM_CXSCREEN/CYSCREEN), TRUE).
  - Verified: menu window 1920x1080, gameplay window 1920x1080, alt-tab, Esc/pause (1920x1080), resume, quit clean.
    Side effect: gameplay now runs at the monitor's 180 Hz (180 fps); game clock x1.000. Physics feel not checked.
- REVERTED (tester: mouse unusable, cursor translucent and flickering): both changes above were wrong.
  `mod\mouse_test.sh` (real SendInput absolute moves; first version had a 48-byte INPUT struct, so SendInput failed;
  correct size on x64 is 40) + monitor capture:
  - With SystemHookFlags=cursor and AppControlledScreenMode=true the physical cursor is clipped to a 640x480 box (the
    game's coordinate space) and dgVoodoo draws the mapped cursor on the scaled menu: hover works (options text
    brightness 150 vs 101 away). This is the setup the tester had working.
  - Hook off: the real cursor is visible but stuck in that 640x480 box, plus dgVoodoo's drawn one -> tester's
    translucent/flickering cursor, mouse unusable. My earlier SetCursorPos tests could not show this.
  - AppControlledScreenMode=false: dgVoodoo draws the cursor where you point but the game reads the unmapped
    position; options never highlight. So the 0.1 s black-gap result is unusable; MoveWindow patch removed.
- Busy-ring cursor (first menu only, gone after a level; reproduced: arrow after Esc from a level) NOT fixed.
  Tried and removed: SetCursor(arrow) at menu entry and on every pass, ShowCursor toggles and a one-time
  ShowCursor(TRUE), IDC_ARROW in the sound-init wait cursor (0x459bef). AttachThreadInput+GetCursor shows the game
  thread holds a dgVoodoo handle (the hook substitutes its own). Best theory: dgVoodoo captures the system cursor when
  it starts (Windows' app-starting cursor; only its coloured ring survives) and re-reads only when 3D is created.
- CURRENT: dgVoodoo.conf as in the earlier FINAL but SystemHookFlags=cursor, AppControlledScreenMode=true (copy:
  dgVoodoo.conf.current). Exe: compat fixes, DrawPrim box, menu full redraw (0x4d0a37), single 3D build (0x4590d0),
  DirectInput non-fatal, 16:9. Black gap 1.6 s, gameplay 60 fps. Hover verified with real input.
- Tools: `mod\menu_rate.sh` (menu redraw rate, needs the redraw patch), `mod\cursor_test.sh`, `mod\sample.py`
  (now names modules), `mod\clock_check.py`. Conf snapshot: dgVoodoo.conf.current.
- HUD scale: NOT done. HUD art is 640x480-era bitmaps (media\dibs\Hud, 32x32 icons; HudLoRes for <640 modes, chosen
  by [0x5c7734] at 0x45a0f6) drawn 1:1 in screen pixels as XYZRHW quads (FVF 0x1c4, XLR8 2D code ~0x509100-0x509900),
  positioned from the screen size. Scaling needs a virtual HUD layout + vertex scale in the 2D path: a few hours of RE.

## Wrapper switch: dgVoodoo -> DDrawCompat v0.7.2 (2026-11-05, tester asked to try a different wrapper)
- Downloaded (tester OK) DDrawCompat-v0.7.2.zip, 1,080,531 bytes, sha256 a932a4dc...a397b39, from
  github.com/narzoul/DDrawCompat releases -> downloads\ddrawcompat\x\ddraw.dll (x86, FileVersion v0.7.2).
- Game folder: dgVoodoo ddraw.dll + D3DImm.dll moved to parked-dgvoodoo\ (dgVoodoo.conf/dgVoodooCpl left, unused).
  DDrawCompat's ddraw.dll installed (loaded via the exe's ".\ddraw.dll" patch; it uses the system DirectDraw).
- Config: game folder DDrawCompat-D3D.ini (log: DDrawCompat-D3D.log next to it lists the final config):
  SupportedResolutions = 640x480 ... 3840x2160 (no "native": that floods the game's mode list again, 116 entries,
  no 1920x1080), SupportedRefreshRates = 60, Antialiasing = msaa4x. Defaults kept: DisplayResolution=desktop
  (no mode switches), DisplayAspectRatio=app (4:3 menu pillarboxed), FullscreenMode=borderless.
- Verified (real SendInput mouse, monitor captures): display stays 1920x1080, 10 modes incl. 1920x1080, menu 60 fps,
  first-menu cursor is a normal ARROW drawn over the right item, hover highlights (150 vs 102). Like dgVoodoo, the
  physical cursor lives in the game's 640x480 space (game ClipCursor, 13 call sites) and is shown scaled.
  New game: level at full 16:9 1920x1080, 60 fps, clock x1.000, alt-tab x2 fine, quit clean. Black before the
  level ~1.75 s (same as dgVoodoo's 1.6 s). DDrawCompat log: no errors.
- Visual comparison (`mod\cmp_capture.sh <label>`: New Game, full-res captures at 5 s / 15 s of game clock into the
  cutscene and 3 s into the level; images compare_3d.png, zoom_wall.png, zoom_hud_left.png, menu_filters.png):
  - DDrawCompat with TextureFilter=app is blurrier on angled textures; TextureFilter = af16x matches dgVoodoo.
  - dgVoodoo drew the HUD ~1.5x larger (bilinear, colour fringes); DDrawCompat draws it 1:1 (crisp, small).
  - Menu: DisplayFilter bilinear (default) is soft; point sharpest but uneven (2.25x scale); lanczos/spline sharper
    with clean edges; bicubic ~ bilinear. Set DisplayFilter = lanczos (tester confirmed 2026-11-06).
- Decision: DDrawCompat is the wrapper (tester preferred its menu; 3D matches dgVoodoo with af16x).
- DDrawCompat-D3D.ini now: SupportedResolutions list, SupportedRefreshRates = 60, Antialiasing = msaa4x,
  TextureFilter = af16x, DisplayFilter = lanczos.
- Switch back: copy parked-dgvoodoo\*.dll into the game folder (dgVoodoo.conf.current is the last good conf).

## HUD scale (2026-11-06)
- Path: HUD object 0x45c2b0 ([0x5c7f3c]) draws widget panels via vtable +0xc; in 3D every widget is drawn by
  0x4ca901 -> 0x508aa0 (ecx = src rect, edx = dst rect, int l,t,r,b), which builds an XYZRHW quad (FVF 0x1c4) and
  DrawPrimitive. (In 2D menus the same widgets use BltFast at 0x4ca9bb.)
- Patch (`patch_d3d.py --hud H`): hook 0x508aa0 -> cave 0x51ea00. S = screen height / H (min 1). Per axis: element
  in the first third scales from that edge, last third from the far edge, middle around the centre; elements larger
  than half the screen untouched. Scaled rect written to 0x6bf3c0 and passed on in edx. Source rect unchanged.
- `mod\test_hud.py`: runs the generated x86 in a capstone-driven interpreter vs a Python model of the rule:
  1525 rects at 640x480..3840x2160 match. 1920x1080: (10,1000,70,1070) -> (22,901,157,1058).
- Installed with --hud 480 (2.25x at 1080p). Not yet seen in game (tester was at the PC); widget hit-testing (if any
  in-game) is not scaled.
- Tester: 2.25x may be too big -> rebuilt with --hud 720 (1.5x at 1080p, about what dgVoodoo showed).
  Tester confirmed 1.5x in game (2026-11-06).
- Build now: `py mod\patch_d3d.py "...\D3D.exe" --aspect 16:9 --hud 720` (600 = 1.8x, 480 = 2.25x, 0 = off).

## Above 60 fps (2026-11-06)
- With DDrawCompat the game's frame rate = the refresh rate of its (emulated) modes: SupportedRefreshRates.
  Monitor is 180 Hz. Old ini copy: DDrawCompat-D3D.ini.60hz.
- First 180 Hz run crashed 20 s into the cutscene at D3D.exe+0xBAE9D (the early dgVoodoo crash site). Dump
  dumps\D3D-20261106-025357.dmp: renderer visibility pass 0x4bac80, second loop unlinks entry esi from singly linked
  list [edi+4] by searching for its predecessor; the recursive check 0x4baef0 had already moved the saved next entry
  (0x648a18 was in none of [edi+4]/[edi+8]/[edi+0xc]), so the search ran off the end: read [0+4]. Fix in PATCHES:
  0x4bae94 search rewritten in place with an end-of-list check that skips to the next entry (0x4baed2).
  Afterwards a full 180 fps cutscene (5847 frames) and level ran fine.
- Physics (`mod\physics.py`; player object [0x6ac5e0]: +0x60 = height, +0x5c/+0x64/+0x68 position; found with
  `mod\player_probe.py` snapshots): walk = horizontal speed between 0.8 and 2.3 s of holding W/S; jump = Space,
  sampled every 2 ms. 3 runs each, game clock x1.000 at every rate:
    60 fps: walk 34.1-35.0 u/s, jump rise 5.5, airtime 0.547 s
   120 fps: walk 34.0-35.0 u/s, jump rise 5.3-5.4, airtime 0.540 s
   180 fps: walk 32.2-34.3 u/s, jump rise 4.7-4.8, airtime 0.49-0.50 s  (jumps ~14% lower: could break jumps)
- Set SupportedRefreshRates = 120. 120 on a 180 Hz screen alternates 1 and 2 refreshes per frame unless the
  monitor's VRR (G-Sync) is on; 90 would divide 180 evenly (not measured).

## Launcher (2026-11-06): `Requiem Launcher.pyw` in the game folder
- In-game frame-rate option would mean adding a front-end menu item: not done. Resolution in the game's Options
  still works, but the 16:9 view is built into the exe, so the launcher sets both together.
- Launcher (tkinter, double-click; .pyw -> pyw.exe for this tester): Resolution (800x600 ... 3840x2160 incl. 4:3,
  16:9, 21:9; bigger than the desktop = downscaled), Frame rate (the monitor's rates at desktop res: 60, 120
  recommended, 144, 165, 180 + Unlimited), HUD size (off / 1.5x / 1.8x / 2.25x at 1080p), Skip intro videos.
  Play: rewrites SupportedResolutions / SupportedRefreshRates / VSync in DDrawCompat-D3D.ini (other lines kept),
  patch_d3d.build(exe, W:H, hud) from D3D.exe.orig, writes the mode index into Gamers\latest.cfg, saves choices in
  'Requiem Launcher.json', starts D3D.exe. Refuses if the game is running.
- latest.cfg format (loader 0x4d4670): u32 n, skip n bytes, then u32 [0x659110], u32 [0x659154], u32 mode index
  [0x65923c] at offset 4+n+8. The index is into the game's list = SupportedResolutions sorted by height then width
  (verified: 1920x1080 -> 6 and 2560x1080 -> 7 render at those sizes).
- patch_d3d.py: main() now calls build(exe, aspect, hud, trace) (same CLI).
- Unlimited = SupportedRefreshRates desktop + VSync = off: ~1000 fps (game's 1 ms timer), clock x1.000, cutscene
  fine, jump 5.2 (vs 5.5 at 60), i.e. ~5% lower. Labelled with measured numbers; 144/165 not measured.
- Added Anti-aliasing choice (Off / msaa2x / msaa4x default / msaa8x): rewrites the Antialiasing line; each value
  checked in DDrawCompat's log (msaa2x(7), msaa4x(7), msaa8x(7), off), no errors.
- Added Texture filtering (app / bilinear / trilinear / af4x / af8x / af16x default) and Menu sharpness
  (DisplayFilter point / bilinear / bicubic / lanczos default / spline). All values checked in the log, no errors.
  Launcher table GRAPHICS maps each to its ini key; choices saved as aa / tex / menu in 'Requiem Launcher.json'.
- Note: my tests overwrite the ini; afterwards re-apply the tester's saved json (done 2026-11-06: 1920x1080,
  unlimited, HUD 720, nomovies, msaa4x, af16x, lanczos).
- Verified: GUI defaults (desktop res, 120, HUD 1.5x), Play wrote ini/json/latest.cfg and started the game;
  21:9 test letterboxed correctly on the 16:9 screen. Final state restored to 1920x1080 / 120 / HUD 1.5x.

## Requiem Modern 1.0.0: installer + launcher exe (2026-11-06)
- Rule (tester): every modern change also goes into this launcher (install step and/or option + About list).
- Source: launcher\requiem_modern.py (+ mod\patch_d3d.py). Build: launcher\build.bat (PyInstaller 6.22.3, one-file,
  windowed, bundles DDrawCompat ddraw.dll) -> launcher\dist\Requiem Modern.exe (~21 MB); copy in the game folder.
- Design after the King Kong PC port launcher (tester's reference): main menu over game art with logo top-left, gold
  accent, status cells, key hints; Settings with tabs (Q/E), grouped rows with < value > and dots, right info panel
  (description, every value with a note, tags, default), About = change list. Uses the game's own art (Splash01 title
  art at 1.25x faded over a blurred fill; Splash06 for settings) and font (media\fonts\SMASH.TTF, family "Smash",
  loaded with AddFontResourceExW FR_PRIVATE), read from the game folder at run time: no game files in the exe.
- First run: game folder from the registry (HKLM\SOFTWARE\WOW6432Node\3DO\Requiem AppPath), confirm or browse.
  check_folder: D3D.exe (or .orig) must be GOG v1.2 sha256 f472aa5f...; installed = ddraw.dll is DDrawCompat +
  .orig + ini. Install: D3D.exe.orig, ddraw.dll/D3DImm.dll (if not DDrawCompat) -> 'Modern Backup', DDrawCompat in,
  dgVoodoo D3DImm removed, settings applied. Restore: everything back, .orig/ini/log/backup removed.
  Settings: %APPDATA%\Requiem Modern\launcher.json (REQUIEM_MODERN_CONF overrides, for tests). First confirm of a
  folder imports 'Requiem Launcher.json' from the old .pyw (moved to old-launcher\).
- Main-menu items have a one-line description (tester asked what Repair means). Play hides the launcher window before
  starting D3D.exe so the game owns the foreground.
- Tested on a clean copy (testgame\, from the pristine zip): Install (hashes: DDrawCompat in, GOG ddraw in backup,
  GOG exe as .orig), Settings tabs, Restore (D3D.exe and ddraw.dll back to GOG hashes, extras removed), Play (game in
  front, no ATTENTION box, DDrawCompat log clean). testgame is left restored (clean).
- Tester's real folder: the tester ran the test launcher on it themselves (install + play). Its Modern Backup was empty
  (ddraw.dll was already DDrawCompat), so GOG's original ddraw.dll (lab orig\, hash 70004195...) was put there.

## DirectInput setup acquire (2026-11-06, tester saw "DirectInput could not acquire keyboard")
- Input setup 0x45d859 (keyboard) / 0x45d908 (mouse): SetCooperativeLevel FOREGROUND|NONEXCLUSIVE then Acquire; failure
  -> error box 0x491980 + exit. Happens when the game window is not in front at that moment (launcher window still
  had focus). Patches: 0x45d88f / 0x45d93e je -> jmp (not fatal). The poll only re-acquired on DIERR_INPUTLOST
  (0x8007001e), so a never-acquired device would stay dead: 0x45dd82 (mouse, jne rel32) and 0x45ddd0 (keyboard, jne
  rel8) nopped, so any GetDeviceState failure goes through the 16-try re-acquire loop. In PATCHES and the About list.
  Tester confirmed in game via Requiem Modern.exe: "Works fine" (2026-11-06).

## Audio (2026-11-06, Requiem Modern 1.1.0)
- Assets: music MUSIC\Track02-06.ogg already 44.1 kHz / 256 kbps (GOG WINMM.DLL). SFX: 1,096 MP3 22 kHz mono 32 kbps,
  148 at 64 kbps; WAVs mostly 22/11 kHz, many 8-bit. AI upscaling of SFX deferred (sample first).
- Miles mixer: game calls AIL_quick_startup(1,0,0,0,2) at 0x4eaf05 (rate/bits 0 = Miles' low default). Cave 0x51ef40
  pushes 2,16,44100,0,1 and jumps back to the call at 0x4eaf0f. In PATCHES.
- 3D provider: 0x4eb0ce enumerates Miles providers and maps names to 1 EAX / 2 A3D / 3 DS3D hw / 4 DS3D sw (bitmask
  [ebx+0x2c]); opens at 0x4eafac / 0x4eb33c; "EAX environment selection" preference at 0x4ec59a. readme: EAX is used
  automatically when detected. Game ships MSSEAX.M3D, so no exe patch is needed for EAX, only a dsound that has EAX.
- DSOAL r697 (LGPL-2.1, OpenAL Soft inside), downloaded with permission to downloads\dsoal. dsound.dll (fd2e9ae6...) +
  dsoal-aldrv.dll (741a040e...) next to D3D.exe. HRTF mode = alsoft.ini `[general] channels=stereo,
  stereo-mode=headphones, stereo-encoding=hrtf` (the stock alsoft.ini is all comments).
- Launcher: Audio tab, "3D audio" = EAX (speakers, default) / Headphones (EAX + HRTF) / Original (no DSOAL). set_audio()
  copies or removes only our hash-matched files plus the licence/version txts; install backs up foreign
  dsound/dsoal/alsoft files to Modern Backup; restore removes ours. Tested on testgame: every mode, install, repair,
  restore. build.bat bundles launcher\dsoal via --add-data. Test script: mod\audio_test.sh (logs to audio-logs\).
- In-game check on testgame (DSOAL_LOGLEVEL=3): game loads the folder's dsound.dll; OpenAL Soft opens the default
  device and reports EAX5.0 + EFX; Miles' primary buffer is now 44100 Hz / 16-bit / stereo (patch confirmed); second
  device open has DSBCAPS_CTRL3D primary + QuerySupport(DSPROPSETID_EAX10_ListenerProperties) = MSSEAX.M3D taking EAX,
  no fallback provider probes after it; OpenAL allocates effect slots. Reverb inside a level not heard/logged yet
  (menu has no 3D sounds) - tester to listen.
- Automation notes: the copyright screen after `nomovies` waits for a click (not a hang); SendInput relative mouse moves
  did not move the menu cursor (left for later). New helpers: mod\click.py, mod\rclick.py.
- Requiem Modern 1.1.0 exe copied to the game folder 2026-11-06. DSOAL lands in the folder on the next Play.
- Tester played a level with EAX on: sounds right (2026-11-06). Audio step done.

## Frame rate vs enemies (2026-11-06, Requiem Modern 1.2.0, tester asked whether the frame rate affects the enemies)
- Tick 0x448450: raw = timeGetTime delta capped 100 ms ([0x5404e4]); 0x4c6bd0 scales it (flag 0x1000000 = slow motion
  dt>>2; flag [0x5c6e11]&8 = dt * speed byte [0x64ef98] via float + ftol, not touched) -> dt [0x5404e8] (int ms);
  clock [0x5404f4] += dt. dt has 221 users: timers (sub/cmp), float scaling, args - all exact at any rate.
- No per-frame gameplay on the frame counter [0x531fd8] (only once-per-frame stamps, render cache, stats ring
  0x492b5d). No inc-and-compare frame-count timers on objects. rand (0x50e7cb, 52 callers) picks animations/angles/
  particles, no per-frame chance rolls. AI is native (entities.txt strat fields are not parsed by D3D.exe).
- Rounding sites (mod\dt_taint.py traces dt through registers): 0x472735 [+0x18] -= dt>>1 and 0x49efa3 [+0xda] +=
  dt>>1 (character animation, shared method 0x49ef80 in 6+ vtables, states 0x16/0x20-0x22); 0x473b25 area damage
  vcall +0x28(dt>>2, ..., type 5) to visible actors (~250 HP/s); 0x4c6be1 slow motion dt>>2.
  Loss vs exact: 60 fps (dt 16/17) and 120 fps (dt 8/9) both 4% - identical; 180 fps (5/6) 10% / 28%; ~1000+ fps
  (dt 0/1) everything 0 = stalls (no area damage, animation timers frozen, game frozen in slow motion).
- Animation ticks via 0x499ac0 (+0xd6 += dt*k, returns 3 per 300) carry remainders: fps-independent at >= 60 fps.
- Fix (PATCHES "frame time"): tick hook 0x4484b3 -> cave 0x51ef60 computes dt/2, dt/4 with carried remainders
  into .data 0x6bf3a0 (half) / 0x6bf3a4 (quarter) / 0x6bf3a8, 0x6bf3ac (rems); the three sites read them. Slow
  motion: hook 0x4c6bdb -> cave 0x51efad with its own remainder 0x6bf3b0. Verified live at ~3200 fps: half=1 every
  2nd 1-ms frame, quarter every 4th (was always 0); clock x1.000; 365k samples consistent apart from torn reads.
- Not changed: jump/fall arcs (Euler integration, ~3% lower at 120, measured earlier), the speed-byte path.
- Tools: mod\xref.py (absolute-address xrefs), mod\disasm.py, mod\dt_taint.py, mod\objs.py, mod\actorscan.py
  (actor-shaped objects near the player; position = +0x5c x, +0x60 height, +0x64 y), mod\enemy_test.py,
  mod\gshot.sh (gfxcapture frame grab; PrintWindow returns stale frames), mod\click.py/rclick.py.
- Menu automation: under DDrawCompat the cursor is clipped to 640x480 menu coordinates; `um win drive --proc D3D
  "click X Y"` with X,Y in 640x480 works (title 320 240, single player 427 107, load game 249 244, pray 418 307).
  Test copy keys are the defaults (Up arrow = forward). Test copy has a save copied in.
- Requiem Modern 1.2.0 copied to the game folder; the fix lands in D3D.exe on the next Play.

## Per-frame drag (2026-11-06, Requiem Modern 1.2.1; tester: the first enemy lunged more at 60 fps than at 120)
- Cause: velocities integrate with dt but then get v *= C every frame (fld [x]; fmul [C]; fstp [x]), so at 120 fps
  they decay twice as fast per second: a leap travels about half as far. Lunge site 0x47f82d (method 0x47f220,
  vtable slot 0x521ad4): vy -= dt*g, then vx (+0x88), vz (+0x90) *= 0.95.
- All such sites in dt-using per-frame updates (scan for fld/fmul const in (0.3,1)/fstp on the same field):
  0.95 [0x527188]: 0x47f85b 0x47f86d (leap), 0x468b50/62/74 (actor +0xf0.. in state 16, called from 0x47f220);
  0.9 [0x51f67c]: 0x482de4/df6/e08 (actor velocity, vtables 0x521ea4 0x522108), 0x46a00f/21/33 (+0x208..);
  0.97 [0x520a7c]: 0x45eeb2 0x45eebe 0x45eee6 (debris); 0.65 [0x51f43c]: 0x43ffd8/e4/f0 (particles);
  0.972 [0x520618]: 0x46bb7a 0x46bd42; 0.98 [0x5290bc]: 0x4c29f9 0x4c2a05 0x4c2a11; 0.74 [0x5283dc]: 0x4b771e
  0x4b7730 (player physics). Not touched: 0x4ab8bf/0x4b7789 (0.6 on a velocity set fresh each frame), 0x4747a5,
  0x4be61c, 0x4b86ce (functions that do not read dt).
- Fix: the tick cave continues to cave 0x51e840 which computes F_k = C_k^(dt/16.667) (r_k = C_k^0.06 doubles at
  0x51e940, multiplied dt times) into .data 0x6bf3d0+4k; each listed fmul now reads F_k (same instruction length).
  At 60 fps F = C, so 60 fps behaves as before. Verified live (mod\drag_check.py): all 7 factors equal C^(dt/16.667)
  at 60 fps (dt 16-18) and 120 fps (dt 7-10); per second 0.95 decays to 0.046 at both rates.
- Not verified on the creature itself: could not locate the cf object (its class does not keep position at +0x5c);
  tester to compare the lunge at 60 and 120 fps.
- Tester (1.2.1): still different. Testing halted at the tester's request. Notes for the next step: 0x47f220,
  0x482d70 sit in one big vtable starting 0x520a80 (slots 1045 / 1289 / 1442) and get a sub-object: actor = this-0x68
  (state at this+0x180 = actor+0x1e8), so the leap velocity this+0x88..0x90 = actor+0xf0..0xf8 (the same vector
  0x468810 damps in state 16). Next: a debug build that stores `this` at 0x47f220/0x482d70 entry to find the creature,
  then log its state changes and velocity at 60 vs 120 fps - "lunges more" may be how OFTEN, not how far.

## Remaining Phase 1
- Widescreen: done (own patch, no third-party FOV fixer needed). FPS: done (61, correct speed).
- Crash: fixed (DrawPrim debug box, see above). Tester confirmed no crashes in their own play (2026-11-05).
- Installed D3D.exe rebuilt WITHOUT --trace (2026-11-05): `py mod\patch_d3d.py "...\D3D.exe" --aspect 16:9`.
  36 bytes differ from D3D.exe.orig in 9 places (3 compat fixes, DrawPrim box, 4 view-window floats); smoke-launched OK.
- Phase 1 complete: runs on Windows 11, any resolution incl. 1080p, correct 16:9 FOV, steady 61 fps, crash fixed.
- Leftover: delete `D3D.exe.stuck` from the game folder after a reboot (zombie process from the 11:27 crash).

## First creature lunges less at 120 fps - ROOT CAUSE FOUND, not fixed yet (2026-11-06)
- Creature = sector-list entity type 93, vtable 0x5255e4 (find via mod\cf_log.py creatures()). Think 0x47c440 ->
  attack/decide fn 0x47ab70: runs ONLY if on-ground bit (+0x78 & 1). Decide (d^2): <100 attack 0x19, <529 pounce
  0x18, <784 0xb, else 1/30 0xb or run 0x15 (table rand 0x56f6e0). Pounce takeoff checked by anim-cursor crossing
  (+0x210 prev / +0x214 cur vs anim+0x1c) inside 0x47ab70, i.e. only on grounded frames -> missed takeoffs.
  Contact damage: Hit(1, type 0x22) every grounded frame (player vtable +0x28 = 0x4b94d0, converts via 0x499ac0).
- Measured (mod\ground_watch.py): on-ground pattern 0101 at 60 fps (50% of frames), 001 at 120 (33%).
  Damage accumulator 472/s at 60 vs 322/s at 120 (mod\acc_watch.py); hits every 0.6 s vs 1.17 s.
- Mechanism: physics step 0x47ca20 (velocity drag time-correct, gravity) -> collision 0x47c490 -> move 0x42ad40,
  which CLEARS ground bit at start (0x42ad9c) and sets it only if the move penetrates the floor (0x42b0fe, also vy=0).
  After landing vy=0, so the next move does not reach the floor -> bit cleared; at 60 fps one frame of gravity
  (~0.017) reaches the floor again, at 120 (~0.004) it takes two frames.
- Fix idea (next): make the first airborne frame after resting reach the floor at any fps (e.g. minimum downward
  probe of the 60 fps drop when vy == 0 / bit 2 "was on ground" set, in 0x47ca20 before 0x47c490), giving 0101 at
  all rates = 60 fps behaviour. Verify with ground_watch.py / acc_watch.py / cf_log.py at 60 and 120.
- Test copy D3D.exe currently has DEBUG hooks (mod\debug_hooks.py, Hit tracer + 0x499ac0); rebuild with
  patch_d3d.py before other tests. Tools: engage.sh (load save + face creature), cf_log.py (keeps player alive,
  test copy only), trace_read.py, dmg_read.py, cf_anim.py, cf_fields.py.
- The 1.2.1 per-frame drag fix stays (correct, harmless) but did not affect this creature.

## Ground flicker FIXED (2026-11-06, Requiem Modern 1.3.0)
- Patch "ground" (patch_d3d.py): hook Move 0x42ad40 entry -> cave 0x51e978. (1) If the actor was airborne and has
  only just started falling from rest (0 > vy > -0.002 u/ms), lower its target 0.015 so it lands on that frame
  (60 fps on/off pattern at any rate). (2) On dt = 0 frames (>1000 fps) Move runs via a wrapper that restores a
  grounded actor's bit afterwards. Trampoline 0x51e9e7 (moved prologue), probe constant 0x51e9f5.
- Verified on the first creature (type 93) with mod\ground_watch.py / acc_watch.py / cf_log.py:
    60 fps: grounded 50% of frames, damage accumulator 474/s, bites every 0.60 s (unchanged)
   120 fps: 33% -> 50%, 322/s -> 485-522/s, bites 1.17 s -> 0.61 s, pounce-to-landing 3 s -> 0.61 s
   ~1800 fps: 23% -> 48%, 288/s -> 496/s
  Pounce counts over repeated 25 s runs now show the same mix at 60 and 120 (1 or 2 pounces, chance).
- Not checked: player physics/jump with this patch (player is not seen using Move in traces; a falling player gets
  at most a one-off 0.015 lower target), other enemy types (they share Move, so they get the same fix).
- Requiem Modern 1.3.0 copied to the game folder; the patch lands in D3D.exe on the next Play.

## Black screen at level start FIXED (2026-11-06, Requiem Modern 1.3.1)
- Tester: menu fine, level black. Game and DDrawCompat both rendered normally (window and monitor capture showed the level,
  logs identical to good runs), so the picture was lost at the display. The tester's main monitor runs 1920x1080 @ 180 Hz;
  `SupportedRefreshRates = 120` with `DisplayRefreshRate = app` made DDrawCompat switch it to 120 Hz on entering 3D
  (measured 180 -> 120 -> 180), and the monitor shows black at that mode. 4x AA at 120 Hz: still black (not the 8x AA).
- Fix (launcher write_ini): always `DisplayRefreshRate = desktop`; when the chosen fps is not the desktop rate,
  `VSync = off` + `FpsLimiter = flipend(N)` (borderless, so DWM composes: no tearing). The game still sees N Hz.
  Verified on the tester's folder: monitor stays 180 Hz, game counter 121 (as before), DDrawCompat accepted all three keys,
  tester confirmed.
- Test copy: engage.sh now writes its ini with the launcher's write_ini, so test runs keep the monitor rate too.

## Lunges at 120 still fewer -> crouch ground flicker (2026-11-06, Requiem Modern 1.3.2)
- Tester after 1.3.1: lunges still differ. Recorded the tester's own play read-only (`mod\play_log.py`, analysis
  `mod\play_read.py`, logs enemy-logs\play-60-205436.json / play-120-205557.json):
  pounce decisions per engaged minute equal (0x18 24.5 vs 23.6) but physical leaps 80/min at 60 vs 33/min at 120.
  At 60 one 0x18 entry chains 2-6 leaps; at 120 the creature crouches up to 3 s without leaving the ground.
- Cause: after a grounded frame, a resting creature is grounded again on 95-98% of frames at 60 (0xb, 0x15, 0x18) but
  only 6-14% at 120 (on/off pattern). The take-off check (cursor crossing anim+0x1c in 0x47ab70) runs only on
  grounded frames, so at 120 half the take-offs were missed. The 1.3.0 probe only covered actors that were airborne
  on entry. (Bite 0x19 alternates at both rates, 13% vs 8%; my earlier "0101 at 60" came from standing-still tests,
  where the creature was biting.)
- Fix: ground probe also applies to an actor grounded last frame when dt < 16 ms; 60 fps and slower unchanged.
  Ground cave moved to 0x51EE00 (old spot 0x51E978 had 7 bytes left); HUD cave limit now 0x51EE00.
- Automated tests of this were unreliable (creature wakes only after 26-33 s of player movement; the game pauses
  without focus). `mod\chase.sh` / `leap_test.py` kept for reference; real verification is the tester's play + play_log.
- VERIFIED in the tester's own play with 1.3.2 (play-120-210036, play-60-210131, play-120-210220; game rate 118.5 /
  59.2 / 117.8 fps): leaps per engaged minute 83 and 88 at 120 vs 97 at 60 (and 82 at 60 before; was 33 at 120 in
  1.3.1). Grounded after a grounded frame in crouch/leap/run states at 120: 0xb 100%, 0x18 99-100%, 0x15 90%
  (was 6-14%), matching 60's 95-100%. Short sessions (4-10 s engaged): direction clear, exact rates noisy.

## Long-range leap chance per second (2026-11-06, Requiem Modern 1.3.3)
- First creature's decision 0x47ab70, d^2 >= 784: int(rand*30) == 5 -> leap 0xb, else run 0x15. Run sets busy only on
  entry, so after the first stride it rolls on every grounded frame: with 1.3.2 grounded ~100% at both rates, that
  is 60 rolls/s at 60 vs 120 at 120. Patch (cave after the ground cave, 0x51EE90): leap if rand*500 < dt ms
  (= 1/30 per 60 fps frame, same per second at any rate; never on dt = 0 frames).
- Other creature routine 0x47b380 (think 0x47c440, vtable slot 0x522f64): its rolls pick between attack states
  (8-11 units: 1/2 bite 0x19 or 0xd; 11-30: 1/5 run, 1/5 0x12, 3/5 pounce 0x18) and re-pick almost at once at any
  rate, so left alone.
- play_log.py now records every nearby entity with an AI state (type +0x20, hp +0x18 added) for other-enemy checks.
- Checked in the tester's play with 1.3.3 (play-60-211326 / play-120-211047, 61 / 121 fps, `mod\type_read.py`):
  two fighting types. Type 93 (first creature, 9 seen): leaps per engaged minute 57.8 at 60 vs 61.3 at 120;
  type 120 (4 seen): 31.9 vs 25.3 (11 vs 12 leaps, within noise). "Stays grounded after a grounded frame" now
  matches per state for both (run/leap/pounce 97-100% at both rates; knock-back 0x16 and type 93's bite 0x19 are
  airborne at both). Types 132, 73, 151 never left idle state 0x10 (not fighters).

## Jump re-measured after the frame-time fixes (2026-11-06, Requiem Modern 1.3.4)
- `mod\jump_run.sh 60 120 180 unlimited` (test copy, launcher ini writer, physics.py 3 jumps each):
    60: rise 5.5, airtime 0.545-0.548 s | 120: 5.3-5.4, 0.530-0.537 | 180: 5.3, 0.530-0.532 | Unlimited (~3000 fps): 5.2, 0.519-0.522
  The old "180 = 14% lower" was the dt rounding fixed in 1.2.0. What remains is a smooth trend from per-frame
  integration (explicit-Euler-like: apex = true + v0*dt/2, so 60 fps is ~5% above the dt->0 arc).
- Not fixed: gravity is spread over the tick's per-object step 0x4015a0 (g [0x531548] * scale [0x531540] * dt), the
  shared character physics 0x49e950 (vtable +0x180, y += vy*dt into 0x429c40 / 0x42ad40) and anim-driven takeoffs
  (0x49e2b3: vy = dy/T + 6e-5*T). Matching 60 exactly would mean a per-step bias a*(16.67-dt)/2*dt while airborne;
  judged not worth it for 3-4%. Launcher descriptions now give the measured numbers.
- Note: play_log.py also records test-copy runs (it watches any D3D.exe); delete those logs after test runs.

## Black pause before a level, re-profiled under DDrawCompat (2026-11-06) - NOT shortened
- `mod\gap2.py` (call-validated return addresses, 5 ms samples from the Load click to the first 3D frame) and
  `mod\gap3.py` (also names system-DLL frames), Load Game on the test copy at 120 fps. 3D-up to first frame ~1.3 s:
    ~450 ms  2D DDTerm 0x458f30: SetCooperativeLevel(hwnd, NORMAL) at 0x458f5b (DDrawCompat: EnumWindows +
             SendNotifyMessage to every window, nested WndProc 0x4597c0 -> DefWindowProc)
    ~100 ms  3D SetCooperativeLevel exclusive (0x50c45d)
    ~350 ms  SetDisplayMode 1920x1080 at 0x50d0cf (DDrawCompat: display-settings enumeration + broadcast via
             SendMessageTimeout), real display untouched (stays 180 Hz)
    ~220 ms  surfaces/device (0x50d1d2, 0x50cc8b, 0x50ce4e); ~150 ms first textures/level setup.
  Load from the click to 3D-up is ~0.6 s with the menu still on screen.
- Tried: skipping the 2D NORMAL call (xor eax,eax at 0x458f57) -> crash after 3D-up (3D cannot take exclusive),
  same as under dgVoodoo. DDrawCompat FullscreenMode = exclusive: identical timings. The ~0.9 s of mode-switch work
  is inside DDrawCompat and scales with the windows open on the desktop; shortening it would need a modified
  DDrawCompat build. Left as is (tester asked to try again; reported).

## Display mode option (2026-11-06, Requiem Modern 1.4.0)
- Launcher Display tab: Display mode = Borderless (default) / Fullscreen -> DDrawCompat `FullscreenMode` borderless /
  exclusive. Exclusive tested on the test copy: 121 fps at 120, monitor stays 180 Hz (screen capture is black in
  exclusive mode, as expected; picture not yet seen by the tester).
- Windowed: not available. DDrawCompat 0.7.2 (latest) has no forced windowed mode. The game's own `window` switch
  ([0x5c7758], read by 2D init 0x459410) opens a developer window with a status bar, garbled menu, crash on 3D.
  dgVoodoo windowed needs AppControlledScreenMode = false, which breaks menu mouse input (see above), and with the
  stored conf it stayed fullscreen and switched the monitor to 60 Hz.

## INCIDENT 2026-11-06 22:17: Art\D3D\ReqArtD3.dat overwritten by me, restored
- `xxd D3D/* | head` in the game's Art folder: with two names xxd writes the hexdump of the first INTO the second, so
  the real ReqArtD3.dat (16004 bytes) became a 105 MB text dump. Restored at 22:21 (tester approved) from
  backups\requiem-pristine zip; sha256 f1d921140e03... matches the test copy; ReqArtD3.art untouched (hash equal).
- Rule: inspect game data only in testgame\, and never pass xxd more than one file.

## HD textures - recon (2026-11-06)
- 3D textures: Art\D3D\ReqArtD3.art (24.7 MB) + ReqArtD3.dat = 4001 u32 offsets (0xFFFFFFFF = empty), 2686 used.
  (Art\HW, Art\SW = the 3Dfx / software renderer sets, not used by D3D.exe.) Entry: 8-byte header read at 0x41faa8
  (u32 type/flags e.g. 0x4412 / 0x8412 / 0x10412, u32), then a compressed blob decoded by 0x45fc70. Decoded image:
  u16 width [+0], u16 height [+2], byte [+0xe] bytes per pixel, 256-colour palette at +0x12 (0x400 bytes) for 8-bit.
  Fetch by index: 0x41f9a0 (offset table at this+0x3e8c), upload via 0x505ee0 -> XLR8 texture create 0x505680/0x506296.
- Route under consideration: (1) decode all entries (reimplement 0x45fc70 or dump decoded images at runtime),
  (2) AI-upscale locally on the tester's machine, (3) hook the upload so a texture index with an HD file in a folder
  gets a bigger surface (D3D UVs are normalised); original archive untouched, HD files never bundled.
- Compression: ReqArtD3.art entries are PKWARE DCL "implode" streams (explode() at 0x50d8c0 with a 0x3134-byte work
  buffer, read/write callbacks 0x45fbf0/0x45fc30). Entry = u32 decoded size, u32 0, u32 stream size, stream
  (00 06 = binary, 4 KB dictionary). `mod\blast.py` (port of zlib's blast.c) decodes all 2686; `mod\tex_extract.py`
  -> hd\orig (2401 x 128x128, 212 x 256x256, rest smaller; 2551 8-bit paletted RGBA-palette, 125 16-bit, A1R5G5B5
  likely). Animated textures: byte +0xc = frame count (frame size at +4/+6, +8/+0xa).

## HD textures (2026-11-07, Requiem Modern 1.5.0)
- Engine test: every texture 4x nearest-neighbour -> loads and runs (120 fps) but textures magnified: the upload
  0x505ee0 copies the header size into the texture record ([ebx+4]/[ebx+6]; path 5 stores float w, h/2 at
  [[ebx+0x14]+0x10/0x14]) and the renderer scales texel coordinates by it. Fix (PATCHES "HD textures", caves at
  0x51ED00): at the 3 record stores + the float path, a side > 256 (never true for originals) means 4x HD -> store
  size / 4. Surface creation 0x5055d0 and the copies use the full HD size. Verified: same layout, sharper.
- HD set (hd\eligible.txt, 2496): 8-bit, single frame, no colour key (+0x10 & 0x80), longer side >= 128.
  Real-ESRGAN ncnn-vulkan 20220424 (downloads\realesrgan, approved, BSD), model realesrgan-x4plus, 16 px
  wrapped border for tiling (`mod\tex_upscale.py`, 7.7 min for all on the tester's GPU) -> hd\x4. Each mapped back
  onto its own 256-colour palette with Floyd-Steinberg (`mod\hd_build.py`): visually equal to true colour.
- Archive writer `mod\art_build.py`: literal-only DCL streams (9 bits/byte, byte-plane packing), round-trip tested.
  HD archive 884 MB on disk. Payload `mod\hd_pack.py build` -> hd\hd_payload.bin (LZMA, 339 MB), appended to the exe
  by build.bat (footer RQHDPAK1 + u64 size; PyInstaller onefile still runs with appended data, tested).
- Launcher 1.5.0: Graphics > Textures > HD textures On (default) / Off. On: backs up the GOG ReqArtD3.art/.dat
  (sha-checked) to Modern Backup, writes the HD archive (HD entries re-encoded, others copied byte for byte) and
  Art\D3D\ReqArtD3.hd as marker; ~20-30 s once. Off / Restore original game: originals copied back (hash-verified).
  End-to-end on the test copy with the built exe: built from the appended payload, level renders HD.
- Not HD yet: 125 16-bit effect textures, 12 colour-keyed, animated and < 128 px textures; menus/HUD (media\DIBs).
- 1.5.1 (tester asked for a launcher option that installs them): HD textures default Off; changing
  the setting (arrows, click, Delete, Reset page) installs or removes them at once (sync_hd, message while it works;
  if the game is running it waits for Play). Tested in the launcher on the test copy: Off -> originals back, On ->
  installed in ~22 s. Tester's saved setting is hd=1 (installed), so nothing changes for them.

## HD textures: the rest (2026-11-07, Requiem Modern 1.6.0) - all 2686 HD
- Remaining 190: 124 x 16-bit, 12 render-flagged 8-bit (+0x10 & 0x80; NOT colour-keyed: every upload passes key -1),
  15 small, 39 skins with animation frames (+0xc frames of +4/+6 size at +8/+0xa in the atlas; data after the atlas).
- 16-bit formats: +0x10 bit 0x80 set = A1R5G5B5, clear (0x60) = A4R4G4B4 (glows/lightning only look right as 4444).
  Pack/unpack round-trips byte-exact for both (mod\tex_extract.fmt16_of, hd_build._pixels via ImageMath).
- New HD caves: shared SUB at 0x51ED00 returns the original size from a marker 'RQHD' + u16 w, h placed after the
  pixel + frame data (+0x412 + bpp*(w*h + frames*fw*fh)); only looked for when a side > 256 (small textures are
  upscaled 8x/16x so every HD texture qualifies); no marker = /4 (1.5.x archives). Disassembly-checked.
- Frames upscaled separately (mod\hd_rest.py export -> hd\frames_orig, 312 frames), size/position scaled 4x.
- Full set crashed on entering a level: 0x45fc43 explode write to NULL+0x19, loader 0x4f5bf0 allocating from the
  fixed game-memory arena (VirtualAlloc 0x6000000, 0x852B40 bytes, bump allocator 0x4461d0, no NULL check). Grown to
  128 MB (15 constants in 0x446130-0x4464a0; log: extents (0x6000000, 0xe000000)). No game-folder DLL is based there.
- catch_crash.py: RQ_GAME selects the folder, passes nomovies, swallows 0xC0000008 (debugger-only invalid handle).
  (Before that edit applied, one run started the REAL game folder: launch + load only, nothing written.)
- Verified on the test copy: level renders, creature close-up (skin) and player's hand in HD, 120 fps, no crash.
- Payload 375 MB (2686 textures); launcher 1.6.0: marker records the payload size, an older HD install is rebuilt
  from the backed-up originals (tested: 1.5.x mark -> rebuilt in 27 s; Off -> GOG hashes).

## 1.6.1 fixes (2026-11-07): striped skins, red HUD highlight
- Tester screenshot: a man's skin drawn as streaks. Cause (mine): skins with animation frames store the FRAMES FIRST,
  then the atlas (path 4 at 0x506408: [eax+0xc] = pixel start = frames, atlas after frames*fw*fh*bpp); I had read
  the atlas from the pixel start. tex_extract.pixel_start(), hd_rest.frames_of and hd_build (frames then atlas)
  fixed; 39 skins + 312 frames re-exported and re-upscaled. Checked: HD 3502 decodes clean; human body in the first
  cavern textured correctly in game. (The marker offset was right either way: it uses the total size.)
- Tester: red square at the bottom of the HUD, seen when the ability icon changed. 0x45d0f0 draws
  three icon slots (scaled by the quad hook) then a red outline round the active slot ([0x658ac3], flags 0x658acc+n)
  via 0x434fd0 (4 x line 0x4581d0, colour 0xf9 = red) from the unscaled slot rect. Hook 0x434fd0 -> HUD cave
  "redbox": same axis scaling as the icons. Verified by forcing slot 1 on the test copy: outline = scaled icon size,
  in the slot row. test_hud.py still passes.

## 1.6.2: water and effects keep their grain (2026-11-09)
- Tester: water and effects did not look HD. Water 9/82 (and copies 1509/1582) are A4R4G4B4 colour-speckle
  textures; Real-ESRGAN treats speckle as noise and flattened them (bigger but less detail). mod\detail_loss.py:
  AI result box-shrunk back vs original, / original neighbour detail; good textures ~0.4-0.6, speckle/effects >= 0.75.
- Compared AI / Lanczos / 50:50 by eye: for 8-bit walls AI stays (clearly better); for 16-bit effects (water,
  lightning, fire, explosions, glows) Lanczos 4x keeps the sparkle; 16-bit skins (1166-1169, 3001, 3016, 3053, 3248,
  3260, 3271, 3280, 3318) stay AI. All 112 non-skin 16-bit textures -> Lanczos (whole animation sequences
  consistent); AI versions kept in hd\x4_ai. Payload rebuilt.

## 1.6.3: sewer water (2026-11-09)
- Tester screenshot: sewer water banded, pixelated. Reproduced with a save copied into the test copy
  (slot 0). Original textures: smooth murky water. Bisect
  (mod\hd_bisect.py, mod\water_shot.sh): all 16-bit original -> smooth; only 8/9/82/1508/1509/1582 original -> smooth.
  The game builds the rippling water from those textures every frame at their original size; a 4x texture gives the
  stripes. Those six are excluded (hd\x4_excluded); 2680 HD.
- Also found: re-uploads of dirty (animated) textures (0x506900 / 0x506d70 / 0x5073f0 / 0x509240 -> 0x5059c0) used
  the record (= original) size. Hook at 0x5059c0 (cave 0x51EC00): surface exactly 4/8/16x the requested <=256 size on
  both axes -> copy the surface size (GetSurfaceDesc). Path 5's float size (scroll working size) reverted to the HD
  size. Labels fixed: site 0x5063EA is path 5 (w x h/2 surface), 0x506506 is path 4 (skins).

- 2026-11-09: tester confirmed in play that the sewer water looks right with 1.6.3.

## 1.7.0 HD HUD (2026-11-09)
- HUD art: media\DIBs\HUD (63 8-bit BMPs: AngIcons/InvIcons/WpnIcons 32x32, Digits 16x32, hud3 128x128; key index 0xfd
  = magenta). Image class 0x4c9f10 -> load 0x4ca260 -> 3D loader 0x509c20 (8-bit uncompressed only, reads 0x400
  palette, w*h pixels) -> 0x505790 builds the image record (obj+0x100, surface at +0x1c). 0x4ca260 then GetSurfaceDesc
  (obj+0x124: h +0x12c, w +0x130) and sets the layout rect from it. The quad 0x508aa0 maps the whole surface (UV 0..1).
- Patch (patch_d3d, cave 0x51EC90): HD BMP header biXPelsPerMeter = 'RQHD', biYPelsPerMeter = w | h<<16. Hook 0x509E3B
  stores it at record+4 (0 if not HD); hook 0x4CA362 (3D path only) replaces the surface size with it.
- Art (mod\hud_hd.py -> hd\hud): Real-ESRGAN x4plus 4x, key pixels filled from neighbours first, key mask upscaled
  separately and kept 1-bit, quantised to the original palette (FS dither, never into the key). The AI garbled the
  5 px label lettering (ENERGY -> CHERGY), so 15 labelled icons (green/red rows 24-28) get a Scale2x x2 strip from
  the label down.
- Verified on the test copy with the tester's save: icons and digits at the same size/position, sharper, no magenta fringe
  on the digits (in-game before/after hud_ingame.png). Launcher set_hud on/on/off/on: HD, idempotent, originals back
  byte for byte. 1.7.0 built (HUD bundled as hud\, 63 files) and copied to the game folder.
- Not HD: menus (2D 640x480 screen scaled by DDrawCompat; HD would mean a higher-res menu renderer), HUDLoRes (<640 modes).
- 2026-11-09: tester confirmed in play that the HD HUD looks right with 1.7.0.

## 1.8.0 Menus at the game resolution (2026-11-09)
- The front end is DirectDraw 2D, 640x480x8 (palette), set by 0x458970(w,h,bpp) from 0x458946 (front end) and
  0x458898 (menu entered from a level). Primary [0x5c710c], back buffer [0x5c7110], sized from the mode. Render mode
  [0x658d20]: 1 = 2D, 2 = 3D. Traced with mod\menu_trace.py (int3 on the surface methods): every menu draw is
  BltFast/Blt of an image's surface onto the back buffer (image draw 0x4ca7a0, 5 call sites), a colour-fill clear
  0x4d07bd, present BltFast back->primary 0x4d0942 or Flip 0x4d07cc; text is GDI (TextOut 0x4ca540 / DrawText
  0x4ca6a1) into blank images (0x4ca0a0, created per text widget); list/dropdown outlines are direct writes with a
  hard-coded 640 pitch (0x4ce28b, 0x4cfed2); videos (Smacker) Lock the primary and decode into it (0x4c7c41/72).
- RequiemMenu.dll (menu\rqmenu.c, zig cc x86; patch_d3d loads it first thing at the entry point 0x5109a2 -> cave
  0x51EDB4). With RequiemMenu.cfg "W H": 2D mode WxH x8; the shared surface vtable (Release, Blt, BltFast, GetDC,
  GetSurfaceDesc, Lock, Unlock) maps logical 640x480 rects to the back/primary (S = min(W/640,H/480), centred,
  clipped to the 4:3 picture: hidden widgets are parked off-screen) and to HD surfaces (registry: logical vs physical
  size). Blank images are created S x larger with a GDI world transform -> TrueType text at full resolution.
  BMPs with the 'RQHD' header are registered; GetSurfaceDesc reports the logical size. Outlines -> scaled colour
  fills. Videos -> 640x480 stand-in surface, stretched onto the primary on Unlock. Cursor 0x459dc0 mapped back.
- Art: mod\menu_hd.py: Real-ESRGAN 4x masters of the 172 menu BMPs (hd\menu4x, 87 MB payload RQMNPAK1 appended after
  the texture payload); the launcher's set_menu resamples them (Lanczos) to exactly S, quantises to each image's
  palette, key from the original, ~6 s, cached by media\DIBs\RequiemMenu.art; originals in Modern Backup\DIBs.
- Verified on the test copy at 1920x1080 (S 2.25), 1280x720 (1.5), 2560x1440 (3): title, main, options (display,
  controls, sound), single player, load list, credits, multiplayer, intro videos, level load and back, in-level Esc
  menu, quit dialog; clicks land; no failed blits; no direct back-buffer writes left. Launcher set_menu on / cached /
  res change / off (originals byte for byte) / on. Not yet seen: alt-tab in a menu, typing a save name, the
  between-level briefings.
- 2026-11-09: tester confirmed in play that the menus look and work right with 1.8.0.

## 1.9.0 HD upgrades as separate options (2026-11-09)
- Graphics > HD: HD textures (hd: 2,574 walls/floors/objects/characters), HD effects (hdfx: 106 = 16-bit single-frame
  textures except the 12 16-bit skins), HD HUD icons (hdhud), HD menu art (hdmenu; off = original art Lanczos-resampled
  with the key as premultiplied alpha). Menu resolution stays in Display. Texture archive marker records "sel TF";
  1.8 markers count as both groups. Settings from 1.8: hd copied to hdfx and hdhud.
- Tested on the test copy: sel 10 / 01 / 11 / 00 (wall 0, effect 642, skin 3502 decoded sizes HD or original as
  chosen, 00 restores the GOG archive), menu art 0/1/0 (2.6 s / 5.3 s), migration, and in game with effects + HUD on,
  textures + menu art off.

## 1.9.1 Menu mouse fix (2026-11-09)
- Tester: mouse does nothing in the 1.8 menus, keyboard works. Cause: the front end takes the mouse from each message's
  msg.pt (minus the window rect) in its handler 0x4d99a0 (called with the MSG by value from the loop at 0x4d9838),
  not from 0x459dc0 (called once). My test clicks (um win drive click X Y = SetCursorPos to those numbers) put the
  cursor at 640x480 values, which the unmapped game read as menu coordinates, so they "worked" by coincidence.
- Fix: RequiemMenu.dll wraps the 0x4d9838 call and maps msg.pt of mouse messages to 640x480. Verified with
  mod\real_mouse.py (absolute SendInput at screen pixels, like a real mouse): 'options' highlights on hover (162 vs
  93), click opens Options, Cancel returns. Use real_mouse.py, not um win drive clicks, for menu tests from now on.

- 1.9.2 (2026-11-09): tester: mouse dead in the quit confirmation. The two modal loops (0x4da261, 0x4da6a6) call the
  same handler 0x4d99a0; both now go through the msg.pt mapping too. real_mouse.py quit: "no" highlights (76 vs 56),
  click closes the dialog.
- 2026-11-09: tester confirmed the mouse works in the quit dialog with 1.9.2.

## 1.9.3 Borderless alt-tab (2026-11-09)
- Tester: in Borderless, alt-tab minimises the game. The game never minimises itself (WM_ACTIVATEAPP only sets
  [0x5c6fb4]; its ShowWindow calls are at window creation); DDrawCompat does, ShowWindow(SW_SHOWMINNOACTIVE) from its
  own code on deactivation (exclusive-fullscreen emulation), even with FullscreenMode = borderless.
- RequiemMenu.dll: cfg line 2 "nominimize" (written by the launcher when Display mode = Borderless; the cfg is now
  always written, "640 480" when the menu option is off) hooks user32!ShowWindow (32-bit jmp [ptr] stub) and ignores
  minimise requests for the game window. Verified (mod\alttab.py, real Alt+Tab): menu and level stay visible, not
  minimised; back in the game it renders and takes input. Fullscreen (exclusive) mode keeps the minimise.

- 1.9.4: in the real game folder ShowWindow starts 8b ff 55 8b ec (shimmed, not the jmp [ptr] stub the test copy has),
  so 1.9.3 logged "unknown prologue, not hooked". Hot-patch prologue now hooked via a trampoline. Not yet verified.
- 1.9.5: 1.9.4 hooked the ShowWindow that GetProcAddress returned, which on the tester PC is apphelp.dll (a shim);
  DDrawCompat calls user32 directly, so nothing was caught. Now win32u!NtUserShowWindow and NtUserShowWindowAsync are
  hooked (address from the export table, mov eax,imm32 stub -> trampoline). Test copy: hooked, alt-tab kept visible.
- 2026-11-09: tester: with 1.9.5 alt-tab keeps the game open (not minimised) but its window shows black while in the
  background. The game pauses without focus (no frames presented) and DDrawCompat does not repaint the last frame.
  Tester: acceptable; left as is (revisited in 1.9.6 / 1.9.8).
- 1.9.6: black background window: DDrawCompat releases its screen copy on WM_ACTIVATEAPP(0). RequiemMenu.dll wraps
  the window procedure on top of DDrawCompat (ddraw.dll) and sends focus loss only to the game (0x4597c0, still
  pauses), then takes "always on top" off the game windows and puts them at the bottom (DDrawCompat would have).
  Test copy: other apps stay on top in menu and level, game resumes on return. The picture behind could not be
  captured (WGC delivers no frame from a paused background window); tester to check.
- 2026-11-09: tester confirmed with 1.9.6: alt-tab in borderless shows the paused game picture behind other windows.
- 1.9.7 (2026-11-09): REVERTED 1.9.6: DDrawCompat's picture window stayed TOPMOST (and is click-through), so
  the paused picture covered the other windows while clicks went to what was underneath. Lesson:
  WindowFromPoint skips click-through windows; check the real stacking order from outside.
- 1.9.8 (2026-11-09): picture kept while away, done safely. Focus loss goes only to the game (as 1.9.6); then, every
  100 ms while away, the game's windows are placed directly behind the active window with win32u!NtUserSetWindowPos
  (placing after a non-topmost window also removes topmost). DDrawCompat hides its picture window from EnumWindows,
  FindWindowEx and GetTopWindow/GetWindow inside the game and filters SetWindowPos, so the windows come from the
  kernel list (win32u!NtUserBuildHwndList) with the owner from NtUserQueryWindow. Test mod\alttab_click.py (own test
  window, true stacking order via GetTopWindow from outside, click only if a game window is really top at the point):
  menu and level: test window top, no game window topmost, picture above the game window, a real click on the
  visible picture brings the game back, alt-tab away/back works. The click that brings it back also reaches the game.
- 2026-11-09: tester confirmed 1.9.8 alt-tab works on their PC.
- 2026-11-13: tester confirmed the remaining menu screens (save name, briefings/loading, multiplayer) work.
- 2026-11-13: tidy (tester OK): moved dgVoodoo.conf, dgVoodooCpl.exe, D3D.exe.stuck and the old "Requiem Launcher.json"
  out of the game folder to an archive folder (not deleted).

## Game options file Gamers\latest.cfg (2026-11-13)
- Loader 0x4d4670 (path, edx), saver 0x4d4a40, defaults 0x4d4b90 (+ key defaults 0x466560). Layout (292 bytes):
  u32 n, n bytes profile name ("*\0"); u32 flags [0x659110]; f32 mouse sensitivity [0x659154] (0.5);
  u32 resolution index [0x65923c]; u8 H/W device [0x659238]; f32 brightness [0x6591f4] (0.5); u8 3D audio provider
  [0x659239]; f32 sound vol [0x659240], dialog vol [0x6591ec], music vol [0x6591f0] (1.0); 256-byte key table
  [0x5c87b4 + DIK scancode] = action.
- Flags (default 0x01290003): 0x1 Always Run, 0x2 Mouse Free Look, 0x4 Invert Mouse, 0x20 Analog Movement, 0x40 Use
  Trackball (controls page apply 0x4d4dfc, widgets 0x13a/b/c/d/0x158); 0x10000 Show Crosshairs, 0x40000 Show Dialogue
  Text, 0x80000 Show Shadows, 0x100000 Hide Weapon, 0x200000 Enable Special FX (display page 0x4d51e6);
  0x1000000 Audible Footsteps (sound page 0x4d53cf). Labels are RT_STRING resources (0x6a4.. etc.).
- Key table: 0x44 = no command, 0x46 = reserved (Esc...). Action number = index into the non-empty strings 0x640..:
  0 Forward ... 0x27 Railgun, 0x28 Hand ... 0x3f Quick Save (F5), 0x40 Quick Load, 0x41 Take Screenshot (F10!),
  0x42 Use Bound Power, 0x43 Journal/Info (F1). Mouse buttons at 0xfa..0xfe (0xfc Fire, 0xfd Use Defensive);
  0xff = Mouse Z Control (wheel): 0x44 Unused, 0x00 Frwrd/Back, 0x12 Weapon, 0x14 Offensive, 0x16 Defensive,
  0x18 Maneuver, 0x1a Interactive, 0x1c Inventory (U/D).

## 2.0.0 Apply, the game's own options, F10 in game (2026-11-13)
- Launcher: settings edits are pending (marked with a dot, value in gold) until Apply (A) / Discard (D); Play refuses
  while changes are pending and uses only applied settings; HD textures no longer install the moment they are toggled.
- launcher\game_cfg.py reads/writes Gamers\latest.cfg (layout in "Game options file"); round trip byte-identical.
  New tabs: Game (brightness, crosshairs, hide weapon, shadows, effects, dialogue text, three volumes, footsteps) and
  Controls (sensitivity, free look, invert, wheel, always run, analog, trackball, Key bindings page: choose an action,
  press a key or mouse button; Delete clears). Not offered: H/W device and 3D audio provider (detected at run time).
- F10: Play keeps the launcher running hidden (closes with the game; mutex Local\RequiemModernLauncher).
  RequiemMenu.dll watches F10 while the game has focus and signals Local\RequiemModernF10; the launcher shows its
  settings over the paused game. Apply there: game options -> latest.cfg + shared memory Local\RequiemModernLive
  (seq, flag mask/flags, 5 floats, 256 keys), applied by the DLL in the game's window procedure on WM_ACTIVATEAPP(1)
  (game thread): flags, sensitivity, volumes, key table, brightness via the game's gamma routine 0x505340 (stdcall
  float). Other settings are saved and installed by the next Play. F10 is unbound in the game's table at Play (its
  Take Screenshot moves to F12 if free); the key page refuses F10.
- Test mod\f10_test.py (input only to the launcher/game; a first run without the guard sent keys/clicks to the Claude
  window, tester checked nothing changed): F10 in a level opened the settings, crosshair off + music 10->30%, Apply,
  Escape: game in front, memory flags 01280003, music 0.30; launcher closed with the game.
- 2.0.1 (2026-11-13): game volumes + footsteps moved to the Audio tab (GAME VOLUME); the selected row's left/right arrows
  are click targets (left steps down; before, any click on a row stepped up). Tested: click > 3->4, < twice ->2, keys Left/Right.
- 2026-11-13: tester confirmed 2.0.1 all working (Apply, game options tabs, F10, Audio tab, arrows).

## Release package 2.0.1 (2026-11-13)
- Two builds (launcher\build.bat / build.bat lite): RequiemModern-2.0.1 (23 MB, no game art; HD options hidden when the
  payloads / HUD art are absent) and RequiemModern-HD-2.0.1 (485 MB, AI-upscaled game art). release\*.zip with README
  (md + txt), CHANGELOG.txt (from CHANGES), LICENSES (Requiem Modern MIT, DDrawCompat 0BSD, DSOAL LGPL 2.1 + version,
  OpenAL Soft LGPL 2). um publish check: only "verbatim" hits are the DSOAL/OpenAL licence texts (installed in the game
  folder by the launcher itself), kept deliberately. Exe scanned: no username or personal paths.
- Not published: the HD package redistributes upscaled 3DO art (tester's call where, if anywhere).

## 2.1.0 MAKE HD ART: the HD art is made on the player's PC (2026-11-13)
- The release carries none of the game's art. `mod/hd_make.py` runs the whole HD pipeline from the player's
  original files: the texture archive is decoded (blast), every texture except the six water ones upscaled
  (Real-ESRGAN x4plus with a 16 px wrapped border and alpha kept separately; the 106 16-bit effect textures Lanczos
  4x), skins' animation frames too, then `hd_build.hd_raw` (4/8/16x, back to the texture's palette / 1555 / 4444,
  `RQHD` marker) into `textures.bin` (zlib); HUD via `hud_hd.main`, menu masters via `menu_hd.masters` + `pack`.
  Originals come from the launcher's backups where it has replaced files. `done.txt` is written last.
- Launcher: art in `%LOCALAPPDATA%\Requiem Modern\HD art`; MAKE HD ART main-menu item, progress page on a worker
  thread, Esc / closing the window cancels (the upscaler is killed, partial art removed). If Real-ESRGAN cannot run
  (no Vulkan), the textures are made with Lanczos and the HD HUD / menu options stay hidden.
- Verified: the art made by the built exe is byte-identical to the hand-made set (2,680 textures, 63 HUD images,
  172 menu masters), and a game folder installed from it is identical to one installed from the hand-made set
  (476 files). About 13-18 minutes on the test PC. Exe 56 MB (was 485 MB).

### 2.1.0: generated textures (stained glass) with HD (2026-11-13/14)
- User screenshot (real game, art made by MAKE HD ART): the stained-glass window at the end of the opening tunnel
  was combed stripes; same with the shipped 2.0.x set (byte-identical art). Original textures: intact window.
- Cause: upload paths 2/3 (0x5060fa / 0x506521; type from the texture's object vtable [0]) are generated textures.
  The set-up copies the source's pixels ([[gen+0x18]+8]+0x10) into new buffers and makes the target surface at the
  TARGET record size (128x128), then the effects redraw the target from the source every frame, hard-coded to
  128x128: 0x4f4f30 scroll (dst[(r+py)&127][(c+px)&127] = src[r][c], px/py = (int)pos floats +0x10/+0x14), 0x4f5180
  ripple and 0x4f53f0 scroll + ripple (dst[r][c] = src[r+ro+floor(E[c]*floor(C[r]*D[phy]))][c+co+floor(T[c]*F[r])],
  T[k] = floor(A[k]*B[phx]); tables +0x20/+0x24/+0x30/+0x34/+0x48/+0x4c, phases +0x38/+0x3c low 16 bits, floor
  rounding throughout (0x50fd5b = floor); ro/co = scroll offsets, or (table pointer + 0x400) & 127 in the plain
  ripple). With an HD source the copy was the first 1/16 of the HD pixels at the wrong row length. Logged in the
  test copy (cave appending (target, source) pairs to the .data slack): level 1 generates 4001 <- 601,
  4002 <- 759, 4003 <- 1072 (128x128 8-bit). Sources come from the compressed .jam maps, so no static list.
- First fix (original pixels appended to HD textures, generator pointed at them) worked but the window was then
  128x128 between HD walls (user: "low res") and freed an interior pointer; replaced.
- Fix: patch_d3d gen_patches (CAVE 0x51E760, so not in --trace builds): when the source is HD at exactly 4x the
  target record, the record holds the HD size during the set-up (buffers, copies, target surface all HD; the source
  keeps HD pixels matching its HD surface) and gets its size back at 0x506601 (saved at 0x6BF780). RequiemMenu.dll
  (rqmenu.c gen_hd) detours the three effects: the game's effect runs (keeps its state), then the same effect is
  redrawn at the HD size; scroll offsets x k; the ripple's integer offsets interpolated between neighbouring
  128-space pixels so the glass bends smoothly (block moves showed jaggies on the sharp HD lead lines). Only when
  the target surface really is the HD size (GetSurfaceDesc).
- Verified (test copy, New Game, level start): window HD, sharp glass and lead lines, smooth ripple; log
  "HD generated textures: on".

### 2.1.1: face frames, flat textures, quantization (2026-11-14)
- User screenshots: the homeless man (and every skin with face animation) had extra faces on the side of the head
  and the legs, changing with the face animation. 0x4f58b0 (type-4 anim object: +0xc frames start, +0x10/+0x14
  frame w/h, +0x18/+0x1c position) copies a frame into the atlas with the pitch from the texture RECORD width
  ([rec+4], the original 256) while the HD atlas is 1024 wide. Patch at 0x4F58F5: pitch from the decoded header
  ([anim+0xc] - 0x412), identical when not HD. All 39 skins with frames (3500-3538).
- User screenshot: grainy debris. 94 textures are one flat colour in the GOG archive (1-24, 469, 479-481, 948,
  1088-1109, 1501-1524, 1892-1899, 1976, 2083-2098, 2170-2172, 2550); Real-ESRGAN's faint variation became
  Floyd-Steinberg speckle. hd_make.FLAT (KEEP = WATER | FLAT) stays original, also skipped by set_hd for art made
  by 2.1.0 (marker "keep N" forces the rebuild).
- Palette mapping (hd_build._pixels): nearest colour, which was as close to the AI image as FS on every texture
  measured and without the grain; FS only for smooth gradients the palette cannot follow (error > 10 and the AI image
  smooth: 3217/3218 banded into blotches). done.txt "v2"; the launcher offers REMAKE HD ART for older art and makes
  into "HD art new", swapping it in when complete (cancel keeps the old art).
- User screenshot: blotchy skylight grille. The six 16-bit A1R5G5B5 textures (flag 0x80: 642/643/1002/1003/2253/
  2254, on/off alpha, speckled bars) counted as effects (16-bit single frame) and got Lanczos, which smeared the
  speckle into blotches. is_effect (hd_make and launcher) now excludes flag 0x80: AI like other surfaces (alpha kept
  binary). Real effects are all A4R4G4B4.
