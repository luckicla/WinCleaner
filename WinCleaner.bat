@echo off
:: WinCleaner v3.4 Launcher - Ejecuta con privilegios de administrador
NET SESSION >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo Solicitando permisos de administrador...
    powershell -Command "Start-Process cmd -ArgumentList '/c cd /d %~dp0 && python main.py' -Verb RunAs"
    EXIT /B
)
cd /d "%~dp0"
python main.py
pause
