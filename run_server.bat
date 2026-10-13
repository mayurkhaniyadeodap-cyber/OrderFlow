@echo off
REM Live-server mode: serves the already-built React app and the API on one port (no build, no browser, no pause).
REM Use this from a Windows service or Task Scheduler ("At startup"). Build first with setup_production.bat.
REM Address and port come from backend\.env: HOST (127.0.0.1 = this PC only / behind a reverse proxy;
REM 0.0.0.0 = reachable from other computers) and PORT.
setlocal
if "%PORT%"=="" if exist "%~dp0backend\.env" for /f "usebackq tokens=1,* delims== " %%a in ("%~dp0backend\.env") do if /i "%%a"=="PORT" set "PORT=%%b"
if "%HOST%"=="" if exist "%~dp0backend\.env" for /f "usebackq tokens=1,* delims== " %%a in ("%~dp0backend\.env") do if /i "%%a"=="HOST" set "HOST=%%b"
if "%PORT%"=="" set PORT=8000
if "%HOST%"=="" set HOST=127.0.0.1
cd /d "%~dp0backend" || exit /b 1
if not exist ".venv\Scripts\python.exe" ( echo Run setup_production.bat first. & exit /b 1 )
if not exist "%~dp0frontend\dist\index.html" ( echo The frontend is not built. Run setup_production.bat first. & exit /b 1 )
echo OrderFlow running on http://%HOST%:%PORT%
".venv\Scripts\python.exe" -m uvicorn app.main:app --host %HOST% --port %PORT% --proxy-headers
exit /b %ERRORLEVEL%
