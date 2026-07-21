@echo off
REM ============================================================
REM  Bhajan Video Generator - one-click standalone EXE builder
REM  Run this on WINDOWS, from the folder containing:
REM    - bhajan_video_with_preview_GUI.py
REM    - bhajan_video.spec
REM    - requirements.txt
REM    - ffmpeg.exe
REM    - icon.png
REM ============================================================

echo Checking required files...
if not exist "..\ffmpeg-8.1.2\bin\ffmpeg.exe" (
    echo [ERROR] ffmpeg.exe not found at ..\ffmpeg-8.1.2\bin\ffmpeg.exe
    pause
    exit /b 1
)
if not exist icon.png (
    echo [ERROR] icon.png not found in this folder. Place it here first.
    pause
    exit /b 1
)

echo.
echo Creating a clean virtual environment (build_env)...
python -m venv build_env
call build_env\Scripts\activate.bat

echo.
echo Installing dependencies...
pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Building standalone EXE with PyInstaller...
pyinstaller --clean --noconfirm bhajan_video.spec

echo.
if exist dist\Bhajan-Video-Generator.exe (
    echo ============================================================
    echo  SUCCESS: dist\Bhajan-Video-Generator.exe
    echo  This single file has everything embedded - no Python,
    echo  no libraries, no ffmpeg install needed on the target PC.
    echo ============================================================
) else (
    echo [ERROR] Build did not produce the expected exe. Scroll up for errors.
)

pause
