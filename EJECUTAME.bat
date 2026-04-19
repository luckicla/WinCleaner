@echo off
setlocal enabledelayedexpansion
chcp 65001 >nul 2>&1
title WinClean — Instalador

echo.
echo  ============================================
echo   WinClean — Instalador de dependencias
echo  ============================================
echo.

:: -- 1. Comprobar si Python ya esta instalado ------------------
python --version >nul 2>&1
IF NOT ERRORLEVEL 1 (
    for /f "tokens=*" %%v in ('python --version 2^>^&1') do set PYVER=%%v
    echo [OK] Python ya instalado: !PYVER!
    goto :instalar_deps
)

:: -- 2. Elegir version de Python --------------------------------
echo  Python no esta instalado. Elige que version quieres instalar:
echo.
echo    [1] Python 3.13  (recomendada) - mas reciente, mejor rendimiento
echo    [2] Python 3.12
echo    [3] Python 3.11
echo    [4] Python 3.10
echo.
set /p OPCION="  Tu eleccion (Enter para instalar la 3.13): "

IF "%OPCION%"==""  set OPCION=1
IF "%OPCION%"=="1" ( set PY_VER=3.13.3 )
IF "%OPCION%"=="2" ( set PY_VER=3.12.10 )
IF "%OPCION%"=="3" ( set PY_VER=3.11.9 )
IF "%OPCION%"=="4" ( set PY_VER=3.10.16 )

IF NOT DEFINED PY_VER (
    echo [ERROR] Opcion no valida. Reinicia el instalador.
    pause & exit /b 1
)

echo.
echo [*] Descargando Python !PY_VER!...
echo     (puede tardar un momento segun tu conexion)
echo.

set PY_URL=https://www.python.org/ftp/python/!PY_VER!/python-!PY_VER!-amd64.exe
set PY_INSTALLER=%TEMP%\python-installer.exe

powershell -Command "Invoke-WebRequest -Uri '!PY_URL!' -OutFile '%PY_INSTALLER%' -UseBasicParsing" >nul 2>&1

IF NOT EXIST "%PY_INSTALLER%" (
    echo [ERROR] No se pudo descargar Python.
    echo         Comprueba tu conexion a internet o descargalo desde https://python.org
    pause & exit /b 1
)

echo [*] Instalando Python !PY_VER! en silencio...
"%PY_INSTALLER%" /quiet InstallAllUsers=0 PrependPath=1 Include_test=0

IF ERRORLEVEL 1 (
    echo [ERROR] Fallo la instalacion de Python.
    del /f /q "%PY_INSTALLER%"
    pause & exit /b 1
)
del /f /q "%PY_INSTALLER%"

for /f "tokens=*" %%p in ('powershell -Command "[System.Environment]::GetEnvironmentVariable(\"PATH\",\"User\")"') do set "PATH=%%p;%PATH%"

python --version >nul 2>&1
IF ERRORLEVEL 1 (
    echo.
    echo [AVISO] Python instalado pero necesita reiniciar el CMD.
    echo         Cierra esta ventana, vuelve a abrirla y ejecuta EJECUTAME.bat otra vez.
    pause & exit /b 0
)

echo [OK] Python !PY_VER! instalado correctamente.

:: -- 3. Instalar dependencias pip ------------------------------
:instalar_deps
echo.
echo [*] Instalando dependencias de WinClean...

python -m pip install --upgrade pip --quiet --no-warn-script-location
python -m pip install pystray pillow --quiet --no-warn-script-location

IF ERRORLEVEL 1 (
    echo [ERROR] Fallo la instalacion de dependencias.
    echo         Asegurate de tener conexion a internet.
    pause & exit /b 1
)

echo [OK] pystray instalado.
echo [OK] pillow instalado.

:: -- 4. Mensaje final ------------------------------------------
echo.
echo  ==============================================================
echo   Gracias por confiar en mi aplicacion para optimizar
echo   tu sistema :33. Ahora deberias ejecutar WinCleaner.bat
echo   y si quieres que inicie con windows dale arriba a la
echo   derecha al icono, enserio MUCHAS GRACIAS ^<33
echo  ==============================================================
echo.
pause