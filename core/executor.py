"""
Executor: applies/reverts services, apps, and registry tweaks.
- Real app detection via Get-AppxPackage
- Real service status (running/stopped/disabled/not_found)
- Proper uninstall including provisioned packages
- Startup via Task Scheduler (works with MS Store Python)
- Block service trigger-start for already-disabled services
"""
import subprocess
import winreg
import logging
import os
import sys
import tempfile

logger = logging.getLogger("winclean.executor")


# ─── Subprocess helpers ──────────────────────────────────────────────────────

def _run(cmd: list, capture=True, timeout=30) -> tuple:
    try:
        r = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            timeout=timeout,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        return -2, "Timeout"
    except FileNotFoundError as e:
        return -1, str(e)
    except Exception as e:
        return -1, str(e)


def _powershell(script: str, timeout=60) -> tuple:
    return _run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        timeout=timeout,
    )


# ─── Registry helpers ────────────────────────────────────────────────────────

def _reg_set(hive, path, name, value, vtype=winreg.REG_DWORD) -> bool:
    try:
        key = winreg.CreateKeyEx(hive, path, 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, name, 0, vtype, value)
        winreg.CloseKey(key)
        return True
    except Exception as e:
        logger.error(f"Registry set failed {path}\\{name}: {e}")
        return False


def _reg_get(hive, path, name):
    try:
        key = winreg.OpenKey(hive, path, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, name)
        winreg.CloseKey(key)
        return val
    except Exception:
        return None


# ─── App detection ───────────────────────────────────────────────────────────

def get_all_installed_packages() -> set:
    """
    Returns set of lowercase package name fragments for all installed
    AppX packages (current user + all users + provisioned).
    """
    script = """
$names = @()
try { $names += (Get-AppxPackage -ErrorAction SilentlyContinue).Name } catch {}
try { $names += (Get-AppxPackage -AllUsers -ErrorAction SilentlyContinue).Name } catch {}
try { $names += (Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue).DisplayName } catch {}
$names | Sort-Object -Unique
"""
    code, out = _powershell(script, timeout=90)
    result = set()
    for line in out.splitlines():
        name = line.strip()
        if name and not name.startswith("WARNING") and not name.startswith("ERROR"):
            result.add(name.lower())
    return result


def is_app_installed(package_name: str, installed_cache: set = None) -> bool:
    """Check if any installed package matches the given pattern."""
    pattern = package_name.lower()
    if installed_cache is not None:
        return any(pattern in pkg for pkg in installed_cache)
    # Direct query fallback
    code, out = _powershell(
        f'(Get-AppxPackage -AllUsers "*{package_name}*" -ErrorAction SilentlyContinue).Name'
    )
    return bool(out.strip()) and code == 0


def uninstall_app(package_name: str) -> tuple:
    """
    Uninstall UWP app for all users + remove provisioned package.
    Returns (success: bool, message: str)
    """
    script = f"""
$errors = @()
$removed = $false

# Remove for all users
try {{
    $pkgs = Get-AppxPackage -AllUsers "*{package_name}*" -ErrorAction SilentlyContinue
    if ($pkgs) {{
        $pkgs | Remove-AppxPackage -AllUsers -ErrorAction SilentlyContinue
        $removed = $true
        Write-Output "Removed AppxPackage"
    }}
}} catch {{ $errors += $_.Exception.Message }}

# Remove provisioned (prevents reinstall on new users)
try {{
    $prov = Get-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue |
            Where-Object {{ $_.DisplayName -like "*{package_name}*" }}
    if ($prov) {{
        $prov | Remove-AppxProvisionedPackage -Online -ErrorAction SilentlyContinue
        $removed = $true
        Write-Output "Removed provisioned package"
    }}
}} catch {{ $errors += $_.Exception.Message }}

if (-not $removed) {{ Write-Output "NOT_INSTALLED" }}
if ($errors) {{ Write-Output ("ERRORS: " + ($errors -join "; ")) }}
"""
    code, out = _powershell(script, timeout=120)
    if "NOT_INSTALLED" in out and "Removed" not in out:
        return True, "No estaba instalada"
    if "Removed" in out:
        return True, out.strip()[:200]
    return False, out.strip()[:200]


