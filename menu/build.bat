@echo off
rem Build RequiemMenu.dll (32-bit) with zig cc (py -m pip install ziglang).
cd /d "%~dp0"
py -m ziglang cc -target x86-windows-gnu -shared -O2 -Wall -o RequiemMenu.dll rqmenu.c -lgdi32 -luser32 || exit /b 1
del /q RequiemMenu.lib RequiemMenu.pdb 2>nul
