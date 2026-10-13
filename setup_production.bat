@echo off
REM Live-server setup: runtime Python packages only (no test tools), backend\.env (if missing),
REM frontend packages from the lock file, and a production build of the React app. Safe to run again after an update.
REM It never touches the database, uploads or backups.
setlocal
cd /d "%~dp0backend" || goto :fail
echo [1/5] Creating Python virtual environment (if missing)...
if not exist ".venv\Scripts\python.exe" ( py -3 -m venv .venv || python -m venv .venv || goto :fail )
echo [2/5] Installing runtime packages...
".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :fail
".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
echo [3/5] Creating backend\.env (if missing)...
".venv\Scripts\python.exe" scripts\init_env.py || goto :fail
cd /d "%~dp0frontend" || goto :fail
echo [4/5] Installing frontend packages from package-lock.json...
call npm ci || goto :fail
echo [5/5] Building the frontend...
call npm run build || goto :fail
echo.
echo Done. Before going live: edit backend\.env (see DEPLOYMENT.md), then start with run_server.bat.
pause
exit /b 0
:fail
echo.
echo SETUP FAILED - see the messages above.
pause
exit /b 1
