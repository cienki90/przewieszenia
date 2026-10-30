@echo off
chcp 65001 >nul
rem ==========================================================================
rem  sprawdz.bat - test poprawnosci: uruchamia kolejno moduly na pliku
rem  przykladowym "przyklady\przewieszenia plan.dxf" (bez internetu) i sprawdza,
rem  czy powstaly wszystkie trzy pliki wynikowe w katalogu _test.
rem ==========================================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

call :find_python
if errorlevel 1 goto :nopython

set "PLAN=przyklady\przewieszenia plan.dxf"
if not exist "%PLAN%" (
  echo Nie znaleziono pliku przykladowego "%PLAN%".
  pause
  exit /b 1
)

if not exist "_test" mkdir "_test"

for %%M in (przewieszenia zestawienie obliczenia) do (
  echo Uruchamiam modul %%M...
  %PY% generator_cli.py "%PLAN%" -o "_test" --tylko %%M --adresy brak --seed 1 --dxf
  if errorlevel 1 set "BLAD=1"
)
if defined BLAD (
  echo.
  echo TEST NIEUDANY: program zwrocil blad.
  pause
  exit /b 1
)

echo.
echo Sprawdzam pliki wynikowe...
set "OK=1"
call :check "_test\*Przewieszenia przewieszenia plan.dxf"
call :check "_test\zestawienie przewieszenia plan.xlsx"
call :check "_test\Obliczenia - zestawienie przewieszenia plan.xlsx"

echo.
if "!OK!"=="1" (
  echo WYNIK: OK - powstaly wszystkie trzy pliki.
) else (
  echo WYNIK: BLAD - brakuje przynajmniej jednego pliku wynikowego.
)
pause
exit /b 0

:check
if exist "%~1" (
  echo   [OK]   %~1
) else (
  echo   [BRAK] %~1
  set "OK=0"
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
