@echo off
REM Single-window mode: builds the React app, then serves UI + API together on http://127.0.0.1:8000 (or %PORT%)
if "%PORT%"=="" if exist "%~dp0backend\.env" for /f "usebackq tokens=1,* delims== " %%a in ("%~dp0backend\.env") do if /i "%%a"=="PORT" set "PORT=%%b"
if "%HOST%"=="" if exist "%~dp0backend\.env" for /f "usebackq tokens=1,* delims== " %%a in ("%~dp0backend\.env") do if /i "%%a"=="HOST" set "HOST=%%b"
if "%PORT%"=="" set PORT=8000
if "%HOST%"=="" set HOST=127.0.0.1
cd /d "%~dp0frontend" || exit /b 1
if not exist "node_modules" ( echo Run setup.bat first. & pause & exit /b 1 )
echo Building the frontend...
call npm run build || ( echo Frontend build failed. & pause & exit /b 1 )
cd /d "%~dp0backend" || exit /b 1
echo Open http://127.0.0.1:%PORT% in your browser  (Ctrl+C to stop)
start "" http://127.0.0.1:%PORT%
".venv\Scripts\python.exe" -m uvicorn app.main:app --host %HOST% --port %PORT%
pause
