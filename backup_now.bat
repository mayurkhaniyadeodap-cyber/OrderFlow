@echo off
REM Creates a backup ZIP (database + uploaded files) in backend\backups. Safe while the portal is running.
REM Schedule it daily with Windows Task Scheduler. Old backups are never deleted automatically;
REM copy them to another drive or computer regularly.
setlocal
cd /d "%~dp0backend" || exit /b 1
if not exist ".venv\Scripts\python.exe" ( echo OrderFlow is not set up on this computer. & exit /b 1 )
".venv\Scripts\python.exe" -m app.manage backup
exit /b %ERRORLEVEL%
