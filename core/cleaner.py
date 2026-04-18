"""
core/cleaner.py — Lógica de limpieza equivalente a win-cleaner-safe.bat
Ejecuta cada paso en Python nativo (shutil, subprocess) y emite líneas de log
mediante un callback on_log(line: str) para mostrarlas en tiempo real en la UI.

Cada paso devuelve (bytes_freed: int, lines: list[str]).
"""

import os
import shutil
import subprocess
import threading

# ── Helpers ────────────────────────────────────────────────────────────────────

def _folder_size(path: str) -> int:
    """Tamaño total de una carpeta en bytes (ignora errores de permisos)."""
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                try:
                    total += os.path.getsize(os.path.join(dirpath, f))
                except OSError:
                    pass
    except OSError:
        pass
    return total


def _fmt_bytes(n: int) -> str:
    if n >= 1_073_741_824:
        return f"{n/1_073_741_824:.2f} GB"
    if n >= 1_048_576:
        return f"{n/1_048_576:.1f} MB"
    if n >= 1_024:
        return f"{n/1_024:.1f} KB"
    return f"{n} B"


def _delete_folder_contents(path: str, on_log, stop_event: threading.Event) -> int:
    """Elimina el contenido de una carpeta. Devuelve bytes liberados."""
    freed = 0
    if not os.path.isdir(path):
        return 0
    for entry in os.scandir(path):
        if stop_event.is_set():
            break
        try:
            size = _folder_size(entry.path) if entry.is_dir(follow_symlinks=False) else entry.stat(follow_symlinks=False).st_size
            if entry.is_dir(follow_symlinks=False):
                shutil.rmtree(entry.path, ignore_errors=True)
            else:
                os.remove(entry.path)
            freed += size
            on_log(f"    ✓  {entry.path}  ({_fmt_bytes(size)})")
        except Exception as e:
            on_log(f"    ✗  {entry.path}  ({e})")
    return freed


def _delete_folder(path: str, on_log, stop_event: threading.Event) -> int:
    """Elimina una carpeta completa. Devuelve bytes liberados."""
    if not os.path.isdir(path):
        return 0
    size = _folder_size(path)
    try:
        shutil.rmtree(path, ignore_errors=True)
        on_log(f"    ✓  {path}  ({_fmt_bytes(size)})")
    except Exception as e:
        on_log(f"    ✗  {path}  ({e})")
        return 0
    return size


# ── Pasos de limpieza ──────────────────────────────────────────────────────────

