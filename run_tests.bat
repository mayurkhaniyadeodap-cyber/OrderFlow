@echo off
REM Runs backend tests and the frontend type-check + production build.
setlocal
cd /d "%~dp0backend" || exit /b 1
echo === Backend tests ===
".venv\Scripts\python.exe" -m pytest || ( echo BACKEND TESTS FAILED & pause & exit /b 1 )
cd /d "%~dp0frontend" || exit /b 1
echo === Frontend tests ===
call npm test || ( echo FRONTEND TESTS FAILED & pause & exit /b 1 )
echo === Frontend build ===
call npm run build || ( echo FRONTEND BUILD FAILED & pause & exit /b 1 )
echo.
echo All checks passed.
pause
