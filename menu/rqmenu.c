/* RequiemMenu.dll: the 2D front end (menus) at the game's resolution instead of 640x480.
 * D3D.exe (patched by patch_d3d: LoadLibrary("RequiemMenu.dll") before ddraw) loads this DLL. With RequiemMenu.cfg
 * ("W H") next to the exe it patches the running game:
 *  - the 2D display mode 640x480x8 becomes WxH x8; the menu code keeps drawing in 640x480 logical coordinates;
 *  - DirectDraw surface methods (shared vtable, patched once the 2D surfaces exist) map logical rects onto the
 *    back buffer / primary (scale S = min(W/640, H/480), centred) and onto HD surfaces (registry below);
 *  - blank images (text, composition buffers; 0x4ca0a0) are created S times larger, and their DCs get a world
 *    transform, so TrueType text is drawn at full resolution; GetSurfaceDesc reports their logical size;
 *  - BMP images whose header says 'RQHD' (HD art written by the launcher) are registered with their logical size;
 *  - the list/box outline (0x4ce28b, direct writes with a 640 pitch) is drawn with scaled colour fills;
 *  - the menu cursor (0x459dc0) is mapped back to 640x480.
 * Without the cfg file (or 640x480) nothing is changed. Build: build.bat (zig cc, x86). */
#include <windows.h>
#include <math.h>
#include <stdio.h>

static int W = 640, H = 480, on;
static float S = 1, OX, OY;
static FILE *lgf;
#define LOG(...) do { if (lgf) { fprintf(lgf, __VA_ARGS__); fflush(lgf); } } while (0)

#define BACKP (*(void **)0x5C7110)
#define PRIMP (*(void **)0x5C710C)
static int in2d(void) { return *(int *)0x658D20 == 1; }

/* ---------------------------------------------------------------- HD surface registry (logical vs physical size) */
typedef struct { void *s; int lw, lh, pw, ph; } HD;
static HD hd[4096];
static int nhd;
static CRITICAL_SECTION cs;
static HD *find(void *s) { for (int i = 0; i < nhd; i++) if (hd[i].s == s) return &hd[i]; return 0; }
static void reg(void *s, int lw, int lh, int pw, int ph) {
    EnterCriticalSection(&cs);
    HD *e = find(s);
    if (!e && nhd < 4096) e = &hd[nhd++];
    if (e) { e->s = s; e->lw = lw; e->lh = lh; e->pw = pw; e->ph = ph; }
    LeaveCriticalSection(&cs);
}
static void unreg(void *s) {
    EnterCriticalSection(&cs);
    for (int i = 0; i < nhd; i++) if (hd[i].s == s) { hd[i] = hd[--nhd]; break; }
    LeaveCriticalSection(&cs);
}

static int dbg_n;
typedef struct { float sx, sy, ox, oy; } MAP;
static int map_of(void *s, MAP *m) {
    m->sx = m->sy = 1; m->ox = m->oy = 0;
    if (!s) return 0;
    if (s == BACKP || s == PRIMP) { m->sx = m->sy = S; m->ox = OX; m->oy = OY; return 1; }
    HD *e = find(s);
    if (e) { m->sx = (float)e->pw / e->lw; m->sy = (float)e->ph / e->lh; return 1; }
    return 0;
}
static LONG mx(const MAP *m, LONG v) { return (LONG)floorf(m->ox + v * m->sx + 0.5f); }
static LONG my(const MAP *m, LONG v) { return (LONG)floorf(m->oy + v * m->sy + 0.5f); }
static void mrect(const MAP *m, const RECT *r, RECT *o) {
    o->left = mx(m, r->left); o->top = my(m, r->top); o->right = mx(m, r->right); o->bottom = my(m, r->bottom);
}

/* ---------------------------------------------------------------- surface method hooks */
typedef HRESULT(WINAPI *Blt_t)(void *, RECT *, void *, RECT *, DWORD, void *);
typedef HRESULT(WINAPI *BltFast_t)(void *, DWORD, DWORD, void *, RECT *, DWORD);
typedef HRESULT(WINAPI *GetDC_t)(void *, HDC *);
typedef HRESULT(WINAPI *GSD_t)(void *, DWORD *);
typedef ULONG(WINAPI *Rel_t)(void *);
static Blt_t oBlt; static BltFast_t oBltFast; static GetDC_t oGetDC; static GSD_t oGSD; static Rel_t oRel;

static void logical_size(void *s, MAP *m, int mapped, RECT *r) {
    HD *e = find(s);
    if (e) { SetRect(r, 0, 0, e->lw, e->lh); return; }
    DWORD d[31] = {0x7C};
    oGSD(s, d);
    SetRect(r, 0, 0, d[3], d[2]);
    if (mapped && (s == BACKP || s == PRIMP)) SetRect(r, 0, 0, 640, 480);
}

static void fail(const char *m, void *t, void *s, HRESULT hr, const RECT *D, const RECT *SR) {
    if (dbg_n++ < 40)
        LOG("%s on %s src %p failed %08lx: D %ld,%ld,%ld,%ld SR %ld,%ld,%ld,%ld\n", m, t == BACKP ? "back" : t == PRIMP ? "primary" : "surface",
            s, (unsigned long)hr, D ? D->left : -1, D ? D->top : -1, D ? D->right : -1, D ? D->bottom : -1,
            SR ? SR->left : -1, SR ? SR->top : -1, SR ? SR->right : -1, SR ? SR->bottom : -1);
}

/* Clip a destination rect (and its source rect, proportionally) to the 640x480 picture on the back buffer /
 * primary: the game parks hidden widgets off-screen, which the original screen edge cut off. 0 = nothing left. */
