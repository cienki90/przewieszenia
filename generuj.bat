@echo off
chcp 65001 >nul
rem ==========================================================================
rem  generuj.bat - wersja wiersza polecen (jeden modul na uruchomienie).
rem  Przeciagnij plik planu DXF na ten plik .bat albo podaj argumenty:
rem      generuj.bat "przewieszenia plan.dxf" przewieszenia
rem  Brakujacy plik lub modul program zapyta z klawiatury.
rem  Moduly: numeracja przewieszenia zestawienie obliczenia orientacje pzt
rem          opisy ppw zakladki
rem ==========================================================================
setlocal
cd /d "%~dp0"

call :find_python
if errorlevel 1 goto :nopython

if "%~1"=="" (
  set /p PLAN=Podaj sciezke do pliku planu DXF: 
) else (
  set "PLAN=%~1"
)

if "%PLAN%"=="" (
  echo Nie podano pliku planu.
  pause
  exit /b 1
)

set "MODUL=%~2"
if "%MODUL%"=="" (
  echo Moduly: numeracja przewieszenia zestawienie obliczenia orientacje pzt opisy ppw zakladki
  set /p MODUL=Ktory modul uruchomic: 
)

%PY% generator_cli.py "%PLAN%" --tylko %MODUL%
echo.
pause
exit /b 0

:nopython
echo Nie znaleziono Pythona. Najpierw uruchom setup.bat albo zainstaluj Python 3.9+.
pause
exit /b 1

:find_python
where py >nul 2>nul && ( set "PY=py -3" & exit /b 0 )
where python >nul 2>nul && ( set "PY=python" & exit /b 0 )
exit /b 1
