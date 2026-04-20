"""
WinCleaner v3.7.1 — entry point.
  Normal: python main.py          → opens full GUI
  Tray:   python main.py --tray   → starts in system tray, applies last profile silently
"""
import sys
import os
import ctypes


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    """Re-launch self with admin rights via ShellExecute runas."""
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(f'"{a}"' for a in sys.argv), None, 1
    )
    sys.exit(0)


if __name__ == "__main__":
    # Ensure admin privileges (needed for sc.exe, registry HKLM writes, schtasks)
    if not is_admin():
        elevate()

    # Add project root to import path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    tray_mode = "--tray" in sys.argv

    if tray_mode:
        # ── Tray / background mode ──────────────────────────────────────────
        # Apply the saved startup profile silently, then sit in system tray.
        from core.executor import load_startup_profile
        from core.profiles import load_profile
        from ui.tray import WinCleanTray

        profile_id = load_startup_profile()
        profile_data = load_profile(profile_id) if profile_id else None

        app = WinCleanTray(startup_profile=profile_data)
        app.run()
    else:
        # ── Full GUI mode ───────────────────────────────────────────────────
        from ui.app import WinCleanApp
        app = WinCleanApp()
        app.mainloop()
