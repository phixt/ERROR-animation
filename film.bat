@echo off
rem ERROR-animation -- render to video: record logical frames, then ffmpeg
rem (ASCII only on purpose: cmd.exe parses .bat as OEM codepage, Chinese here would corrupt it)
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
if not exist "out" mkdir out

echo [1/4] recording logical frames...
%PY% -m erranim.player --headless --width 118 --height 32 --record out\demo.jsonl
if errorlevel 1 goto :err

echo [2/4] rendering the audio track (noise bed + system sounds + ffmpeg polish)...
%PY% -m erranim.audiotrack --out out\demo.wav
if errorlevel 1 goto :err

echo [3/4] encoding with ffmpeg...
%PY% -m erranim.film --record out\demo.jsonl --out out\demo.mp4 --audio out\demo.wav %*
if errorlevel 1 goto :err

echo [4/4] exporting preview stills...
%PY% -m erranim.film --record out\demo.jsonl --png 26,33,42,61,72.9,88,92.2,102.5,105.4,106.3
echo.
echo done: out\demo.mp4
echo %cmdcmdline% | find /i "%~nx0" >nul 2>nul && pause
exit /b 0

:err
echo.
echo failed, see the output above.
echo %cmdcmdline% | find /i "%~nx0" >nul 2>nul && pause
exit /b 1
