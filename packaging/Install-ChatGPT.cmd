@echo off
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-ChatGPT.ps1" %*
set "installerExit=%errorlevel%"
if not "%installerExit%"=="0" (
    echo Installation failed. Read the error above.
    pause
)
exit /b %installerExit%