static int clip(void *t, RECT *D, RECT *SR) {
    if (t != BACKP && t != PRIMP) return 1;
    RECT V = {(LONG)OX, (LONG)OY, (LONG)OX + (LONG)floorf(640 * S + 0.5f), (LONG)OY + (LONG)floorf(480 * S + 0.5f)}, C;
    if (D->left >= V.left && D->top >= V.top && D->right <= V.right && D->bottom <= V.bottom) return 1;
    if (!IntersectRect(&C, D, &V)) return 0;
    if (SR) {
        float fx = (float)(SR->right - SR->left) / (D->right - D->left), fy = (float)(SR->bottom - SR->top) / (D->bottom - D->top);
        SR->left += (LONG)((C.left - D->left) * fx + 0.5f); SR->right -= (LONG)((D->right - C.right) * fx + 0.5f);
        SR->top += (LONG)((C.top - D->top) * fy + 0.5f); SR->bottom -= (LONG)((D->bottom - C.bottom) * fy + 0.5f);
        if (SR->right <= SR->left || SR->bottom <= SR->top) return 0;
    }
    *D = C;
    return 1;
}

static HRESULT WINAPI myBlt(void *t, RECT *d, void *s, RECT *sr, DWORD f, void *fx) {
    if (!in2d()) return oBlt(t, d, s, sr, f, fx);
    MAP mt, ms;
    int a = map_of(t, &mt), b = map_of(s, &ms);
    if (!a && !b) return oBlt(t, d, s, sr, f, fx);
    if (t == PRIMP && s == BACKP) return oBlt(t, 0, s, 0, f, fx);   /* present: the whole frame */
    RECT D, SR, full = {0, 0, 640, 480};
    RECT *pd = d, *ps = sr;
    if (a && d) { mrect(&mt, d, &D); pd = &D; }
    else if (a && !d && s && (t == BACKP || t == PRIMP)) { mrect(&mt, &full, &D); pd = &D; }
    if (b && s && sr) { mrect(&ms, sr, &SR); ps = &SR; }
    if (pd == &D) {
        if (s && !ps) { DWORD dd[31] = {0x7C}; oGSD(s, dd); SetRect(&SR, 0, 0, dd[3], dd[2]); ps = &SR; }
        if (!clip(t, &D, s ? ps : 0)) return 0;
    }
    HRESULT hr = oBlt(t, pd, s, ps, f, fx);
    if (hr) fail("Blt", t, s, hr, pd, ps);
    return hr;
}

static HRESULT WINAPI myBltFast(void *t, DWORD x, DWORD y, void *s, RECT *sr, DWORD f) {
    if (!in2d()) return oBltFast(t, x, y, s, sr, f);
    MAP mt, ms;
    int a = map_of(t, &mt), b = map_of(s, &ms);
    if (!a && !b) return oBltFast(t, x, y, s, sr, f);
    if (t == PRIMP && s == BACKP) return oBltFast(t, 0, 0, s, 0, f);   /* present: same size, whole frame */
    RECT r, SR, D;
    if (sr) r = *sr; else logical_size(s, &ms, b, &r);
    RECT dl = {(LONG)x, (LONG)y, (LONG)x + r.right - r.left, (LONG)y + r.bottom - r.top};
    mrect(&mt, &dl, &D);
    if (b) mrect(&ms, &r, &SR); else SR = r;
    if (b && fabsf(ms.sx - mt.sx) < 0.01f && fabsf(ms.sy - mt.sy) < 0.01f) {   /* same scale: exact 1:1 copy */
        D.right = D.left + SR.right - SR.left; D.bottom = D.top + SR.bottom - SR.top;
    }
    if (!clip(t, &D, &SR)) return 0;
    HRESULT hr;
    if (D.right - D.left == SR.right - SR.left && D.bottom - D.top == SR.bottom - SR.top)
        hr = oBltFast(t, D.left, D.top, s, &SR, f);
    else
        hr = oBlt(t, &D, s, &SR, 0x1000000 | ((f & 1) ? 0x8000 : 0), 0);   /* WAIT | KEYSRC */
    if (hr) fail("BltFast", t, s, hr, &D, &SR);
    return hr;
}

static HRESULT WINAPI myGetDC(void *t, HDC *ph) {
    HRESULT r = oGetDC(t, ph);
    if (r == 0 && in2d()) {
        HD *e = find(t);
        if (e) {
            XFORM x = {(float)e->pw / e->lw, 0, 0, (float)e->ph / e->lh, 0, 0};
            SetGraphicsMode(*ph, GM_ADVANCED);
            SetWorldTransform(*ph, &x);
        }
    }
    return r;
}

static HRESULT WINAPI myGSD(void *t, DWORD *d) {
    HRESULT r = oGSD(t, d);
    HD *e;
    if (r == 0 && (e = find(t))) { d[2] = e->lh; d[3] = e->lw; }
    return r;
}

typedef HRESULT(WINAPI *Lock_t)(void *, RECT *, void *, DWORD, HANDLE);
static Lock_t oLock;
static void *lock_seen[16];
/* Videos (Smacker, 0x4c7c41 / 0x4c7c72) lock the primary and decode 640x480 frames straight into it. They get a
 * 640x480 stand-in surface instead; on Unlock it is stretched onto the primary's 4:3 picture. */
