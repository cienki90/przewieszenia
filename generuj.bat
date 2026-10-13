@echo off
chcp 65001 >nul
rem ==========================================================================
rem  generuj.bat - wersja wiersza polecen. Przeciagnij plik planu DXF na ten
rem  plik .bat albo podaj sciezke jako argument:
rem      generuj.bat "przewieszenia plan.dxf"
rem  Bez argumentu program zapyta o plik.
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

%PY% generator_cli.py "%PLAN%"
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
