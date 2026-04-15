"""
WinClean System Tray
- Shows icon in notification area (bottom-right)
- Applies startup profile silently in background
- Menu: Open WinClean | Estado | Salir
"""
import threading
import subprocess
import sys
import os


def _open_main_window():
    """Launch the full GUI in a new process."""
    python = sys.executable
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "main.py"))
    subprocess.Popen([python, script], creationflags=subprocess.CREATE_NO_WINDOW)


def _make_icon_image():
    """
    Create a simple tray icon using PIL drawing.
    Returns a PIL Image object.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        return None

    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    draw.ellipse([2, 2, size - 2, size - 2], fill=(34, 37, 46, 255))
    # Blue ring
    draw.ellipse([2, 2, size - 2, size - 2], outline=(77, 166, 255, 255), width=3)
    # Lightning bolt "⚡" approximation
    pts = [
        (36, 6), (20, 34), (32, 34),
        (28, 58), (44, 30), (32, 30), (36, 6)
    ]
    draw.polygon(pts, fill=(77, 166, 255, 255))
    return img


class WinCleanTray:
    def __init__(self, startup_profile: dict = None):
        self.startup_profile = startup_profile
        self._status = "Iniciando..."
        self._icon = None

    def run(self):
        try:
            import pystray
        except ImportError:
            # pystray not available → apply profile and exit silently
            if self.startup_profile:
                self._apply_profile_silent()
            return

        img = _make_icon_image()
        if img is None:
            # PIL not available either → bail
            if self.startup_profile:
                self._apply_profile_silent()
            return

        import pystray

        def open_gui(icon, item):
            _open_main_window()

        def exit_app(icon, item):
            icon.stop()

        def get_status(item):
            return self._status

        menu = pystray.Menu(
            pystray.MenuItem("⚡ Abrir WinClean", open_gui, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(get_status, None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("❌ Salir", exit_app),
        )

        self._icon = pystray.Icon(
            "WinClean",
            img,
            "WinClean — Optimizador Windows 10",
            menu,
        )

        # Apply profile in background thread before showing icon
        if self.startup_profile:
            t = threading.Thread(target=self._apply_profile_silent, daemon=True)
            t.start()
        else:
            self._status = "Sin perfil de inicio configurado"

        self._icon.run()

    def _apply_profile_silent(self):
        """Apply the startup profile with no UI, update status string."""
        from core.data import BLOATWARE_APPS, SERVICES, TWEAKS
        from core.executor import disable_service, apply_tweak

        profile = self.startup_profile
        if not profile:
            self._status = "Sin perfil configurado"
            return

        name = profile.get("name", "Perfil")
        self._status = f"Aplicando {name}..."
        self._update_icon_tooltip(f"WinClean — Aplicando {name}...")

        errors = 0
        done = 0

        # Services only (no app uninstall on silent startup — too destructive)
        svc_ids = set(profile.get("services", []))
        for svc in SERVICES:
            if svc["id"] in svc_ids:
                ok, _ = disable_service(svc["service"])
                if not ok:
                    errors += 1
                done += 1

        # Tweaks
        tweak_ids = set(profile.get("tweaks", []))
        for tweak in TWEAKS:
            if tweak["id"] in tweak_ids:
                ok, _ = apply_tweak(tweak["id"])
                if not ok:
                    errors += 1
                done += 1

        if errors:
            self._status = f"✅ {name} aplicado ({errors} advertencias)"
        else:
            self._status = f"✅ {name} aplicado correctamente"

        self._update_icon_tooltip(f"WinClean — {self._status}")

    def _update_icon_tooltip(self, text: str):
        if self._icon:
            try:
                self._icon.title = text[:63]  # Windows tray tooltip limit
            except Exception:
                pass