typedef HRESULT(WINAPI *Unlock_t)(void *, RECT *);
static Unlock_t oUnlock;
static void *shadow, *shadow_dd;
static int shadow_locked;
static void *get_shadow(void) {
    void *dd = ((void *(*)(void))0x4D0050)();
    if (shadow && dd == shadow_dd) return shadow;
    DWORD desc[31] = {0x7C, 0x1007, 480, 640};   /* CAPS | HEIGHT | WIDTH | PIXELFORMAT */
    desc[0x48 / 4] = 0x20; desc[0x4C / 4] = 0x60; desc[0x54 / 4] = 8;   /* 8-bit palette indexed */
    desc[0x68 / 4] = 0x840;                                             /* OFFSCREENPLAIN | SYSTEMMEMORY */
    void *s = 0;
    if (((HRESULT(WINAPI *)(void *, void *, void **, void *))(*(void ***)dd)[6])(dd, desc, &s, 0)) return 0;
    shadow = s; shadow_dd = dd;
    LOG("video stand-in surface %p\n", s);
    return s;
}
static HRESULT WINAPI myLock(void *t, RECT *r, void *d, DWORD f, HANDLE h) {
    if (in2d() && (t == BACKP || t == PRIMP)) {
        void *ret = __builtin_return_address(0);
        int i;
        if (t == PRIMP && (ret == (void *)0x4C7C44 || ret == (void *)0x4C7C75)) {
            void *s = get_shadow();
            if (s) {
                HRESULT hr = oLock(s, 0, d, f, h);
                if (hr == 0) { shadow_locked = 1; return 0; }
            }
        }
        for (i = 0; i < 16 && lock_seen[i] && lock_seen[i] != ret; i++);
        if (i < 16 && !lock_seen[i]) { lock_seen[i] = ret; LOG("Lock on %s from %p\n", t == BACKP ? "back" : "primary", ret); }
    }
    return oLock(t, r, d, f, h);
}
static HRESULT WINAPI myUnlock(void *t, RECT *r) {
    if (shadow_locked && t == PRIMP) {
        shadow_locked = 0;
        oUnlock(shadow, 0);
        RECT full = {0, 0, 640, 480}, D;
        MAP m; map_of(PRIMP, &m); mrect(&m, &full, &D);
        return oBlt(PRIMP, &D, shadow, 0, 0x1000000, 0);
    }
    return oUnlock(t, r);
}

static ULONG WINAPI myRel(void *t) {
    ULONG n = oRel(t);
    if (n == 0 && nhd) unreg(t);
    return n;
}

/* ---------------------------------------------------------------- code patching helpers */
static int patch(DWORD at, const void *bytes, int n) {
    DWORD old;
    if (!VirtualProtect((void *)at, n, PAGE_EXECUTE_READWRITE, &old)) return 0;
    memcpy((void *)at, bytes, n);
    VirtualProtect((void *)at, n, old, &old);
    FlushInstructionCache(GetCurrentProcess(), (void *)at, n);
    return 1;
}
static void rel32(BYTE *p, DWORD from_end, DWORD to) { *(DWORD *)p = to - from_end; }
static int redirect_call(DWORD at, DWORD expect, void *fn) {   /* E8 call at `at` to `expect` -> fn */
    if (*(BYTE *)at != 0xE8 || at + 5 + *(LONG *)(at + 1) != expect) { LOG("call at %08lx: unexpected bytes\n", at); return 0; }
    BYTE b[5] = {0xE8}; rel32(b + 1, at + 5, (DWORD)fn);
    return patch(at, b, 5);
}
static int same(DWORD at, const char *hex) {
    for (int i = 0; hex[2 * i]; i++) {
        unsigned v; sscanf(hex + 2 * i, "%2x", &v);
        if (((BYTE *)at)[i] != v) { LOG("bytes at %08lx differ: not the GOG D3D.exe\n", at); return 0; }
    }
    return 1;
}

/* DDInitSurfaces (0x458b40): afterwards the 2D surfaces exist; patch their (shared) vtable once. */
static int (*oInitSurf)(void) = (int (*)(void))0x458B40;
static void hook_vtable(void **vt) {
    if (oBlt) return;
    DWORD old;
    VirtualProtect(vt, 0x90, PAGE_EXECUTE_READWRITE, &old);
    oRel = vt[2]; vt[2] = myRel;
    oBlt = vt[5]; vt[5] = myBlt;
    oBltFast = vt[7]; vt[7] = myBltFast;
    oGetDC = vt[17]; vt[17] = myGetDC;
    oGSD = vt[22]; vt[22] = myGSD;
    oLock = vt[25]; vt[25] = myLock;
    oUnlock = vt[32]; vt[32] = myUnlock;
    VirtualProtect(vt, 0x90, old, &old);
    LOG("surface vtable %p hooked\n", vt);
}
static int initsurf(void) {
    int r = oInitSurf();
    if (r && BACKP) {
        void **vb = *(void ***)BACKP, **vp = PRIMP ? *(void ***)PRIMP : vb;
        hook_vtable(vb);
        if (vp != vb) LOG("primary has its own vtable %p (not hooked)\n", vp);
        LOG("2D surfaces: back %p primary %p, %dx%d S=%.3f ox=%.0f oy=%.0f\n", BACKP, PRIMP, W, H, S, OX, OY);
    }
    return r;
}

/* Blank images (0x4ca0a0, 2D path): create the surface S times larger, keep the logical size in the image. */
static HRESULT WINAPI mycreate(DWORD *desc, void **psurf) {
    void *dd = ((void *(*)(void))0x4D0050)();
    int lw = desc[3], lh = desc[2], pw = (int)floorf(lw * S + 0.5f), ph = (int)floorf(lh * S + 0.5f);
    desc[3] = pw; desc[2] = ph;
    HRESULT hr = ((HRESULT(WINAPI *)(void *, void *, void **, void *))(*(void ***)dd)[6])(dd, desc, psurf, 0);
    desc[3] = lw; desc[2] = lh;
    if (hr == 0) reg(*psurf, lw, lh, pw, ph);
    return hr;
}

