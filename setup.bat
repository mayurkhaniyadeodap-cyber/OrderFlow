@echo off
REM One-time setup: Python virtual environment, backend packages, .env, frontend packages.
setlocal
cd /d "%~dp0backend" || goto :fail
echo [1/4] Creating Python virtual environment...
if not exist ".venv\Scripts\python.exe" ( py -3 -m venv .venv || python -m venv .venv || goto :fail )
echo [2/4] Installing backend packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements-dev.txt || goto :fail
echo [3/4] Creating backend\.env (if missing)...
".venv\Scripts\python.exe" scripts\init_env.py || goto :fail
cd /d "%~dp0frontend" || goto :fail
echo [4/4] Installing frontend packages...
call npm install || goto :fail
echo.
echo Setup complete. Start the portal with start_backend.bat and start_frontend.bat
echo (or start_portal.bat for a single-window build).
pause
exit /b 0
:fail
echo.
echo SETUP FAILED - see the messages above.
pause
exit /b 1
