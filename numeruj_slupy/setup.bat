@echo off
chcp 65001 >nul
rem ============================================================
rem  setup.bat - instalacja zależności (ezdxf) w wirtualnym środowisku
rem ============================================================
setlocal
cd /d "%~dp0"

rem --- wykryj Pythona (py -3 lub python)
set "PY="
py -3 --version >nul 2>&1 && set "PY=py -3"
if not defined PY (
    python --version >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo Nie znaleziono Pythona. Zainstaluj Python 3.8+ ze strony python.org
    echo (zaznacz "Add Python to PATH") i uruchom setup.bat ponownie.
    pause
    exit /b 1
)

echo Uzywam: %PY%
echo Tworze wirtualne srodowisko .venv ...
%PY% -m venv .venv
if errorlevel 1 (
    echo Nie udalo sie utworzyc .venv
    pause
    exit /b 1
)

echo Instaluje zaleznosci (ezdxf) ...
call ".venv\Scripts\python.exe" -m pip install --upgrade pip
call ".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
    echo Instalacja zaleznosci nie powiodla sie.
    pause
    exit /b 1
)

echo.
echo Gotowe. Mozesz uruchomic program: uruchom.bat
pause
