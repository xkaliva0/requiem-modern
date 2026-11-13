@echo off
rem Build "Requiem Modern.exe" (installer + launcher) with PyInstaller.
rem   build.bat        -> dist\Requiem Modern.exe       everything, with the HD art (HUD icons bundled; HD texture and
rem                                                     menu-art payloads appended afterwards by mod\hd_pack.py)
rem   build.bat lite   -> dist_lite\Requiem Modern.exe  no game art at all: the HD options are hidden
cd /d "%~dp0"
set OUT=dist
set ART=
if exist "%~dp0..\hd\hud" set ART=--add-data "%~dp0..\hd\hud;hud"
if /i "%1"=="lite" (set OUT=dist_lite& set ART=)
py -m PyInstaller --noconfirm --onefile --windowed --name "Requiem Modern" ^
  --paths "%~dp0..\mod" --hidden-import art_build --hidden-import blast --hidden-import menu_hd ^
  --add-binary "%~dp0ddrawcompat\ddraw.dll;ddrawcompat" --add-binary "%~dp0..\menu\RequiemMenu.dll;." --add-data "%~dp0dsoal;dsoal" %ART% ^
  --distpath "%~dp0%OUT%" --workpath "%~dp0build_%OUT%" --specpath "%~dp0build_%OUT%" "%~dp0requiem_modern.py" || exit /b 1
if /i "%1"=="lite" exit /b 0
if exist "%~dp0..\hd\hd_payload.bin" py "%~dp0..\mod\hd_pack.py" append "%~dp0dist\Requiem Modern.exe" "%~dp0..\hd\hd_payload.bin"
if exist "%~dp0..\hd\menu_payload.bin" py "%~dp0..\mod\hd_pack.py" append "%~dp0dist\Requiem Modern.exe" "%~dp0..\hd\menu_payload.bin" RQMNPAK1
