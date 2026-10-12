@echo off
chcp 65001 >nul
rem ============================================================
rem  Przewieszenia - sprawdzenie programu (test)
rem  Uruchamia generator na dolaczonym planie, bez internetu,
rem  i sprawdza, czy powstal plik wynikowy. Taki sam test jak w CI.
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
    echo.
    pause
    exit /b 1
)

echo Wersja Pythona:
%PY% --version
echo.

set "PLAN=przewieszenia plan.dxf"
set "TEST=_test wynik.dxf"

if not exist "%PLAN%" (
    echo [BLAD] Brak pliku testowego "%PLAN%".
    pause
    exit /b 1
)

echo Test: generowanie bez internetu (--adresy brak)...
echo.
%PY% "przewieszenia.py" "%PLAN%" -o "%TEST%" --adresy brak
set "KOD=%ERRORLEVEL%"
echo.

if not "%KOD%"=="0" (
    echo [BLAD] Program zakonczyl sie kodem %KOD%.
    pause
    exit /b %KOD%
)

if exist "%TEST%" (
    echo [OK] Powstal plik wynikowy "%TEST%" - program dziala poprawnie.
    del "%TEST%" >nul 2>&1
) else (
    echo [BLAD] Program zakonczyl sie bez bledu, ale nie powstal plik "%TEST%".
    set "KOD=1"
)

echo.
pause
endlocal
exit /b %KOD%