# ─── Service detection ───────────────────────────────────────────────────────

SVC_RUNNING   = "running"
SVC_STOPPED   = "stopped"
SVC_DISABLED  = "disabled"
SVC_BLOCKED   = "blocked"   # disabled + triggers removed
SVC_NOT_FOUND = "not_found"


def get_service_status(service_name: str) -> str:
    """Returns one of: running | stopped | disabled | blocked | not_found"""
    # Query current state
    code, out = _run(["sc", "query", service_name])
    if code != 0 and ("does not exist" in out or "1060" in out or "OpenService" in out):
        return SVC_NOT_FOUND

    running = "RUNNING" in out

    # Query config for start type
    code2, out2 = _run(["sc", "qc", service_name])
    disabled = "DISABLED" in out2

    if not disabled:
        return SVC_RUNNING if running else SVC_STOPPED
    
    # Check for trigger info (if no triggers → blocked)
    code3, out3 = _run(["sc", "qtriggerinfo", service_name])
    has_triggers = "START" in out3.upper() and "TRIGGER" in out3.upper()
    
    if disabled and not has_triggers:
        return SVC_BLOCKED
    return SVC_DISABLED


def get_all_service_statuses(service_names: list) -> dict:
    """Batch query. Returns {service_name: status_str}"""
    return {name: get_service_status(name) for name in service_names}


def disable_service(service_name: str) -> tuple:
    """Stop and disable a service."""
    _run(["sc", "stop", service_name])
    code, out = _run(["sc", "config", service_name, "start=", "disabled"])
    return code == 0, out.strip()


def enable_service(service_name: str) -> tuple:
    """Re-enable and start a service."""
    code, out = _run(["sc", "config", service_name, "start=", "auto"])
    _run(["sc", "start", service_name])
    return code == 0, out.strip()


def block_service(service_name: str) -> tuple:
    """
    Disable service AND remove its trigger-start entries so Windows
    cannot automatically wake it (e.g. DiagTrack, dmwappushservice).
    """
    _run(["sc", "stop", service_name])
    _run(["sc", "config", service_name, "start=", "disabled"])
    # Delete trigger info
    _run(["sc", "triggerinfo", service_name, "delete"])
    return True, "Bloqueado (sin triggers)"


def unblock_service(service_name: str) -> tuple:
    """Restore service to automatic start (undo block)."""
    code, out = _run(["sc", "config", service_name, "start=", "auto"])
    _run(["sc", "start", service_name])
    return code == 0, out.strip()


# ─── Tweaks ──────────────────────────────────────────────────────────────────