def step_user_temp(on_log, stop_event: threading.Event) -> int:
    """[1/6] Temporales del usuario."""
    on_log("  Carpetas: %TEMP%, %TMP%, %APPDATA%\\Temp, %LOCALAPPDATA%\\Temp")
    freed = 0
    paths = [
        os.environ.get("TEMP", ""),
        os.environ.get("TMP", ""),
        os.path.join(os.environ.get("APPDATA", ""), "Temp"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Temp"),
        os.path.join(os.environ.get("USERPROFILE", ""), "AppData", "LocalLow", "Temp"),
    ]
    for p in paths:
        if p and os.path.isdir(p):
            on_log(f"  → {p}")
            freed += _delete_folder_contents(p, on_log, stop_event)
        if stop_event.is_set():
            break
    on_log(f"  ✅ Liberado: {_fmt_bytes(freed)}")
    return freed


def step_system_temp(on_log, stop_event: threading.Event) -> int:
    """[2/6] Temporales del sistema."""
    on_log("  Carpetas: %WINDIR%\\Temp, *.tmp en raíz")
    freed = 0
    windir = os.environ.get("WINDIR", r"C:\Windows")
    sys_temp = os.path.join(windir, "Temp")
    if os.path.isdir(sys_temp):
        on_log(f"  → {sys_temp}")
        freed += _delete_folder_contents(sys_temp, on_log, stop_event)

    # *.tmp en raíz del sistema
    sysdrive = os.environ.get("SYSTEMDRIVE", "C:")
    for fname in os.listdir(sysdrive + os.sep):
        if stop_event.is_set():
            break
        if fname.lower().endswith((".tmp", "._mp")):
            fpath = os.path.join(sysdrive + os.sep, fname)
            try:
                size = os.path.getsize(fpath)
                os.remove(fpath)
                freed += size
                on_log(f"    ✓  {fpath}")
            except Exception as e:
                on_log(f"    ✗  {fpath}  ({e})")

    on_log(f"  ✅ Liberado: {_fmt_bytes(freed)}")
    return freed


def step_recycle_bin(on_log, stop_event: threading.Event) -> int:
    """[3/6] Vaciar la Papelera de Reciclaje."""
    on_log("  Vaciando Papelera de Reciclaje...")
    try:
        result = subprocess.run(
            ["PowerShell", "-NoProfile", "-Command",
             "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode == 0:
            on_log("  ✅ Papelera vaciada.")
        else:
            on_log(f"  ⚠  PowerShell: {result.stderr.strip()[:120]}")
    except Exception as e:
        on_log(f"  ✗  Error: {e}")
    return 0  # no podemos medir fácilmente el tamaño de la papelera


def step_driver_leftovers(on_log, stop_event: threading.Event) -> int:
    """[4/6] Restos de instaladores de drivers (C:\\AMD, C:\\NVIDIA, C:\\INTEL)."""
    on_log("  Eliminando C:\\AMD, C:\\NVIDIA, C:\\INTEL (si existen)")
    on_log("  ⚠  NO afecta a los drivers ya instalados en el sistema.")
    freed = 0
    sysdrive = os.environ.get("SYSTEMDRIVE", "C:")
    for name in ("AMD", "NVIDIA", "INTEL"):
        path = os.path.join(sysdrive + os.sep, name)
        if stop_event.is_set():
            break
        freed += _delete_folder(path, on_log, stop_event)
    on_log(f"  ✅ Liberado: {_fmt_bytes(freed)}")
    return freed


def step_windows_update_cache(on_log, stop_event: threading.Event) -> int:
    """[5/6] Caché de Windows Update."""
    on_log("  Deteniendo servicios de Windows Update...")
    for svc in ("wuauserv", "bits"):
        subprocess.run(["net", "stop", svc], capture_output=True)
        on_log(f"    → {svc} detenido")

    freed = 0
    path = os.path.join(os.environ.get("WINDIR", r"C:\Windows"),
                        "SoftwareDistribution", "Download")
    if os.path.isdir(path):
        on_log(f"  → {path}")
        freed += _delete_folder_contents(path, on_log, stop_event)

    on_log("  Reiniciando servicios de Windows Update...")
    for svc in ("wuauserv", "bits"):
        subprocess.run(["net", "start", svc], capture_output=True)
        on_log(f"    → {svc} iniciado")

    on_log(f"  ✅ Caché de actualizaciones vaciada. Liberado: {_fmt_bytes(freed)}")
    return freed


def step_dism(on_log, stop_event: threading.Event) -> int:
    """[6/6] Limpieza DISM de componentes del sistema."""
    on_log("  ⚠  Es normal que el progreso se quede en 10% durante mucho tiempo.")
    on_log("  ⚠  Dependiendo del PC puede tardar entre 10 min y 2 horas.")
    on_log("  ⚠  NO cierres la ventana mientras esté en marcha.")
    on_log("")
    on_log("  Ejecutando DISM /StartComponentCleanup ...")

    try:
        proc = subprocess.Popen(
            ["dism", "/online", "/cleanup-image", "/startcomponentcleanup"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        for line in proc.stdout:
            if stop_event.is_set():
                proc.terminate()
                on_log("  ⚠  Cancelado por el usuario.")
                break
            line = line.rstrip()
            if line:
                on_log(f"    {line}")
        proc.wait()
        if proc.returncode == 0:
            on_log("  ✅ Limpieza DISM completada correctamente.")
        else:
            on_log(f"  ⚠  DISM terminó con código {proc.returncode}.")
            on_log("     (Puede que ya estuviera limpio o requiera reinicio.)")
    except FileNotFoundError:
        on_log("  ✗  DISM no encontrado (¿no es Windows?).")
    except Exception as e:
        on_log(f"  ✗  Error inesperado: {e}")

    return 0


def step_defrag(on_log, stop_event: threading.Event) -> int:
    """[Opcional] Optimización de disco C: (TRIM en SSD / defrag en HDD)."""
    on_log("  Ejecutando defrag C: /O /U /V ...")
    on_log("  (SSD: TRIM | HDD: Desfragmentación)")
    try:
        proc = subprocess.Popen(
            ["defrag", "C:", "/O", "/U", "/V"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        for line in proc.stdout:
            if stop_event.is_set():
                proc.terminate()
                on_log("  ⚠  Cancelado por el usuario.")
                break
            line = line.rstrip()
            if line:
                on_log(f"    {line}")
        proc.wait()
        on_log("  ✅ Optimización completada.")
    except FileNotFoundError:
        on_log("  ✗  defrag no encontrado.")
    except Exception as e:
        on_log(f"  ✗  Error: {e}")
    return 0


# ── Definición pública de los pasos ───────────────────────────────────────────

CLEANER_STEPS = [
    {
        "id": "user_temp",
        "label": "[1/6] Archivos temporales del usuario",
        "detail": "%TEMP%, %TMP%, %APPDATA%\\Temp, %LOCALAPPDATA%\\Temp",
        "fn": step_user_temp,
        "default": True,
    },
    {
        "id": "system_temp",
        "label": "[2/6] Archivos temporales del sistema",
        "detail": "%WINDIR%\\Temp, *.tmp en raíz de unidad",
        "fn": step_system_temp,
        "default": True,
    },
    {
        "id": "recycle_bin",
        "label": "[3/6] Vaciar la Papelera de Reciclaje",
        "detail": "Elimina todos los archivos de la Papelera",
        "fn": step_recycle_bin,
        "default": True,
    },
    {
        "id": "driver_leftovers",
        "label": "[4/6] Restos de instaladores de drivers",
        "detail": "C:\\AMD, C:\\NVIDIA, C:\\INTEL  —  NO afecta a los drivers instalados",
        "fn": step_driver_leftovers,
        "default": True,
    },
    {
        "id": "update_cache",
        "label": "[5/6] Caché de Windows Update",
        "detail": "Elimina actualizaciones ya instaladas de SoftwareDistribution\\Download",
        "fn": step_windows_update_cache,
        "default": True,
    },
    {
        "id": "dism",
        "label": "[6/6] Limpieza DISM de componentes",
        "detail": "Elimina versiones antiguas de componentes. Puede tardar hasta 2 h.",
        "fn": step_dism,
        "default": False,  # opt-in por defecto (lento)
    },
    {
        "id": "defrag",
        "label": "[Opcional] Optimizar disco C:",
        "detail": "SSD: ejecuta TRIM  |  HDD: desfragmenta",
        "fn": step_defrag,
        "default": False,
    },
]
