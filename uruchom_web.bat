@echo off
rem Generator nN w przegladarce na tym komputerze: http://localhost:8765
chcp 65001 >nul
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
start "" http://localhost:8765
%PY% generator_web.py %*
