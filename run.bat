@echo off
setlocal
cd /d "%~dp0"

rem ============================================================
rem  wisland launcher
rem    run.bat        start in background (no console window)
rem    run.bat /r     kill old instance, then start
rem    run.bat /d     start with console + debug output
rem    run.bat /s     start and open the settings window
rem ============================================================

set "WEXE=.venv\Scripts\Wisland.exe"
if not exist "%WEXE%" set "WEXE=.venv\Scripts\pythonw.exe"
if not exist "%WEXE%" goto nodeps

if /i "%~1"=="/r" goto restart
if /i "%~1"=="/d" goto debug
if /i "%~1"=="/s" goto settings
goto start

:restart
echo [wisland] stopping old instance...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe','Wisland.exe') -and $_.CommandLine -match 'run\.pyw' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 1 /nobreak >nul
if exist "data\wisland.lock" del /q "data\wisland.lock" >nul 2>&1
goto start

:debug
set "WISLAND_CONSOLE=1"
set "WISLAND_DEBUG=1"
echo [wisland] console mode - closing this window quits wisland.
".venv\Scripts\python.exe" "run.pyw"
goto end

:settings
if exist "data\wisland.lock" goto restart_then_settings
set "WISLAND_OPEN_SETTINGS=1"
start "" "%WEXE%" "run.pyw"
goto end

:restart_then_settings
echo [wisland] already running, restarting...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('python.exe','pythonw.exe','Wisland.exe') -and $_.CommandLine -match 'run\.pyw' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }" >nul 2>&1
timeout /t 1 /nobreak >nul
if exist "data\wisland.lock" del /q "data\wisland.lock" >nul 2>&1
set "WISLAND_OPEN_SETTINGS=1"
start "" "%WEXE%" "run.pyw"
goto end

:start
if exist "data\wisland.lock" echo [wisland] looks like it is already running - use: run.bat /r
start "" "%WEXE%" "run.pyw"
goto end

:nodeps
echo [wisland] .venv not found. Run setup.bat first.
pause

:end
endlocal
exit /b 0
