@echo off
chcp 65001 >nul
rem ==========================================================================
rem  setup.bat - przygotowanie srodowiska do uruchomienia programu pod Windows
rem  Sprawdza, czy Python (3.10+, z tkinter) jest zainstalowany, i instaluje
rem  biblioteki programu z pliku requirements.txt (docx, xlsx, ezdxf, wyglad okna).
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

echo Instaluje biblioteki programu (requirements.txt)...
%PY% -m pip install --upgrade -r "%~dp0requirements.txt"
if errorlevel 1 (
  echo   UWAGA: nie udalo sie zainstalowac bibliotek - sprawdz polaczenie z internetem.
)
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
