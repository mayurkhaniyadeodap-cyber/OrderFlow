@echo off
REM Starts the FastAPI backend on http://127.0.0.1:8000 (API docs at /docs).
REM Port in use? Add a line  PORT=8010  to backend\.env (used by all start scripts and the Vite proxy).
if "%PORT%"=="" if exist "%~dp0backend\.env" for /f "usebackq tokens=1,* delims== " %%a in ("%~dp0backend\.env") do if /i "%%a"=="PORT" set "PORT=%%b"
if "%HOST%"=="" if exist "%~dp0backend\.env" for /f "usebackq tokens=1,* delims== " %%a in ("%~dp0backend\.env") do if /i "%%a"=="HOST" set "HOST=%%b"
if "%PORT%"=="" set PORT=8000
if "%HOST%"=="" set HOST=127.0.0.1
cd /d "%~dp0backend" || exit /b 1
if not exist ".venv\Scripts\python.exe" (
  echo Backend is not set up yet. Run setup.bat first.
  pause
  exit /b 1
)
echo Starting OrderFlow backend on http://%HOST%:%PORT%  (Ctrl+C to stop)
".venv\Scripts\python.exe" -m uvicorn app.main:app --host %HOST% --port %PORT%
pause
