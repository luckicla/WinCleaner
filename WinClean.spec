# WinClean.spec
# Archivo de configuración PyInstaller para generar WinClean.exe
# Uso: pyinstaller WinClean.spec
#
# Este spec genera un EXE de un solo fichero (onefile) que:
#   - Incluye Python 3.11 embebido
#   - Incluye pystray + Pillow (tray icon)
#   - Solicita UAC (requireAdministrator) automáticamente
#   - Muestra un icono personalizado (si existe winclean.ico)
#   - NO abre ventana de consola (windowed)

import os
from PyInstaller.building.api import PYZ, EXE, COLLECT
from PyInstaller.building.build_main import Analysis

block_cipher = None

# ─── Rutas ────────────────────────────────────────────────────────────────────
ROOT = os.path.abspath(".")
ICON = os.path.join(ROOT, "assets", "winclean.ico")   # Opcional — pon tu .ico aquí
HAS_ICON = os.path.isfile(ICON)

# ─── Análisis de dependencias ─────────────────────────────────────────────────
a = Analysis(
    ["main.py"],
    pathex=[ROOT],
    binaries=[],
    # Incluye carpetas como datos (UI, core)
    datas=[
        (os.path.join(ROOT, "core"),  "core"),
        (os.path.join(ROOT, "ui"),    "ui"),
        # Si tienes assets/imágenes/iconos descomenta la línea siguiente:
        # (os.path.join(ROOT, "assets"), "assets"),
    ],
    hiddenimports=[
        # pystray usa backends distintos según el OS; forzamos el de Windows
        "pystray._win32",
        # Pillow
        "PIL._tkinter_finder",
        "PIL.Image",
        "PIL.ImageDraw",
        # tkinter (a veces PyInstaller no lo detecta automáticamente)
        "tkinter",
        "tkinter.ttk",
        "tkinter.messagebox",
        "tkinter.filedialog",
        # Módulos estándar que pueden perderse en onefile
        "winreg",
        "ctypes",
        "ctypes.wintypes",
        "threading",
        "subprocess",
        "json",
        "tempfile",
        "logging",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Elimina módulos que no se usan para reducir tamaño
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "wx",
        "gi",
        "gtk",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="WinClean",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,               # Comprime con UPX si está instalado (reduce ~30% el tamaño)
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # Sin ventana de consola negra
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=ICON if HAS_ICON else None,
    # ── Manifiesto UAC ────────────────────────────────────────────────────────
    # "requireAdministrator" hace que Windows pida UAC al doble-clicar el EXE
    # sin necesidad de que el propio Python lo haga por código.
    uac_admin=True,
    onefile=True,           # Todo en un único .exe
    version=None,           # Puedes apuntar a un version_info.txt si quieres
)