/* 2D BMP loader 0x436150 (ecx = DirectDraw, edx = path, 2 stack args): register HD art by its header. */
typedef void *(__attribute__((fastcall)) *ld_t)(void *, const char *, int, int);
static void *__attribute__((fastcall)) myload(void *dd, const char *path, int a, int b) {
    void *s = ((ld_t)0x436150)(dd, path, a, b);
    if (s && path) {
        FILE *f = fopen(path, "rb");
        if (f) {
            BYTE h[54];
            if (fread(h, 1, 54, f) == 54 && !memcmp(h + 38, "RQHD", 4)) {
                DWORD lo = *(DWORD *)(h + 42);
                int pw = *(LONG *)(h + 18), ph = abs(*(LONG *)(h + 22));
                reg(s, lo & 0xFFFF, lo >> 16, pw, ph);
            }
            fclose(f);
        }
    }
    return s;
}

/* List / box outline (replaces 0x4ce28b..0x4ce3b1: Lock + 1 px lines in colour 0xf6 with a 640 pitch). */
static void box(LONG l, LONG t, LONG r, LONG b) {
    RECT side[4] = {{l, t, r + 1, t + 1}, {l, b, r + 1, b + 1}, {l, t, l + 1, b}, {r, t, r + 1, b}};
    DWORD fx[25] = {100};
    fx[20] = 0xF6;   /* dwFillColor */
    MAP m; map_of(BACKP, &m);
    for (int i = 0; i < 4; i++) {
        RECT D; mrect(&m, &side[i], &D);
        if (D.right <= D.left) D.right = D.left + 1;
        if (D.bottom <= D.top) D.bottom = D.top + 1;
        if (clip(BACKP, &D, 0)) oBlt(BACKP, &D, 0, 0, 0x1000400, fx);   /* WAIT | COLORFILL */
    }
}
static void WINAPI mybox(BYTE *o) { box(*(LONG *)(o + 0x8C), *(LONG *)(o + 0x90), *(LONG *)(o + 0x94), *(LONG *)(o + 0x98)); }
/* the dropdown's own copy of the same outline (0x4cfed2..0x4cffe2), rect at +0x20 */
static void WINAPI mybox2(BYTE *o) { box(*(LONG *)(o + 0x20), *(LONG *)(o + 0x24), *(LONG *)(o + 0x28), *(LONG *)(o + 0x2C)); }

/* Menu cursor 0x459dc0 (ecx = POINT*, client coordinates): back to 640x480. */
typedef void(__attribute__((fastcall)) *cur_t)(POINT *);
static void __attribute__((fastcall)) mycur(POINT *p) {
    ((cur_t)0x459DC0)(p);
    if (!in2d()) return;
    LONG x = (LONG)((p->x - OX) / S), y = (LONG)((p->y - OY) / S);
    p->x = x < 0 ? 0 : x > 639 ? 639 : x;
    p->y = y < 0 ? 0 : y > 479 ? 479 : y;
}

/* The front end's message handler 0x4d99a0 (MSG by value, ret 0x1c) takes the mouse position from msg.pt
 * relative to the window (mouse move, clicks): map it back to 640x480 before it sees it. */
typedef struct { DWORD hwnd, message, wparam, lparam, time; LONG x, y; } MSG7;
static void WINAPI mymsg(MSG7 m) {
    if (in2d() && m.message >= 0x200 && m.message <= 0x20E) {
        RECT r;
        if (GetWindowRect((HWND)m.hwnd, &r)) {
            LONG x = (LONG)((m.x - r.left - OX) / S), y = (LONG)((m.y - r.top - OY) / S);
            m.x = r.left + (x < 0 ? 0 : x > 639 ? 639 : x);
            m.y = r.top + (y < 0 ? 0 : y > 479 ? 479 : y);
        }
    }
    ((void(WINAPI *)(MSG7))0x4D99A0)(m);
}

/* Borderless: DDrawCompat still minimises the game window when it loses focus (exclusive-fullscreen behaviour), so
 * alt-tab hides the game. With "nominimize" in the cfg, minimise requests for the game's window are ignored and it
 * stays on screen behind the other windows. user32!ShowWindow (32-bit) is a jmp [ptr] stub or already detoured. */
static BOOL(WINAPI *oShow)(HWND, int), (WINAPI *oShowAsync)(HWND, int);
static int keep_visible(HWND hw, int cmd, void *ret) {
    if (!hw || hw != *(HWND *)0x5C6F6C) return 0;
    if (cmd != SW_SHOWMINIMIZED && cmd != SW_MINIMIZE && cmd != SW_SHOWMINNOACTIVE && cmd != SW_FORCEMINIMIZE) return 0;
    static int n;
    if (n++ < 10) LOG("kept the game window on screen (ShowWindow %d from %p)\n", cmd, ret);
    return 1;
}
static BOOL WINAPI myShow(HWND hw, int cmd) { return keep_visible(hw, cmd, __builtin_return_address(0)) ? TRUE : oShow(hw, cmd); }
static BOOL WINAPI myShowAsync(HWND hw, int cmd) { return keep_visible(hw, cmd, __builtin_return_address(0)) ? TRUE : oShowAsync(hw, cmd); }
/* Export address straight from a module's export table (GetProcAddress can be redirected by compatibility shims:
 * on the user's PC it returned apphelp.dll's ShowWindow, which DDrawCompat never calls). */
