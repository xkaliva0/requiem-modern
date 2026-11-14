@echo off
rem Build "Requiem Modern.exe" (installer + launcher) with PyInstaller -> dist\Requiem Modern.exe
rem It carries none of the game's art: MAKE HD ART makes it on the player's PC (mod\hd_make.py) with the bundled
rem Real-ESRGAN (launcher\realesrgan: realesrgan-ncnn-vulkan.exe, vcomp140.dll, models\realesrgan-x4plus.*).
cd /d "%~dp0"
py -m PyInstaller --noconfirm --onefile --windowed --name "Requiem Modern" ^
  --paths "%~dp0..\mod" --hidden-import art_build --hidden-import blast --hidden-import menu_hd --hidden-import hd_make ^
  --add-binary "%~dp0ddrawcompat\ddraw.dll;ddrawcompat" --add-binary "%~dp0..\menu\RequiemMenu.dll;." --add-data "%~dp0dsoal;dsoal" ^
  --add-data "%~dp0realesrgan;realesrgan" ^
  --distpath "%~dp0dist" --workpath "%~dp0build_dist" --specpath "%~dp0build_dist" "%~dp0requiem_modern.py" || exit /b 1