TWEAK_ACTIONS = {
    "telemetry_reg": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 0),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry", 1),
    },
    "cortana_search": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Policies\Microsoft\Windows\Windows Search", "AllowCortana", 0),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Policies\Microsoft\Windows\Windows Search", "AllowCortana", 1),
    },
    "activity_history": {
        "apply":  lambda: all([
            _reg_set(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\System", "EnableActivityFeed", 0),
            _reg_set(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\System", "PublishUserActivities", 0),
        ]),
        "revert": lambda: all([
            _reg_set(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\System", "EnableActivityFeed", 1),
            _reg_set(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Policies\Microsoft\Windows\System", "PublishUserActivities", 1),
        ]),
    },
    "advertising_id": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled", 1),
    },
    "location_tracking": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Sensor\Overrides\{BFA794E4-F964-4FDB-90F6-51056BFE4B44}",
            "SensorPermissionState", 0),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Sensor\Overrides\{BFA794E4-F964-4FDB-90F6-51056BFE4B44}",
            "SensorPermissionState", 1),
    },
    "feedback_freq": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod", 1),
    },
    "startup_sound": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI\BootAnimation",
            "DisableStartupSound", 1),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI\BootAnimation",
            "DisableStartupSound", 0),
    },
    "game_mode": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\GameBar", "AutoGameModeEnabled", 1),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\GameBar", "AutoGameModeEnabled", 0),
    },
    "hardware_acceleration": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 1),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode", 2),
    },
    "power_plan": {
        "apply":  lambda: _run(["powercfg", "/setactive", "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c"])[0] == 0,
        "revert": lambda: _run(["powercfg", "/setactive", "381b4222-f694-41f0-9685-ff5bb260df2e"])[0] == 0,
    },
    "visual_effects": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 2),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting", 0),
    },
    "notifications": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled", 1),
    },
    "autoplay": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDriveTypeAutoRun", 255),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDriveTypeAutoRun", 145),
    },
    "error_reporting": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled", 1),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled", 0),
    },
    "remote_assistance": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Remote Assistance", "fAllowToGetHelp", 0),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Remote Assistance", "fAllowToGetHelp", 1),
    },
    "hibernation": {
        "apply":  lambda: _run(["powercfg", "/h", "off"])[0] == 0,
        "revert": lambda: _run(["powercfg", "/h", "on"])[0] == 0,
    },
    "news_interests": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Feeds", "ShellFeedsTaskbarViewMode", 2),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Feeds", "ShellFeedsTaskbarViewMode", 0),
    },
    "search_highlights": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\SearchSettings", "IsDynamicSearchBoxEnabled", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\SearchSettings", "IsDynamicSearchBoxEnabled", 1),
    },
    "timer_resolution": {
        "apply":  lambda: _run(["bcdedit", "/set", "useplatformtick", "yes"])[0] == 0,
        "revert": lambda: _run(["bcdedit", "/deletevalue", "useplatformtick"])[0] == 0,
    },
    "network_throttle": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
            "NetworkThrottlingIndex", 0xffffffff),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
            "NetworkThrottlingIndex", 10),
    },
    # ── Windows 11 tweaks ─────────────────────────────────────────────────
    "w11_copilot_taskbar": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ShowCopilotButton", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ShowCopilotButton", 1),
    },
    "w11_recall": {
        "apply":  lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", 1),
        "revert": lambda: _reg_set(winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis", 0),
    },
    "w11_ai_search": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\SearchSettings", "IsDynamicSearchBoxEnabled", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\SearchSettings", "IsDynamicSearchBoxEnabled", 1),
    },
    "w11_widgets": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarDa", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarDa", 1),
    },
    "w11_snap_suggest": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "SnapAssist", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "SnapAssist", 1),
    },
    "w11_typing_insights": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Input\Settings", "IsVoiceTypingKeyEnabled", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Input\Settings", "IsVoiceTypingKeyEnabled", 1),
    },
    "w11_personalized_ads": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Privacy",
            "TailoredExperiencesWithDiagnosticDataEnabled", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Privacy",
            "TailoredExperiencesWithDiagnosticDataEnabled", 1),
    },
    "w11_voice_typing": {
        "apply":  lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Speech_OneCore\Settings\OnlineSpeechPrivacy", "HasAccepted", 0),
        "revert": lambda: _reg_set(winreg.HKEY_CURRENT_USER,
            r"SOFTWARE\Microsoft\Speech_OneCore\Settings\OnlineSpeechPrivacy", "HasAccepted", 1),
    },
}


def apply_tweak(tweak_id: str) -> tuple:
    action = TWEAK_ACTIONS.get(tweak_id)
    if not action:
        return False, f"Tweak '{tweak_id}' no encontrado"
    try:
        result = action["apply"]()
        return bool(result), "OK" if result else "Error en registro/sistema"
    except Exception as e:
        return False, str(e)


def revert_tweak(tweak_id: str) -> tuple:
    action = TWEAK_ACTIONS.get(tweak_id)
    if not action:
        return False, f"Tweak '{tweak_id}' no encontrado"
    try:
        result = action["revert"]()
        return bool(result), "OK" if result else "Error en registro/sistema"
    except Exception as e:
        return False, str(e)


