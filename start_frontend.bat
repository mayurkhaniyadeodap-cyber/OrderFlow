@echo off
REM Starts the React dev server on http://127.0.0.1:5173 (proxies /api to the backend, port 8000 or %PORT%).
if "%PORT%"=="" if exist "%~dp0backend\.env" for /f "usebackq tokens=1,* delims== " %%a in ("%~dp0backend\.env") do if /i "%%a"=="PORT" set "PORT=%%b"
if "%PORT%"=="" set PORT=8000
set ORDERFLOW_API=http://127.0.0.1:%PORT%
cd /d "%~dp0frontend" || exit /b 1
if not exist "node_modules" (
  echo Frontend is not set up yet. Run setup.bat first.
  pause
  exit /b 1
)
echo Starting OrderFlow frontend on http://127.0.0.1:5173  (Ctrl+C to stop)
call npm run dev
pause
