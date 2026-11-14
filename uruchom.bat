@echo off
chcp 65001 >nul
rem ==========================================================================
rem  uruchom.bat - otwiera OKNO programu bez okna terminala.
rem  Program startuje przez pythonw (Python bez konsoli); to okienko zamyka sie
rem  od razu. Blad przy starcie pokaze sie w okienku programu i w pliku
rem  "blad uruchomienia.txt". Z konsola (do diagnozy):  python generator_gui.py
rem ==========================================================================
setlocal
cd /d "%~dp0"

where pyw >nul 2>nul && ( start "" pyw -3 generator_gui.pyw & exit /b 0 )
where pythonw >nul 2>nul && ( start "" pythonw generator_gui.pyw & exit /b 0 )

rem brak pythonw - stary sposob, z oknem terminala
call :find_python
if errorlevel 1 goto :nopython

%PY% generator_gui.py
if errorlevel 1 (
  echo.
  echo Program zakonczyl sie bledem. Przewin wyzej, aby zobaczyc szczegoly.
  pause
)
exit /b 0

:nopython
echo Nie znaleziono Pythona. Najpierw uruchom setup.bat albo zainstaluj Python 3.9+.
pause
exit /b 1

:find_python
where py >nul 2>nul && ( set "PY=py -3" & exit /b 0 )
where python >nul 2>nul && ( set "PY=python" & exit /b 0 )
exit /b 1