static BYTE *export_addr(HMODULE m, const char *name) {
    BYTE *b = (BYTE *)m;
    if (!b) return 0;
    IMAGE_NT_HEADERS *nt = (IMAGE_NT_HEADERS *)(b + ((IMAGE_DOS_HEADER *)b)->e_lfanew);
    IMAGE_EXPORT_DIRECTORY *ed = (IMAGE_EXPORT_DIRECTORY *)(b + nt->OptionalHeader.DataDirectory[0].VirtualAddress);
    DWORD *names = (DWORD *)(b + ed->AddressOfNames), *funcs = (DWORD *)(b + ed->AddressOfFunctions);
    WORD *ords = (WORD *)(b + ed->AddressOfNameOrdinals);
    for (DWORD i = 0; i < ed->NumberOfNames; i++)
        if (!strcmp((char *)b + names[i], name)) return b + funcs[ords[i]];
    return 0;
}
/* Hook win32u!NtUserShowWindow(Async): user32!ShowWindow and any shim in front of it all end there. The 32-bit stubs
 * start with mov eax, imm32 (5 bytes, position independent): copy them to a trampoline and jump in their place. */
static void *hook5(const char *name, void *fn_new) {
    BYTE *fn = export_addr(GetModuleHandleA("win32u.dll"), name);
    if (!fn || (fn[0] != 0xB8 && memcmp(fn, "\x8b\xff\x55\x8b\xec", 5))) {
        LOG("borderless: %s %s, not hooked\n", name, fn ? "has an unknown start" : "not found");
        return 0;
    }
    BYTE *t = VirtualAlloc(0, 16, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t) return 0;
    memcpy(t, fn, 5); t[5] = 0xE9; rel32(t + 6, (DWORD)t + 10, (DWORD)fn + 5);
    BYTE j[5] = {0xE9};
    rel32(j + 1, (DWORD)fn + 5, (DWORD)fn_new);
    patch((DWORD)fn, j, 5);
    return t;
}
/* Alt-tab in borderless, keeping the picture: DDrawCompat releases its copy of the screen when the game loses
 * focus (WM_ACTIVATEAPP 0), so the window goes black. A subclass on top of DDrawCompat's sends that message only to
 * the game's own window procedure 0x4597c0 (the game still pauses) and DDrawCompat never hears of it.
 * DDrawCompat would also have taken "always on top" off its windows (its picture window is click-through): 1.9.6 got
 * this wrong and the picture covered every window while clicks went to what was underneath. So while the game is
 * away a guard keeps every window of the game out of the topmost band, directly behind the active window: clicks on
 * the visible picture then land on the game's own window and bring it back. */
static WNDPROC prevProc;
static volatile int away;
static int fixes, reorder;
static HWND mine[16];
static int nmine;
/* Every tick while away: put the game's windows directly behind the active window, bottom-up so they keep their
 * order (the picture stays above the game's own window). Placing a window after a non-topmost one also takes its
 * 'always on top' off. Called through win32u: DDrawCompat filters SetWindowPos for its picture window (1.9.6 and the
 * first try here both 'removed' topmost while the real stacking order kept it). */
typedef BOOL(WINAPI *swp_t)(HWND, HWND, int, int, int, int, UINT);
static swp_t ntSWP;
static void behind_fg(void) {
    if (!ntSWP) ntSWP = (swp_t)export_addr(GetModuleHandleA("win32u.dll"), "NtUserSetWindowPos");
    if (!ntSWP) return;
    nmine = 0;
    /* DDrawCompat hides its picture window from EnumWindows and FindWindowEx inside the game: walk the real
     * stacking order instead (top to bottom), as an outside process sees it */
    static DWORD_PTR(WINAPI *ntQuery)(HWND, int);
    if (!ntQuery) ntQuery = (void *)export_addr(GetModuleHandleA("win32u.dll"), "NtUserQueryWindow");
    /* the kernel's own list of top-level windows, in stacking order (DDrawCompat's hooks cannot hide anything here) */
    static LONG(WINAPI *ntList)(HANDLE, HWND, BOOL, BOOL, DWORD, UINT, HWND *, UINT *);
    if (!ntList) ntList = (void *)export_addr(GetModuleHandleA("win32u.dll"), "NtUserBuildHwndList");
    static HWND all[2048];
    UINT n = 0;
    if (!ntList || ntList(0, 0, FALSE, FALSE, 0, 2048, all, &n) < 0 || n > 2048) n = 0;
    for (UINT ix = 0; ix < n && nmine < 16; ix++) {
        HWND hw = all[ix];
        DWORD np = ntQuery ? (DWORD)ntQuery(hw, 0) : 0;   /* 0 = owning process id, as the kernel has it */
        if (np == GetCurrentProcessId() && (GetWindowLongA(hw, GWL_STYLE) & WS_VISIBLE)) mine[nmine++] = hw;
    }
    HWND fg = GetForegroundWindow();
    DWORD fp = 0; GetWindowThreadProcessId(fg, &fp);
    if (!fg || fp == GetCurrentProcessId()) return;
    for (int i = nmine - 1; i >= 0; i--)
        if (!ntSWP(mine[i], fg, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE) && fixes++ < 10)
            LOG("away: placing window %p behind the active window failed (%lu)\n", mine[i], GetLastError());
    if (reorder) LOG("away: %d game windows placed behind the active window\n", nmine);
}
/* Live settings from Requiem Modern's in-game screen (F10). The launcher fills this block (named shared memory) while
 * the game is paused behind it; when the game gets the focus back, the values go into the game on its own thread:
 * the option flags, mouse sensitivity, volumes, key table, and brightness through the game's own gamma routine. */
