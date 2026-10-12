@echo off
chcp 65001 >nul
rem ============================================================
rem  Przewieszenia - generowanie z wiersza polecen
rem
rem  Sposoby uzycia:
rem   1. Przeciagnij plik planu .dxf na ten plik .bat
rem   2. Dwuklik - uzyje domyslnego "przewieszenia plan.dxf"
rem   3. Z konsoli:  generuj.bat "sciezka\plan.dxf"
rem ============================================================
setlocal
cd /d "%~dp0"

rem --- wykrycie Pythona (py -3 albo python) ---
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo.
    echo [BLAD] Nie znaleziono Pythona. Zainstaluj Python 3.9 lub nowszy:
    echo        https://www.python.org/downloads/
    echo        (podczas instalacji zaznacz "Add Python to PATH").
    echo.
    pause
    exit /b 1
)

rem --- plik planu: argument albo domyslny ---
set "PLAN=%~1"
if "%PLAN%"=="" set "PLAN=przewieszenia plan.dxf"

if not exist "%PLAN%" (
    echo.
    echo [BLAD] Nie znaleziono pliku planu: "%PLAN%"
    echo Przeciagnij plik .dxf na generuj.bat albo podaj go jako argument.
    echo.
    pause
    exit /b 1
)

echo Plan:  "%PLAN%"
echo Generuje przewieszenia...
echo.
%PY% "przewieszenia.py" "%PLAN%"
set "KOD=%ERRORLEVEL%"

echo.
if "%KOD%"=="0" (
    echo [OK] Gotowe.
) else (
    echo [BLAD] Program zakonczyl sie kodem %KOD%.
)
pause
endlocal
exit /b %KOD%