# ─── Startup via Task Scheduler ──────────────────────────────────────────────

TASK_NAME = "WinCleanAutostart"


def _get_python_exe() -> str:
    """
    Resolve real pythonw.exe path.
    Handles: normal install, MS Store Python (WindowsApps alias).
    """
    exe = sys.executable  # may be python.exe or a Store alias

    # Prefer pythonw.exe (no console window)
    candidate_w = exe.replace("python.exe", "pythonw.exe")
    if os.path.exists(candidate_w):
        exe = candidate_w

    # If it's a Store alias (not a real file path), find the real one
    if not os.path.isfile(exe) or "WindowsApps" in exe:
        # Try py launcher
        code, out = _run(["py", "-c", "import sys; print(sys.executable)"])
        if code == 0 and out.strip() and os.path.isfile(out.strip()):
            real = out.strip().replace("python.exe", "pythonw.exe")
            if os.path.isfile(real):
                return real
            return out.strip()
        
        # Search PATH for a non-alias python
        code2, out2 = _run(["where", "python"])
        for line in out2.splitlines():
            line = line.strip()
            if line.endswith(".exe") and os.path.isfile(line) and "WindowsApps" not in line:
                w = line.replace("python.exe", "pythonw.exe")
                return w if os.path.isfile(w) else line

    return exe


def _get_script_path() -> str:
    """Get absolute path to main.py (one level up from core/)."""
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))