typedef struct { volatile LONG seq; DWORD mask, flags; float sens, bright, sound, dialog, music; BYTE keys[256]; } LIVE;
static LIVE *live;
static LONG live_seq;
static int borderless;
static void apply_live(void) {
    if (!live || live->seq == live_seq) return;
    live_seq = live->seq;
    *(DWORD *)0x659110 = (*(DWORD *)0x659110 & ~live->mask) | (live->flags & live->mask);
    *(float *)0x659154 = live->sens; *(float *)0x659240 = live->sound; *(float *)0x6591EC = live->dialog;
    *(float *)0x6591F0 = live->music;
    memcpy((void *)0x5C87B4, live->keys, 256);
    if (*(float *)0x6591F4 != live->bright) {
        *(float *)0x6591F4 = live->bright;
        ((void(WINAPI *)(float))0x505340)(live->bright);   /* the game's brightness (gamma ramp) */
    }
    LOG("live settings applied (#%ld): flags %08lx, brightness %.2f, volumes %.2f %.2f %.2f\n", live_seq,
        *(DWORD *)0x659110, live->bright, live->sound, live->dialog, live->music);
}
/* F10 while the game has the focus: signal the launcher (it shows its settings over the game). */
static DWORD WINAPI f10_watch(LPVOID ev) {
    int down = 0;
    for (;;) {
        Sleep(40);
        DWORD p = 0; GetWindowThreadProcessId(GetForegroundWindow(), &p);
        int now = p == GetCurrentProcessId() && (GetAsyncKeyState(VK_F10) & 0x8000);
        if (now && !down) {
            HANDLE mx = OpenMutexA(SYNCHRONIZE, FALSE, "Local\\RequiemModernLauncher");
            if (mx) { CloseHandle(mx); SetEvent((HANDLE)ev); LOG("F10: settings requested\n"); }
            else LOG("F10: Requiem Modern is not running (start the game from it to use F10)\n");
        }
        down = now;
    }
}

static LRESULT CALLBACK myWndProc(HWND h, UINT m, WPARAM w, LPARAM l) {
    if (m == WM_ACTIVATEAPP && w) apply_live();
    if (m == WM_ACTIVATEAPP && borderless) {
        if (!w) {
            static int n;
            if (n++ < 5) LOG("focus lost: told the game only (picture stays up, behind other windows)\n");
            away = 1;
            LRESULT r = CallWindowProcA((WNDPROC)0x4597C0, h, m, w, l);
            reorder = 1; behind_fg(); reorder = 0;
            return r;
        }
        away = 0;
    }
    return CallWindowProcA(prevProc, h, m, w, l);
}
static DWORD WINAPI keeper(LPVOID unused) {
    for (int i = 0; !prevProc && i < 600; i++) {   /* up to 5 minutes: wait for DDrawCompat to hook the game window */
        Sleep(500);
        HWND h = *(HWND *)0x5C6F6C;
        if (!h) continue;
        WNDPROC cur = (WNDPROC)GetWindowLongA(h, GWL_WNDPROC);
        if (!cur || cur == (WNDPROC)0x4597C0) continue;
        HMODULE m = 0; char name[MAX_PATH] = "?";
        GetModuleHandleExA(6, (LPCSTR)cur, &m); GetModuleFileNameA(m, name, MAX_PATH);
        prevProc = cur;
        SetWindowLongA(h, GWL_WNDPROC, (LONG)myWndProc);
        LOG("window procedure %p (%s) wrapped\n", cur, name);
    }
    if (!prevProc) { LOG("game window procedure never changed, not wrapped\n"); return 0; }
    for (;;) {   /* the guard: while away, nothing of the game may sit in the topmost band */
        Sleep(100);
        if (away) behind_fg();
    }
}

static void hook_showwindow(void) {
    oShow = hook5("NtUserShowWindow", myShow);
    oShowAsync = hook5("NtUserShowWindowAsync", myShowAsync);
    if (oShow) LOG("borderless: alt-tab keeps the game on screen\n");
}

/* ---------------------------------------------------------------- HD generated textures
 * Generated textures (stained glass, glows) are 128x128 effects the game redraws from a source texture every frame:
 * 0x4f4f30 scroll, 0x4f5180 ripple, 0x4f53f0 scroll + ripple (thiscall, ecx = generator; flags +4 (0x10 = 16-bit),
 * position floats +0x10/+0x14, source record +0x18 (-> +8 texture object: +0x10 pixels, +0x14 palette = header +
 * 0x12), target texture object +0x1c (+0x10 pixels, +0x1c surface), ripple tables +0x20/+0x24/+0x30/+0x34/+0x48/+0x4c,
 * phase counters +0x38/+0x3c (low 16 bits)). patch_d3d makes a generator whose source is HD allocate its buffers and
 * surface at the HD size (the record keeps the original size for texture coordinates). Here the game's own effect
 * runs first (it keeps its state; at 128x128 it only touches the first rows of the HD buffers), then the same effect
 * is redrawn at the HD size: every 128-space pixel decision is the game's (same maths, floor rounding), applied to
 * the k x k block of HD pixels it stands for. */
typedef void(__attribute__((thiscall)) * GenFx_t)(BYTE *g);
static GenFx_t oScroll, oRipple, oScrollRipple;

