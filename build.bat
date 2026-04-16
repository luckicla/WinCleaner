@echo off
:: ============================================================
::  build.bat — Construye WinClean.exe con PyInstaller
::  Ejecutar desde la carpeta raíz del proyecto (donde está main.py)
:: ============================================================

setlocal enabledelayedexpansion
title WinClean Builder

echo.
echo  ╔══════════════════════════════════════════╗
echo  ║        WinClean — Build Script           ║
echo  ╚══════════════════════════════════════════╝
echo.

:: ── 1. Comprueba Python ──────────────────────────────────────
where python >nul 2>&1
IF ERRORLEVEL 1 (
    echo [ERROR] Python no encontrado en PATH.
    echo         Instala Python 3.11 desde https://python.org y marca "Add to PATH".
    pause & exit /b 1
)

for /f "tokens=*" %%v in ('python -c "import sys; print(sys.version)"') do set PYVER=%%v
echo [OK] Python: %PYVER%

:: ── 2. Instala/actualiza dependencias ────────────────────────
echo.
echo [*] Instalando dependencias...
python -m pip install --upgrade pip --quiet
python -m pip install pyinstaller pystray pillow --quiet

IF ERRORLEVEL 1 (
    echo [ERROR] Fallo al instalar dependencias.
    pause & exit /b 1
)
echo [OK] Dependencias instaladas.

:: ── 3. Limpia builds anteriores ──────────────────────────────
echo.
echo [*] Limpiando builds anteriores...
if exist "dist\WinClean.exe" del /f /q "dist\WinClean.exe"
if exist "build" rmdir /s /q "build"
echo [OK] Limpieza completada.

:: ── 4. Ejecuta PyInstaller ───────────────────────────────────
echo.
echo [*] Compilando EXE (puede tardar 1-3 minutos)...
echo.
python -m PyInstaller WinClean.spec --noconfirm

IF ERRORLEVEL 1 (
    echo.
    echo [ERROR] PyInstaller falló. Revisa los mensajes de arriba.
    pause & exit /b 1
)

:: ── 5. Resultado ─────────────────────────────────────────────
echo.
if exist "dist\WinClean.exe" (
    for %%F in ("dist\WinClean.exe") do set SIZE=%%~zF
    set /a SIZE_MB=!SIZE! / 1048576
    echo  ╔══════════════════════════════════════════╗
    echo  ║  ✓  BUILD EXITOSO                        ║
    echo  ║                                          ║
    echo  ║  dist\WinClean.exe  (!SIZE_MB! MB aprox.) ║
    echo  ╚══════════════════════════════════════════╝
    echo.
    echo  Copia "dist\WinClean.exe" a cualquier PC con Windows 10/11.
    echo  No necesita Python instalado. Pide UAC automáticamente.
) ELSE (
    echo [ERROR] El EXE no se generó. Algo salió mal.
)

echo.
pause
