@echo off
chcp 65001 >nul
rem ==========================================================================
rem  setup.bat - przygotowanie srodowiska do uruchomienia programu pod Windows
rem  Program nie wymaga zadnych bibliotek (sam Python 3.9+ ze standardowym
rem  tkinter). Ten skrypt tylko sprawdza, czy Python jest zainstalowany,
rem  oraz instaluje PyInstaller, jesli chcesz samodzielnie zbudowac plik .exe.
rem ==========================================================================
setlocal

call :find_python
if errorlevel 1 goto :nopython

echo Znaleziono Pythona:
%PY% --version
echo.

echo Sprawdzam modul tkinter (potrzebny do okna programu)...
%PY% -c "import tkinter; print('  tkinter OK, wersja Tk', tkinter.TkVersion)"
if errorlevel 1 (
  echo   UWAGA: brak modulu tkinter. Zainstaluj Pythona z opcja "tcl/tk and IDLE".
)
echo.

echo Instaluje PyInstaller (opcjonalnie - tylko do budowy pliku .exe)...
%PY% -m pip install --upgrade pip pyinstaller
echo.
echo Gotowe. Uruchom program plikiem  uruchom.bat  (okno) albo  generuj.bat  (wiersz polecen).
pause
exit /b 0

:nopython
echo Nie znaleziono Pythona. Zainstaluj Python 3.9+ ze strony https://www.python.org/
echo (podczas instalacji zaznacz "Add Python to PATH" oraz "tcl/tk and IDLE").
pause
exit /b 1

rem --------------------------------------------------------------------------
:find_python
where py >nul 2>nul && ( set "PY=py -3" & exit /b 0 )
where python >nul 2>nul && ( set "PY=python" & exit /b 0 )
exit /b 1
