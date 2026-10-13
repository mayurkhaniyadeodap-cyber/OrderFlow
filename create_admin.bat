@echo off
REM Creates an Admin account. The password is typed at a hidden prompt (never shown, stored only as a hash).
setlocal
cd /d "%~dp0backend" || exit /b 1
if not exist ".venv\Scripts\python.exe" ( echo Run setup.bat first. & pause & exit /b 1 )
set "ADMIN_NAME=%~1"
if "%ADMIN_NAME%"=="" set /p ADMIN_NAME=Admin username (3-32 characters, a-z 0-9 . _ -): 
if "%ADMIN_NAME%"=="" ( echo No username given. & pause & exit /b 1 )
".venv\Scripts\python.exe" -m app.manage create-admin "%ADMIN_NAME%"
pause
