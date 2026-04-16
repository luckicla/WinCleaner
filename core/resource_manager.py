"""
Resource Manager: per-process CPU, RAM and GPU limits.
Uses Windows Job Objects (CPU affinity + working set) and
optionally nvidia-smi / wmic for GPU.

Auto mode: sets sensible defaults based on process category.
Manual mode: user picks max CPU%, RAM MB and GPU%.
"""
import subprocess
import ctypes
import ctypes.wintypes
import os
import threading
import logging

logger = logging.getLogger("winclean.resources")

# ── Known app minimum requirements (RAM MB) ──────────────────────────────────
# These are the MINIMUM we'll ever allow the user to set.
APP_MINIMUMS = {
    "chrome":       800,
    "msedge":       600,
    "firefox":      400,
    "brave":        400,
    "opera":        400,
    "vivaldi":      400,
    "discord":      300,
    "teams":        500,
    "slack":        400,
    "zoom":         400,
    "spotify":      300,
    "steam":        200,
    "epicgameslauncher": 300,
    "code":         400,   # VS Code
    "devenv":       800,   # Visual Studio
    "pycharm":      600,
    "idea":         600,
    "androidstudio":800,
    "obs":          300,
    "vlc":          100,
    "photoshop":    1500,
    "premiere":     2000,
    "afterfx":      2000,
    "illustrator":  800,
    "lightroom":    1000,
    "blender":      800,
    "unity":        1000,
    "unreal":       2000,
    "explorer":     100,
    "svchost":      50,
    "taskmgr":      50,
    "notepad":      30,
    "winword":      300,
    "excel":        300,
    "powerpnt":     300,
    "outlook":      300,
    "onenote":      200,
}

# ── Subprocess helpers ────────────────────────────────────────────────────────

def _run(cmd, timeout=10):
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True,
            timeout=timeout, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        return -1, str(e)

def _ps(script, timeout=15):
    return _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )

# ── Process list ──────────────────────────────────────────────────────────────

def get_running_processes():
    """
    Returns list of dicts:
      { pid, name, exe, cpu_pct, ram_mb, ram_min_mb, gpu_pct }
    Only returns user-visible processes (not system idle, etc.)
    """
    script = """
$procs = Get-Process | Where-Object { $_.MainWindowHandle -ne 0 -or $_.Name -notmatch '^(Idle|System|Registry|smss|csrss|wininit|services|lsass|winlogon|fontdrvhost|dwm|conhost)$' } |
    Select-Object Id, Name, Path,
        @{N='CPUSeconds';E={$_.TotalProcessorTime.TotalSeconds}},
        @{N='RAMMB';E={[math]::Round($_.WorkingSet64/1MB,1)}} |
    Sort-Object RAMMB -Descending |
    Select-Object -First 40
$procs | ForEach-Object {
    "$($_.Id)|$($_.Name)|$($_.Path)|$($_.CPUSeconds)|$($_.RAMMB)"
}
"""
    code, out = _ps(script, timeout=20)
    procs = []
    seen = set()
    for line in out.strip().splitlines():
        parts = line.strip().split("|")
        if len(parts) < 5:
            continue
        try:
            pid   = int(parts[0])
            name  = parts[1].strip()
            path  = parts[2].strip() if parts[2].strip() else ""
            ram   = float(parts[4]) if parts[4].strip() else 0.0

            if name.lower() in ("system", "idle", "") or pid == 0:
                continue
            if name in seen:
                continue
            seen.add(name)

            ram_min = _get_min_ram(name)
            procs.append({
                "pid":        pid,
                "name":       name,
                "exe":        path,
                "cpu_pct":    0,   # filled separately
                "ram_mb":     max(1, int(ram)),
                "ram_min_mb": ram_min,
                "gpu_pct":    0,
            })
        except Exception:
            continue
    return procs


def _get_min_ram(name: str) -> int:
    """Return minimum safe RAM in MB for a process name."""
    n = name.lower().replace(".exe", "")
    for key, val in APP_MINIMUMS.items():
        if key in n:
            return val
    return 50   # generic minimum


