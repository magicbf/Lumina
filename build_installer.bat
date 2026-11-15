@echo off
rem Build dist\Lumina-Setup.exe: the branded installer with the app packed inside.
setlocal
cd /d "%~dp0"

call "%~dp0build_exe.bat" || exit /b 1

echo [A] Packing the app into the installer payload...
python tools\make_payload.py || goto :error

echo [B] Building Lumina-Setup.exe...
python -m PyInstaller ^
  --noconfirm --onefile --windowed ^
  --name Lumina-Setup ^
  --icon "%~dp0assets\lumina.ico" ^
  --version-file "%~dp0build\setup_version_info.txt" ^
  --add-data "%~dp0dist\payload.zip;." ^
  --distpath "dist" ^
  --workpath "build\pyinstaller-setup" ^
  --specpath "build" ^
  --exclude-module tkinter ^
  --exclude-module unittest ^
  --exclude-module pydoc ^
  --exclude-module PIL ^
  --exclude-module numpy ^
  --log-level WARN ^
  setup_main.py || goto :error

echo.
echo   dist\Lumina-Setup.exe
echo.
goto :eof

:error
echo.
echo Build failed.
exit /b 1
