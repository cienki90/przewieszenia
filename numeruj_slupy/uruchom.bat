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
    ".venv\Scripts\python.exe" numeruj.py %*
    goto :po_uruchomieniu
)

rem brak .venv - sprobuj systemowego Pythona (wymaga ezdxf)
set "PY="
call :wykryj_py
if not defined PY (
    echo Nie znaleziono srodowiska. Uruchom najpierw setup.bat
    pause
    exit /b 1
)
echo UWAGA: brak .venv - uzywam systemowego Pythona ^(musi miec ezdxf^).
%PY% numeruj.py %*

:po_uruchomieniu
if errorlevel 1 (
    echo.
    echo Program zakonczyl sie bledem.
    pause
    exit /b 1
)
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
