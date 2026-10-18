@echo off
chcp 65001 >nul
rem ==========================================================================
rem  uruchom.bat - otwiera OKNO programu (przewieszenia + zestawienie + obliczenia)
rem ==========================================================================
setlocal
cd /d "%~dp0"

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
