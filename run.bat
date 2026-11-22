@echo off
rem ERROR-animation -- terminal playback
rem (ASCII only on purpose: cmd.exe parses .bat as OEM codepage, Chinese here would corrupt it)
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PY=python
if exist ".venv\Scripts\python.exe" set PY=.venv\Scripts\python.exe
%PY% -m erranim.player %*
echo.
rem pause only when double-clicked, so scripting does not hang
echo %cmdcmdline% | find /i "%~nx0" >nul 2>nul && pause
