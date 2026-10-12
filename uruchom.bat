@echo off
chcp 65001 >nul
rem ============================================================
rem  Przewieszenia - uruchomienie wersji okienkowej (GUI)
rem  Dwuklik na ten plik: otworzy sie okno z wyborem planu DXF.
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

echo Uruchamiam generator przewieszen (okno)...
%PY% "przewieszenia_gui.py"
set "KOD=%ERRORLEVEL%"
if not "%KOD%"=="0" (
    echo.
    echo [BLAD] Program zakonczyl sie kodem %KOD%.
    pause
)
endlocal
