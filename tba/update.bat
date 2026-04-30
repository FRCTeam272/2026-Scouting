@echo off
setlocal enableextensions enabledelayedexpansion

cd /d "%~dp0"

if not defined PYTHON set "PYTHON=python3"
if not defined LOG_FILE set "LOG_FILE=update.log"
if not defined DB_PATH set "DB_PATH=matches.db"
if not defined COUNT_FILE set "COUNT_FILE=matches-count"

for /f "usebackq tokens=*" %%a in (`powershell -NoProfile -Command "Get-Date -Format 'yyyy-MM-dd HH:mm:ss'"`) do set "TIMESTAMP=%%a"

if exist "%LOG_FILE%" (
    for /f %%c in ('type "%LOG_FILE%" ^| find /c /v ""') do set /a LOG_LINES=%%c
    if !LOG_LINES! gtr 500 (type nul > "%LOG_FILE%")
)

set "PYTEMP=%TEMP%\get_match_counts.py"
(
    echo import sqlite3
    echo import sys
    echo db_path = sys.argv[1]
    echo try:
    echo     con = sqlite3.connect(db_path)
    echo     total = con.execute("SELECT COUNT(*) FROM matches").fetchone()
    echo     completed = con.execute("SELECT COUNT(*) FROM matches WHERE actual_time IS NOT NULL").fetchone()
    echo     print(f"{total[0] if total else 0} {completed[0] if completed else 0}")
    echo except Exception:
    echo     print("0 0")
    echo finally:
    echo     try:
    echo         con.close()
    echo     except Exception:
    echo         pass
) > "%PYTEMP%"

echo [%TIMESTAMP%] === TBA update started ===

call :get_match_counts "%DB_PATH%" BEFORE_COUNT BEFORE_COMPLETED
echo [%TIMESTAMP%] Matches in DB before import: %BEFORE_COUNT% total, %BEFORE_COMPLETED% completed

git pull --force
if errorlevel 1 goto :error

echo [%TIMESTAMP%] Running import_matches.py...
%PYTHON% import_matches.py
if errorlevel 1 goto :error

call :get_match_counts "%DB_PATH%" AFTER_COUNT AFTER_COMPLETED
echo [%TIMESTAMP%] Matches in DB after import: %AFTER_COUNT% total, %AFTER_COMPLETED% completed

echo [%TIMESTAMP%] Running create_view.py...
%PYTHON% create_view.py
if errorlevel 1 goto :error

echo [%TIMESTAMP%] Staging changes...
git add -u
git add *.html update.log

set /a DELTA_TOTAL=%AFTER_COUNT% - %BEFORE_COUNT%
set /a DELTA_COMPLETED=%AFTER_COMPLETED% - %BEFORE_COMPLETED%

if %DELTA_TOTAL% geq 0 set "DELTA_TOTAL=+%DELTA_TOTAL%"
if %DELTA_COMPLETED% geq 0 set "DELTA_COMPLETED=+%DELTA_COMPLETED%"

set "MSG=Auto-update: matches %BEFORE_COUNT%->%AFTER_COUNT% (%DELTA_TOTAL%), completed %BEFORE_COMPLETED%->%AFTER_COMPLETED% (%DELTA_COMPLETED%) [%TIMESTAMP%]"
git commit -m "%MSG%"
if errorlevel 1 goto :error

echo [%TIMESTAMP%] Pushing to origin (match data updated)...
git push origin main
if errorlevel 1 goto :error

echo [%TIMESTAMP%] Push complete.
echo [%TIMESTAMP%] === TBA update finished ===
del "%PYTEMP%" 2>nul
endlocal
exit /b 0

:error
echo [%TIMESTAMP%] ERROR: Script failed.
del "%PYTEMP%" 2>nul
endlocal
exit /b 1

:get_match_counts
:: %1=DB path  %2=output var for total  %3=output var for completed
if not exist "%~1" (
    set "%~2=0"
    set "%~3=0"
    goto :eof
)
for /f "tokens=1,2" %%a in ('%PYTHON% "%PYTEMP%" "%~1"') do (
    set "%~2=%%a"
    set "%~3=%%b"
)
goto :eof