static int gen_hd_size(BYTE *g, int *w, int *h) {
    BYTE *src = *(BYTE **)(*(BYTE **)(g + 0x18) + 8), *hdr = *(BYTE **)(src + 0x14) - 0x12;
    *w = *(WORD *)hdr; *h = *(WORD *)(hdr + 2);
    if ((*w <= 256 && *h <= 256) || *w % 128 || *h % 128) return 0;
    void *surf = *(void **)(*(BYTE **)(g + 0x1c) + 0x1c);   /* the target surface must really be that big */
    DWORD d[31] = {124};
    typedef HRESULT(WINAPI * Desc_t)(void *, DWORD *);
    if (!surf || (*(Desc_t **)surf)[22](surf, d) != 0) return 0;   /* GetSurfaceDesc */
    return (int)d[3] == *w && (int)d[2] == *h;              /* DDSURFACEDESC2: +8 height, +12 width */
}

static void gen_hd(BYTE *g, int kind) {   /* kind 0 scroll, 1 ripple, 2 scroll + ripple */
    int W, H;
    if (!gen_hd_size(g, &W, &H)) return;
    int kx = W / 128, ky = H / 128, bpp = (g[4] & 0x10) ? 2 : 1;
    BYTE *src = *(BYTE **)(*(BYTE **)(*(BYTE **)(g + 0x18) + 8) + 0x10), *dst = *(BYTE **)(*(BYTE **)(g + 0x1c) + 0x10);
    int px = (int)*(float *)(g + 0x10) & 127, py = (int)*(float *)(g + 0x14) & 127;
    if (kind == 0) {                       /* dst[(r + py) & 127][(c + px) & 127] = src[r][c] */
        for (int R = 0; R < H; R++) {
            BYTE *s = src + (size_t)R * W * bpp, *d = dst + (size_t)((R + py * ky) % H) * W * bpp;
            int o = px * kx * bpp, n = W * bpp;
            memcpy(d + o, s, n - o); memcpy(d, s + n - o, o);
        }
        return;
    }
    float *A = *(float **)(g + 0x30), *B = *(float **)(g + 0x48), *C = *(float **)(g + 0x34), *D = *(float **)(g + 0x4c);
    float *E = *(float **)(g + 0x20), *F = *(float **)(g + 0x24);
    int phx = *(DWORD *)(g + 0x38) & 0xffff, phy = *(DWORD *)(g + 0x3c) & 0xffff;
    int ro = kind == 1 ? (int)(((DWORD)F + 0x400) & 127) : px, co = kind == 1 ? (int)(((DWORD)E + 0x400) & 127) : py;
    float T[128];
    for (int k = 0; k < 128; k++) T[k] = (float)floor((double)A[k] * B[phx]);
    /* the game's offsets: dst[r][c] = src[r + ro + dr][c + co + dc]. At the HD size they are interpolated between
     * neighbouring 128-space pixels (wrapping, like the texture), so the glass bends smoothly instead of moving in
     * k x k blocks (sharp HD lead lines showed the steps as jaggies). */
    static float dr[128][128], dc[128][128];
    for (int r = 0; r < 128; r++) {
        double Rr = floor((double)C[r] * D[phy]);
        for (int c = 0; c < 128; c++) {
            dr[r][c] = (float)(ro + floor((double)E[c] * Rr));
            dc[r][c] = (float)(co + floor((double)T[c] * F[r]));
        }
    }
    static int c0[2048], c1[2048]; static float tx[2048];
    if (W > 2048) return;
    for (int C2 = 0; C2 < W; C2++) {
        float g = (C2 + 0.5f) / kx - 0.5f, f = floorf(g);
        c0[C2] = ((int)f + 128) & 127; c1[C2] = (c0[C2] + 1) & 127; tx[C2] = g - f;
    }
    for (int R = 0; R < H; R++) {
        float g = (R + 0.5f) / ky - 0.5f, f = floorf(g), ty = g - f;
        int r0 = ((int)f + 128) & 127, r1 = (r0 + 1) & 127;
        BYTE *d = dst + (size_t)R * W * bpp;
        for (int C2 = 0; C2 < W; C2++) {
            int a = c0[C2], b = c1[C2]; float t = tx[C2];
            float vr = (dr[r0][a] + (dr[r0][b] - dr[r0][a]) * t) * (1 - ty) + (dr[r1][a] + (dr[r1][b] - dr[r1][a]) * t) * ty;
            float vc = (dc[r0][a] + (dc[r0][b] - dc[r0][a]) * t) * (1 - ty) + (dc[r1][a] + (dc[r1][b] - dc[r1][a]) * t) * ty;
            int sy = (R + (int)lrintf(vr * ky)) % H, sx = (C2 + (int)lrintf(vc * kx)) % W;
            if (sy < 0) sy += H;
            if (sx < 0) sx += W;
            const BYTE *s = src + ((size_t)sy * W + sx) * bpp;
            if (bpp == 2) *(WORD *)(d + C2 * 2) = *(const WORD *)s; else d[C2] = *s;
        }
    }
}
static void __attribute__((thiscall)) myScroll(BYTE *g) { oScroll(g); gen_hd(g, 0); }
static void __attribute__((thiscall)) myRipple(BYTE *g) { oRipple(g); gen_hd(g, 1); }
static void __attribute__((thiscall)) myScrollRipple(BYTE *g) { oScrollRipple(g); gen_hd(g, 2); }

static void *detour(DWORD at, const char *hex, int n, void *fn) {   /* jmp at -> fn; returns a trampoline */
    if (!same(at, hex)) return 0;
    BYTE *t = VirtualAlloc(0, 32, MEM_COMMIT | MEM_RESERVE, PAGE_EXECUTE_READWRITE);
    if (!t) return 0;
    memcpy(t, (void *)at, n); t[n] = 0xE9; rel32(t + n + 1, (DWORD)t + n + 5, at + n);
    BYTE j[5] = {0xE9}; rel32(j + 1, at + 5, (DWORD)fn);
    return patch(at, j, 5) ? t : 0;
}
static void hook_gen(void) {
    oScroll = (GenFx_t)detour(0x4F4F30, "83ec0c535556", 6, myScroll);
    oRipple = (GenFx_t)detour(0x4F5180, "558bec81ec2c020000", 9, myRipple);
    oScrollRipple = (GenFx_t)detour(0x4F53F0, "558bec81ec3c020000", 9, myScrollRipple);
    LOG("HD generated textures: %s\n", oScroll && oRipple && oScrollRipple ? "on" : "FAILED");
}

