@echo off
rem Build the one-folder Lumina app: dist\Lumina\Lumina.exe + its DLLs.
setlocal
cd /d "%~dp0"

tasklist /fi "imagename eq Lumina.exe" 2>nul | find /i "Lumina.exe" >nul
if not errorlevel 1 (
  echo Lumina.exe is running - close it before building.
  exit /b 1
)

echo [1/3] Rendering the icon...
python tools\make_icon.py || goto :error

rem Optional image-format plugins are imported by name at runtime, so
rem PyInstaller can only find them if we ask - and only if they are installed.
set "EXTRA="
python -c "import pillow_heif" 2>nul
if not errorlevel 1 set "EXTRA=%EXTRA% --collect-all pillow_heif"
python -c "import pillow_jxl" 2>nul
if not errorlevel 1 set "EXTRA=%EXTRA% --collect-all pillow_jxl"

echo [2/3] Packaging with PyInstaller...
python -m PyInstaller %EXTRA% ^
  --noconfirm --clean --onedir --windowed ^
  --name Lumina ^
  --icon "%~dp0assets\lumina.ico" ^
  --version-file "%~dp0build\version_info.txt" ^
  --distpath "dist" ^
  --workpath "build\pyinstaller" ^
  --specpath "build" ^
  --exclude-module tkinter ^
  --exclude-module unittest ^
  --exclude-module pydoc ^
  --exclude-module numpy ^
  --log-level WARN ^
  main.py || goto :error

rem Trim what a QPainter-only app never loads: the software OpenGL fallback
rem (20 MB) and Qt's translation files.
del /q "dist\Lumina\_internal\PyQt6\Qt6\bin\opengl32sw.dll" 2>nul
rmdir /s /q "dist\Lumina\_internal\PyQt6\Qt6\translations" 2>nul

echo [3/3] Done.
echo.
echo   dist\Lumina\Lumina.exe   (small launcher; DLLs live in dist\Lumina\_internal)
echo.
goto :eof

:error
echo.
echo Build failed.
exit /b 1