# ── CPU affinity (which cores) ────────────────────────────────────────────────

def get_cpu_count() -> int:
    try:
        import os
        return os.cpu_count() or 4
    except Exception:
        return 4


def set_cpu_affinity(pid: int, max_pct: int) -> tuple:
    """
    Limit a process to a fraction of CPU cores proportional to max_pct.
    0-100% maps to 1 core .. all cores.
    """
    ncores = get_cpu_count()
    cores_to_use = max(1, round(ncores * max_pct / 100))
    # Build affinity mask: use first N cores
    mask = (1 << cores_to_use) - 1

    script = f"""
try {{
    $p = Get-Process -Id {pid} -ErrorAction Stop
    $p.ProcessorAffinity = {mask}
    Write-Output "OK"
}} catch {{
    Write-Output "ERR: $($_.Exception.Message)"
}}
"""
    code, out = _ps(script)
    ok = "OK" in out
    return ok, out.strip()


def reset_cpu_affinity(pid: int) -> tuple:
    """Restore full affinity (all cores)."""
    ncores = get_cpu_count()
    mask = (1 << ncores) - 1
    script = f"""
try {{
    $p = Get-Process -Id {pid} -ErrorAction Stop
    $p.ProcessorAffinity = {mask}
    Write-Output "OK"
}} catch {{
    Write-Output "ERR: $($_.Exception.Message)"
}}
"""
    code, out = _ps(script)
    return "OK" in out, out.strip()


# ── RAM working set ───────────────────────────────────────────────────────────

def set_ram_limit(pid: int, max_mb: int, min_mb: int) -> tuple:
    """
    Set working set soft cap via SetProcessWorkingSetSizeEx.
    min_mb = app minimum (we never go below it).
    max_mb is clamped to be at least min_mb.
    """
    safe_max = max(min_mb, max_mb)
    min_bytes = min_mb * 1024 * 1024
    max_bytes = safe_max * 1024 * 1024

    kernel32 = ctypes.windll.kernel32
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_QUERY_INFORMATION = 0x0400

    handle = kernel32.OpenProcess(
        PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid
    )
    if not handle:
        return False, f"No se pudo abrir proceso {pid}"

    # QUOTA_LIMITS_HARDWS_MIN_DISABLE = 0x00000002
    # QUOTA_LIMITS_HARDWS_MAX_ENABLE  = 0x00000004
    try:
        ok = kernel32.SetProcessWorkingSetSizeEx(
            handle, min_bytes, max_bytes, 0x00000004
        )
        kernel32.CloseHandle(handle)
        return bool(ok), "OK" if ok else f"Error WinAPI {ctypes.get_last_error()}"
    except Exception as e:
        try:
            kernel32.CloseHandle(handle)
        except Exception:
            pass
        return False, str(e)


def reset_ram_limit(pid: int) -> tuple:
    """Remove working set cap (set to -1/-1 = no limit)."""
    kernel32 = ctypes.windll.kernel32
    PROCESS_SET_QUOTA = 0x0100
    handle = kernel32.OpenProcess(PROCESS_SET_QUOTA, False, pid)
    if not handle:
        return False, f"No se pudo abrir proceso {pid}"
    ok = kernel32.SetProcessWorkingSetSizeEx(
        handle, ctypes.c_size_t(-1), ctypes.c_size_t(-1), 0
    )
    kernel32.CloseHandle(handle)
    return bool(ok), "OK" if ok else "Error"


# ── GPU (best-effort via nvidia-smi) ─────────────────────────────────────────

def has_nvidia_gpu() -> bool:
    code, out = _run(["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"], timeout=5)
    return code == 0 and bool(out.strip())


