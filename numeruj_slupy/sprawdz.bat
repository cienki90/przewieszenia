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
    set "PYEXE=.venv\Scripts\python.exe"
) else (
    set "PYEXE="
    py -3 --version >nul 2>&1 && set "PYEXE=py -3"
    if not defined PYEXE python --version >nul 2>&1 && set "PYEXE=python"
    if not defined PYEXE (
        echo Nie znaleziono srodowiska. Uruchom najpierw setup.bat
        pause
        exit /b 1
    )
)

%PYEXE% _waliduj.py %1
pause