def set_startup(enabled: bool) -> tuple:
    """
    Register/unregister WinClean in Task Scheduler at user logon.
    The task runs with highest available privileges (UAC elevation).
    Returns (success: bool, message: str)
    """
    if not enabled:
        code, out = _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
        ok = code == 0 or "no existe" in out.lower() or "not exist" in out.lower() or "cannot find" in out.lower()
        return ok, "Inicio automático desactivado"

    python_exe = _get_python_exe()
    script_path = _get_script_path()
    work_dir = os.path.dirname(script_path)

    task_xml = f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>WinClean - Optimizador Windows 10</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <Delay>PT5S</Delay>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>HighestAvailable</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Hidden>false</Hidden>
    <Priority>7</Priority>
    <IdleSettings>
      <StopOnIdleEnd>false</StopOnIdleEnd>
      <RestartOnIdle>false</RestartOnIdle>
    </IdleSettings>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{python_exe}</Command>
      <Arguments>"{script_path}" --tray</Arguments>
      <WorkingDirectory>{work_dir}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>"""

    tmp = tempfile.mktemp(suffix=".xml")
    try:
        with open(tmp, "w", encoding="utf-16") as f:
            f.write(task_xml)
        _run(["schtasks", "/delete", "/tn", TASK_NAME, "/f"])
        code, out = _run(["schtasks", "/create", "/tn", TASK_NAME, "/xml", tmp, "/f"])
        if code == 0:
            return True, "Inicio automático activado (Task Scheduler)"
        return False, f"Error al crear tarea: {out.strip()[:200]}"
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass


def get_startup_status() -> bool:
    """Check if WinClean autostart task exists in Task Scheduler."""
    code, out = _run(["schtasks", "/query", "/tn", TASK_NAME])
    return code == 0


# ─── Startup profile persistence ─────────────────────────────────────────────

_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".winclean")


def save_startup_profile(profile_id: str):
    os.makedirs(_CONFIG_DIR, exist_ok=True)
    with open(os.path.join(_CONFIG_DIR, "startup_config.txt"), "w") as f:
        f.write(profile_id)


def load_startup_profile() -> str:
    try:
        with open(os.path.join(_CONFIG_DIR, "startup_config.txt"), "r") as f:
            return f.read().strip()
    except Exception:
        return ""


# ─── Windows version detection ────────────────────────────────────────────────

def get_windows_build() -> int:
    """Return the Windows build number (e.g. 22000 for W11 21H2)."""
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                             r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
        build, _ = winreg.QueryValueEx(key, "CurrentBuildNumber")
        winreg.CloseKey(key)
        return int(build)
    except Exception:
        return 0


def is_windows_11() -> bool:
    """Windows 11 starts at build 22000."""
    return get_windows_build() >= 22000


# ─── Laptop / battery detection ──────────────────────────────────────────────

def is_laptop() -> bool:
    """Returns True if the system has a battery (i.e. is a laptop)."""
    code, out = _powershell(
        "(Get-WmiObject -Class Win32_Battery -ErrorAction SilentlyContinue | Measure-Object).Count"
    )
    try:
        return int(out.strip()) > 0
    except Exception:
        return False


# ─── Power plan management ────────────────────────────────────────────────────

POWER_PLANS = {
    "saver":     ("a1841308-3541-4fab-bc81-f71556f20b4a", "Ahorro de batería"),
    "balanced":  ("381b4222-f694-41f0-9685-ff5bb260df2e", "Equilibrado"),
    "high":      ("8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c", "Alto rendimiento"),
}


def get_active_power_plan() -> str:
    """Returns 'saver', 'balanced', or 'high'. Falls back to 'balanced'."""
    code, out = _run(["powercfg", "/getactivescheme"])
    out_lower = out.lower()
    for plan_id, (guid, _) in POWER_PLANS.items():
        if guid.lower() in out_lower:
            return plan_id
    return "balanced"


def set_power_plan(plan_id: str) -> tuple:
    """Activate one of the three Windows power plans."""
    guid, name = POWER_PLANS.get(plan_id, POWER_PLANS["balanced"])
    code, out = _run(["powercfg", "/setactive", guid])
    return code == 0, name


# ─── Tweak state readers ──────────────────────────────────────────────────────
# Each function returns True if WinClean's restriction IS APPLIED (i.e. ON=applied=OFF visually)

def _tweak_state_telemetry_reg() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Policies\Microsoft\Windows\DataCollection", "AllowTelemetry")
    return val == 0


def _tweak_state_cortana_search() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Policies\Microsoft\Windows\Windows Search", "AllowCortana")
    return val == 0


def _tweak_state_activity_history() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Policies\Microsoft\Windows\System", "EnableActivityFeed")
    return val == 0


def _tweak_state_advertising_id() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\AdvertisingInfo", "Enabled")
    return val == 0


def _tweak_state_location_tracking() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Sensor\Overrides\{BFA794E4-F964-4FDB-90F6-51056BFE4B44}",
                   "SensorPermissionState")
    return val == 0


def _tweak_state_feedback_freq() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Siuf\Rules", "NumberOfSIUFInPeriod")
    return val == 0


def _tweak_state_startup_sound() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Authentication\LogonUI\BootAnimation",
                   "DisableStartupSound")
    return val == 1


def _tweak_state_game_mode() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\GameBar", "AutoGameModeEnabled")
    # game_mode ON means the restriction (enabling game mode) IS applied
    return val == 1


def _tweak_state_hardware_acceleration() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SYSTEM\CurrentControlSet\Control\GraphicsDrivers", "HwSchMode")
    return val == 1


def _tweak_state_visual_effects() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\VisualEffects", "VisualFXSetting")
    return val == 2


def _tweak_state_notifications() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\PushNotifications", "ToastEnabled")
    return val == 0


def _tweak_state_autoplay() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\Explorer", "NoDriveTypeAutoRun")
    return val == 255


def _tweak_state_error_reporting() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Microsoft\Windows\Windows Error Reporting", "Disabled")
    return val == 1


def _tweak_state_remote_assistance() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SYSTEM\CurrentControlSet\Control\Remote Assistance", "fAllowToGetHelp")
    return val == 0


def _tweak_state_hibernation() -> bool:
    # Check if hiberfil.sys does NOT exist → restriction applied
    import os
    return not os.path.exists(r"C:\hiberfil.sys")


def _tweak_state_news_interests() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Feeds", "ShellFeedsTaskbarViewMode")
    return val == 2


def _tweak_state_search_highlights() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\SearchSettings", "IsDynamicSearchBoxEnabled")
    return val == 0


def _tweak_state_timer_resolution() -> bool:
    code, out = _run(["bcdedit", "/enum", "{current}"])
    return "useplatformtick" in out.lower() and "yes" in out.lower()


def _tweak_state_network_throttle() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Multimedia\SystemProfile",
                   "NetworkThrottlingIndex")
    return val == 0xffffffff


# ── Windows 11 tweak state readers ───────────────────────────────────────────

def _tweak_state_w11_copilot_taskbar() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "ShowCopilotButton")
    return val == 0


def _tweak_state_w11_recall() -> bool:
    val = _reg_get(winreg.HKEY_LOCAL_MACHINE,
                   r"SOFTWARE\Policies\Microsoft\Windows\WindowsAI", "DisableAIDataAnalysis")
    return val == 1


def _tweak_state_w11_ai_search() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\SearchSettings", "IsDynamicSearchBoxEnabled")
    return val == 0


def _tweak_state_w11_widgets() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "TaskbarDa")
    return val == 0


def _tweak_state_w11_snap_suggest() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Explorer\Advanced", "SnapAssist")
    return val == 0


def _tweak_state_w11_typing_insights() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Input\Settings", "IsVoiceTypingKeyEnabled")
    return val == 0


def _tweak_state_w11_personalized_ads() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Windows\CurrentVersion\Privacy", "TailoredExperiencesWithDiagnosticDataEnabled")
    return val == 0


def _tweak_state_w11_voice_typing() -> bool:
    val = _reg_get(winreg.HKEY_CURRENT_USER,
                   r"SOFTWARE\Microsoft\Speech_OneCore\Settings\OnlineSpeechPrivacy", "HasAccepted")
    return val == 0


# Map tweak_id -> state reader function
TWEAK_STATE_READERS = {
    "telemetry_reg":       _tweak_state_telemetry_reg,
    "cortana_search":      _tweak_state_cortana_search,
    "activity_history":    _tweak_state_activity_history,
    "advertising_id":      _tweak_state_advertising_id,
    "location_tracking":   _tweak_state_location_tracking,
    "feedback_freq":       _tweak_state_feedback_freq,
    "startup_sound":       _tweak_state_startup_sound,
    "game_mode":           _tweak_state_game_mode,
    "hardware_acceleration": _tweak_state_hardware_acceleration,
    "visual_effects":      _tweak_state_visual_effects,
    "notifications":       _tweak_state_notifications,
    "autoplay":            _tweak_state_autoplay,
    "error_reporting":     _tweak_state_error_reporting,
    "remote_assistance":   _tweak_state_remote_assistance,
    "hibernation":         _tweak_state_hibernation,
    "news_interests":      _tweak_state_news_interests,
    "search_highlights":   _tweak_state_search_highlights,
    "timer_resolution":    _tweak_state_timer_resolution,
    "network_throttle":    _tweak_state_network_throttle,
    # W11
    "w11_copilot_taskbar":  _tweak_state_w11_copilot_taskbar,
    "w11_recall":           _tweak_state_w11_recall,
    "w11_ai_search":        _tweak_state_w11_ai_search,
    "w11_widgets":          _tweak_state_w11_widgets,
    "w11_snap_suggest":     _tweak_state_w11_snap_suggest,
    "w11_typing_insights":  _tweak_state_w11_typing_insights,
    "w11_personalized_ads": _tweak_state_w11_personalized_ads,
    "w11_voice_typing":     _tweak_state_w11_voice_typing,
}


def read_tweak_state(tweak_id: str) -> bool:
    """Return True if WinClean's restriction is currently applied for this tweak."""
    fn = TWEAK_STATE_READERS.get(tweak_id)
    if fn is None:
        return False
    try:
        return bool(fn())
    except Exception:
        return False


def read_all_tweak_states(tweak_ids: list) -> dict:
    """Batch read. Returns {tweak_id: bool}"""
    return {tid: read_tweak_state(tid) for tid in tweak_ids}