static void install(void) {
    char path[MAX_PATH], *sl;
    GetModuleFileNameA(0, path, MAX_PATH);
    if ((sl = strrchr(path, '\\'))) *sl = 0;
    char cfg[MAX_PATH + 32], lg[MAX_PATH + 32];
    snprintf(cfg, sizeof cfg, "%s\\RequiemMenu.cfg", path);
    snprintf(lg, sizeof lg, "%s\\RequiemMenu.log", path);
    FILE *f = fopen(cfg, "r");
    if (!f) return;
    int w = 0, h = 0;
    char opt[32] = "";
    if (fscanf(f, "%d %d", &w, &h) != 2) w = h = 0;
    if (fscanf(f, "%31s", opt) != 1) opt[0] = 0;
    fclose(f);
    lgf = fopen(lg, "w");
    if (!strcmp(opt, "nominimize")) { borderless = 1; hook_showwindow(); }
    HANDLE map = CreateFileMappingA(INVALID_HANDLE_VALUE, 0, PAGE_READWRITE, 0, sizeof(LIVE), "Local\\RequiemModernLive");
    if (map) live = MapViewOfFile(map, FILE_MAP_ALL_ACCESS, 0, 0, sizeof(LIVE));
    if (live) live_seq = live->seq;
    HANDLE ev = CreateEventA(0, FALSE, FALSE, "Local\\RequiemModernF10");
    if (ev) CloseHandle(CreateThread(0, 0, f10_watch, ev, 0, 0));
    CloseHandle(CreateThread(0, 0, keeper, 0, 0, 0));
    LOG("F10 settings and live changes ready\n");
    hook_gen();
    if (w < 640 || h < 480 || (w == 640 && h == 480) || w > 7680 || h > 4320) return;
    W = w; H = h;
    S = fminf(W / 640.f, H / 480.f);
    OX = floorf((W - 640 * S) / 2); OY = floorf((H - 480 * S) / 2);
    LOG("RequiemMenu: menus at %dx%d (scale %.3f)\n", W, H, S);
    /* every site must be the GOG v1.2 code; check them all before changing anything */
    if (!same(0x458946, "bae0010000b980020000") || !same(0x458898, "bae0010000b980020000") || !same(0x4CA16B, "e8e05e00008b1081c6fc0000006a00565350ff5218")
        || !same(0x4CE28B, "a144715c00") || !same(0x4CFED2, "a144715c00") || *(BYTE *)0x458A93 != 0xE8 || *(BYTE *)0x4FCFCB != 0xE8 || *(BYTE *)0x4D9838 != 0xE8) return;
    BYTE m[10] = {0xBA, 0, 0, 0, 0, 0xB9, 0, 0, 0, 0};
    *(DWORD *)(m + 1) = H; *(DWORD *)(m + 6) = W;
    patch(0x458946, m, 10);                                   /* 2D mode WxH (8-bit stays): front end */
    patch(0x458898, m, 10);                                   /* and the menu entered from a level */
    redirect_call(0x458A93, 0x458B40, initsurf);
    BYTE c[21] = {0x81, 0xC6, 0xFC, 0, 0, 0, 0x56, 0x53, 0xE8, 0, 0, 0, 0, 0xE9, 0, 0, 0, 0, 0x90, 0x90, 0x90};
    rel32(c + 9, 0x4CA16B + 13, (DWORD)mycreate); rel32(c + 14, 0x4CA16B + 18, 0x4CA180);
    patch(0x4CA16B, c, 21);                                   /* blank images: HD surfaces */
    redirect_call(0x4CA329, 0x436150, myload);
    redirect_call(0x4CB217, 0x436150, myload);
    BYTE bx[13] = {0x56, 0xE8, 0, 0, 0, 0, 0x31, 0xFF, 0xE9, 0, 0, 0, 0};
    rel32(bx + 2, 0x4CE28B + 6, (DWORD)mybox); rel32(bx + 9, 0x4CE28B + 13, 0x4CE3B1);
    patch(0x4CE28B, bx, 13);                                  /* box outline */
    BYTE b2[13] = {0x56, 0xE8, 0, 0, 0, 0, 0x31, 0xF6, 0xE9, 0, 0, 0, 0};
    rel32(b2 + 2, 0x4CFED2 + 6, (DWORD)mybox2); rel32(b2 + 9, 0x4CFED2 + 13, 0x4CFFE2);
    patch(0x4CFED2, b2, 13);                                  /* dropdown outline */
    redirect_call(0x4FCFCB, 0x459DC0, mycur);
    redirect_call(0x4D9838, 0x4D99A0, mymsg);                 /* menu mouse: message positions */
    redirect_call(0x4DA261, 0x4D99A0, mymsg);                 /* and in the two modal loops (quit / yes-no dialogs) */
    redirect_call(0x4DA6A6, 0x4D99A0, mymsg);
    on = 1;
    LOG("hooks installed\n");
}

BOOL WINAPI DllMain(HINSTANCE hi, DWORD why, LPVOID r) {
    if (why == DLL_PROCESS_ATTACH) { InitializeCriticalSection(&cs); install(); }
    return TRUE;
}
