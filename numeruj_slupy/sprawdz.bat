@echo off
chcp 65001 >nul
rem ============================================================
rem  sprawdz.bat - szybka walidacja: numeruje wskazany plik i porownuje
rem                nadane numery z numerami juz obecnymi w rysunku
rem                (dziala na rysunku z PELNA numeracja - do testow).
rem  Uzycie:
rem     sprawdz.bat "rysunek z pelna numeracja.dxf"
rem ============================================================
setlocal
cd /d "%~dp0"

if "%~1"=="" (
    echo Podaj plik DXF do sprawdzenia, np.:
    echo     sprawdz.bat "zofinin - PZT.dxf"
    pause
    exit /b 1
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" _waliduj.py %1
    goto :po_uruchomieniu
)

set "PY="
call :wykryj_py
if not defined PY (
    echo Nie znaleziono srodowiska. Uruchom najpierw setup.bat
    pause
    exit /b 1
)
%PY% _waliduj.py %1

:po_uruchomieniu
pause
exit /b 0

rem ------------------------------------------------------------
:wykryj_py
py -3 --version >nul 2>&1
if %errorlevel%==0 (
    set "PY=py -3"
    goto :eof
)
python --version >nul 2>&1
if %errorlevel%==0 (
    set "PY=python"
    goto :eof
)
goto :eof