def set_gpu_limit(pid: int, max_pct: int) -> tuple:
    """
    Try to set nvidia GPU clock offset so total utilisation caps at max_pct.
    This is approximate — true per-process GPU limiting requires CUDA contexts.
    We use nvidia-smi to lower max clocks proportionally.
    """
    if max_pct >= 100:
        return reset_gpu_limit(pid)

    code, out = _run(
        ["nvidia-smi", "--query-gpu=clocks.max.graphics,clocks.max.memory",
         "--format=csv,noheader,nounits"],
        timeout=5,
    )
    if code != 0:
        return False, "nvidia-smi no disponible"

    parts = out.strip().split(",")
    if len(parts) < 2:
        return False, "No se pudieron leer las frecuencias de GPU"

    try:
        max_core = int(parts[0].strip())
        target_core = max(300, int(max_core * max_pct / 100))
        code2, out2 = _run(
            ["nvidia-smi", f"--lock-gpu-clocks={target_core},{target_core}"],
            timeout=5,
        )
        return code2 == 0, out2.strip()
    except Exception as e:
        return False, str(e)


def reset_gpu_limit(pid: int) -> tuple:
    code, out = _run(["nvidia-smi", "--reset-gpu-clocks"], timeout=5)
    return code == 0, out.strip()


# ── Auto-mode profiles ────────────────────────────────────────────────────────

# Auto mode: limit background/heavy apps more aggressively
_AUTO_PROFILES = {
    # background / system helpers — soft limit
    "background": {"cpu_pct": 25,  "ram_factor": 1.5, "gpu_pct": 20},
    # productivity / browsers
    "normal":     {"cpu_pct": 60,  "ram_factor": 2.0, "gpu_pct": 60},
    # games / creative tools — give more room
    "heavy":      {"cpu_pct": 90,  "ram_factor": 3.0, "gpu_pct": 90},
}

_HEAVY_APPS = {
    "blender", "unity", "unreal", "devenv", "idea", "androidstudio",
    "pycharm", "photoshop", "premiere", "afterfx", "illustrator",
    "lightroom", "obs", "davinci", "vegas",
}
_BG_APPS = {
    "svchost", "backgroundtaskhost", "runtimebroker", "searchindexer",
    "winstore.app", "microsoftedgeupdate", "googleupdate", "onedrive",
    "dropbox", "backup", "update", "agent",
}


def get_auto_limits(proc: dict) -> dict:
    """Return auto CPU%, RAM MB and GPU% for a process dict."""
    name = proc["name"].lower().replace(".exe", "")
    ram_min = proc["ram_min_mb"]
    ram_cur = proc["ram_mb"]

    if any(bg in name for bg in _BG_APPS):
        profile = _AUTO_PROFILES["background"]
    elif any(hv in name for hv in _HEAVY_APPS):
        profile = _AUTO_PROFILES["heavy"]
    else:
        profile = _AUTO_PROFILES["normal"]

    cpu_pct = profile["cpu_pct"]
    ram_mb  = max(ram_min, int(ram_cur * profile["ram_factor"]))
    gpu_pct = profile["gpu_pct"]

    return {"cpu_pct": cpu_pct, "ram_mb": ram_mb, "gpu_pct": gpu_pct}


# ── Apply / reset limits ──────────────────────────────────────────────────────

def apply_limits(pid: int, name: str, cpu_pct: int, ram_mb: int,
                 ram_min: int, gpu_pct: int) -> dict:
    """Apply CPU affinity + RAM working set + (optional) GPU limit."""
    results = {}
    ok_cpu, msg_cpu   = set_cpu_affinity(pid, cpu_pct)
    ok_ram, msg_ram   = set_ram_limit(pid, ram_mb, ram_min)
    ok_gpu, msg_gpu   = (True, "N/A") if gpu_pct >= 100 else set_gpu_limit(pid, gpu_pct)
    results["cpu"] = (ok_cpu, msg_cpu)
    results["ram"] = (ok_ram, msg_ram)
    results["gpu"] = (ok_gpu, msg_gpu)
    return results


def reset_limits(pid: int) -> dict:
    """Remove all limits from a process."""
    results = {}
    results["cpu"] = reset_cpu_affinity(pid)
    results["ram"] = reset_ram_limit(pid)
    results["gpu"] = reset_gpu_limit(pid)
    return results
