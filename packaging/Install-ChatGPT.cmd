@echo off
setlocal
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install-ChatGPT.ps1" %*
set "installerExit=%errorlevel%"
if not "%installerExit%"=="0" (
    echo Installation failed. Read the error above.
    pause
)
exit /b %installerExit%
