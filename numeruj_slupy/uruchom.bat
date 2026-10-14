@echo off
chcp 65001 >nul
rem ============================================================
rem  uruchom.bat - uruchamia program (GUI, gdy bez argumentu;
rem                lub numeruje wskazane pliki DXF podane jako argumenty)
rem  Uzycie:
rem     uruchom.bat                      -> okno wyboru pliku (GUI)
rem     uruchom.bat "rysunek.dxf"        -> numeruje jeden plik
rem ============================================================
setlocal
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" (
    set "PYEXE=.venv\Scripts\python.exe"
) else (
    rem brak .venv - sprobuj systemowego Pythona (wymaga ezdxf)
    set "PYEXE="
    py -3 --version >nul 2>&1 && set "PYEXE=py -3"
    if not defined PYEXE python --version >nul 2>&1 && set "PYEXE=python"
    if not defined PYEXE (
        echo Nie znaleziono srodowiska. Uruchom najpierw setup.bat
        pause
        exit /b 1
    )
    echo UWAGA: brak .venv - uzywam systemowego Pythona ^(musi miec ezdxf^).
)

%PYEXE% numeruj.py %*
if errorlevel 1 (
    echo.
    echo Program zakonczyl sie bledem.
    pause
    exit /b 1
)
pause
