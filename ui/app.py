"""
WinClean - Main Application Window
- Detects Windows 10 vs Windows 11 at startup
- Shows W11-exclusive sections only when on W11
- Reads real tweak state before displaying (ON/OFF reflects actual system state)
- Power profile selector (battery saver / balanced / high perf) with laptop detection
- Per-process manual resource limits (no global auto toggle)
- Close button minimizes to tray instead of quitting
"""
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import sys
import os
import json

from core.data import BLOATWARE_APPS, SERVICES, TWEAKS
from core.profiles import list_profiles, load_profile, save_profile, delete_profile, import_profile, export_profile
from core.executor import (
    get_all_installed_packages, is_app_installed,
    get_service_status, SVC_RUNNING, SVC_STOPPED, SVC_DISABLED, SVC_BLOCKED, SVC_NOT_FOUND,
    disable_service, enable_service, block_service, unblock_service,
    uninstall_app, apply_tweak, revert_tweak,
    set_startup, get_startup_status, save_startup_profile, load_startup_profile,
    is_windows_11, is_laptop,
    get_active_power_plan, set_power_plan,
    read_all_tweak_states,
)
from ui.styles import apply_theme, COLORS, FONTS
from ui.widgets import SectionHeader, ItemCard, ServiceCard, TweakCard, ProcessResourceCard, StatusBar
from ui.cleaner_window import CleanerWindow

# Servicios de IA de Windows 11 mostrados en la pestaña IA (con toggle real)
AI_SERVICES = [
    {"id": "ai_svc_AIXHelper",            "service": "AIXHelper",            "name": "AI Helper Service",          "description": "Proceso de soporte de IA, siempre activo en W11 24H2+",      "risk": "medium"},
    {"id": "ai_svc_cbdhsvc",              "service": "cbdhsvc",              "name": "Portapapeles en la nube",    "description": "Sincronización del portapapeles + sugerencias IA",         "risk": "low"},
    {"id": "ai_svc_wemsvc",               "service": "wemsvc",               "name": "Windows Experience Service", "description": "Recopila datos de uso para personalización IA",             "risk": "medium"},
    {"id": "ai_svc_StorSvc",              "service": "StorSvc",              "name": "Storage Service (Recall)",   "description": "Gestiona las capturas de Recall en disco",                 "risk": "high"},
    {"id": "ai_svc_wisvc",                "service": "wisvc",                "name": "Windows Insider Service",    "description": "Envía telemetría incluso sin ser Insider",                 "risk": "medium"},
    {"id": "ai_svc_perceptionsimulation", "service": "perceptionsimulation", "name": "Perception Simulation",      "description": "IA para realidad mixta y cámara inteligente",              "risk": "low"},
]
from core import resource_manager as rm

SVC_STATUS_DISPLAY = {
    SVC_RUNNING:   ("EN EJECUCION", COLORS["success"]),
    SVC_STOPPED:   ("DETENIDO",     COLORS["warning"]),
    SVC_DISABLED:  ("DESACTIVADO",  COLORS["text_muted"]),
    SVC_BLOCKED:   ("BLOQUEADO",    "#8855cc"),
    SVC_NOT_FOUND: ("NO EXISTE",    COLORS["border"]),
}

W11_BADGE_COLOR = "#1a6aff"
W11_BADGE_TEXT  = "WINDOWS 11"


class WinCleanApp(tk.Tk):
    def __init__(self):
        super().__init__()

        # ── Detect system features immediately ────────────────────────
        self.win11 = is_windows_11()
        self.is_laptop = is_laptop()

        title_os = "Windows 11" if self.win11 else "Windows 10"
        self.title(f"WinCleaner v3.7.1 - Optimizador {title_os}")
        self.geometry("1200x760")
        self.minsize(1000, 640)
        self.configure(bg=COLORS["bg"])

        # ── State ─────────────────────────────────────────────────────
        self.check_vars = {}
        self.svc_status_cache = {}
        self.installed_apps = set()
        self.current_profile = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Escaneando sistema...")
        self.startup_var = tk.BooleanVar(value=False)
        self.startup_profile_var = tk.StringVar(value="")
        self.tweak_states = {}       # tweak_id -> bool (True = restriction applied)
        self._tweak_cards = {}       # tweak_id -> TweakCard widget
        self._ai_svc_card_frames = {}  # ai service card widgets

        # Resource manager state (per-process manual mode)
        self._resource_procs  = []
        self._resource_cards  = {}

        # Tray
        self._tray_icon  = None
        self._tray_thread = None

        self._build_check_vars()
        apply_theme(self)
        self._build_ui()
        self._center_window()

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(200, self._start_scan)

    # ── Init ──────────────────────────────────────────────────────────

    def _build_check_vars(self):
        for item in BLOATWARE_APPS + SERVICES + TWEAKS + AI_SERVICES:
            self.check_vars[item["id"]] = tk.BooleanVar(value=False)

    def _center_window(self):
        self.update_idletasks()
        w, h = 1200, 760
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── Tray / close ──────────────────────────────────────────────────

    def _on_close(self):
        self.withdraw()
        if self._tray_icon is not None:
            return
        self._tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        self._tray_thread.start()

    def _run_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            self.after(0, self._show_from_tray)
            self.after(0, lambda: messagebox.showwarning(
                "Bandeja no disponible",
                "Para minimizar a la bandeja instala:\n  pip install pystray pillow\n\n"
                "La ventana se mantendra visible."
            ))
            return

        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, size-2, size-2], fill=(34, 37, 46, 255))
        draw.ellipse([2, 2, size-2, size-2], outline=(77, 166, 255, 255), width=3)
        pts = [(36,6),(20,34),(32,34),(28,58),(44,30),(32,30),(36,6)]
        draw.polygon(pts, fill=(77, 166, 255, 255))

        def on_open(icon, item): self.after(0, self._show_from_tray)
        def on_quit(icon, item): icon.stop(); self.after(0, self._quit_app)

        menu = pystray.Menu(
            pystray.MenuItem("Abrir WinClean", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", on_quit),
        )
        self._tray_icon = pystray.Icon("WinClean", img, "WinClean", menu)
        self._tray_icon.run()

    def _show_from_tray(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_app(self):
        try:
            self.destroy()
        except Exception:
            pass

    # ── Scan ──────────────────────────────────────────────────────────

    def _start_scan(self):
        self.status_text.set("Escaneando apps instaladas, servicios y tweaks...")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        self.installed_apps = get_all_installed_packages()

        svc_names = [s["service"] for s in SERVICES]
        for name in svc_names:
            self.svc_status_cache[name] = get_service_status(name)

        # Scan AI services (shown in IA tab)
        for svc in AI_SERVICES:
            self.svc_status_cache[svc["service"]] = get_service_status(svc["service"])

        # Read real state of all tweaks
        all_tweak_ids = [t["id"] for t in TWEAKS]
        self.tweak_states = read_all_tweak_states(all_tweak_ids)

        is_startup = get_startup_status()
        self.after(0, lambda: self._apply_scan_results(is_startup))

    def _apply_scan_results(self, is_startup: bool):
        self.startup_var.set(is_startup)
        self._refresh_app_cards()
        self._refresh_service_cards()
        self._refresh_tweak_states()
        if self.win11:
            self._refresh_ai_svc_cards()
            self._restore_ai_states_from_disk()

        n_apps = sum(1 for a in BLOATWARE_APPS if is_app_installed(a["package"], self.installed_apps))
        n_svcs = sum(1 for s in SERVICES if self.svc_status_cache.get(s["service"]) != SVC_NOT_FOUND)
        self.status_text.set(f"Escaneado: {n_apps} apps encontradas, {n_svcs} servicios detectados")

    # ── UI Construction ───────────────────────────────────────────────

    def _build_ui(self):
        topbar = tk.Frame(self, bg=COLORS["surface"], height=56)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="WinCleaner v3.7.1", font=FONTS["title"],
                 bg=COLORS["surface"], fg=COLORS["accent"]).pack(side="left", padx=20, pady=10)

        os_label = "Windows 11" if self.win11 else "Windows 10"
        os_color  = W11_BADGE_COLOR if self.win11 else COLORS["text_muted"]
        tk.Label(topbar, text=f"Optimizador & Limpiador {os_label}",
                 font=FONTS["subtitle"], bg=COLORS["surface"], fg=os_color).pack(side="left", padx=4)

        if self.win11:
            tk.Label(topbar, text="  ✦ W11", font=("Segoe UI", 8, "bold"),
                     bg=COLORS["surface"], fg=W11_BADGE_COLOR).pack(side="left")

        sf = tk.Frame(topbar, bg=COLORS["surface"])
        sf.pack(side="right", padx=20)
        tk.Checkbutton(
            sf, text="Iniciar con Windows",
            variable=self.startup_var, command=self._toggle_startup,
            bg=COLORS["surface"], fg=COLORS["text_muted"],
            activebackground=COLORS["surface"], activeforeground=COLORS["accent"],
            selectcolor=COLORS["bg"], font=FONTS["small"], cursor="hand2",
        ).pack(side="right", pady=4)

        tk.Button(
            sf, text="🧹 Limpiar disco",
            command=self._open_cleaner,
            bg=COLORS["btn"], fg=COLORS["accent"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=10, pady=4, bd=0,
            activebackground=COLORS["btn_hover"], activeforeground=COLORS["accent"],
        ).pack(side="right", padx=(0, 12), pady=4)

        main = tk.Frame(self, bg=COLORS["bg"])
        main.pack(fill="both", expand=True)

        sidebar = tk.Frame(main, bg=COLORS["surface"], width=230)
        sidebar.pack(side="left", fill="y")
        sidebar.pack_propagate(False)
        self._build_sidebar(sidebar)

        content = tk.Frame(main, bg=COLORS["bg"])
        content.pack(side="left", fill="both", expand=True)
        self._build_content(content)

        self.status_bar = StatusBar(self, self.status_text)
        self.status_bar.pack(fill="x", side="bottom")

    def _build_sidebar(self, parent):
        tk.Label(parent, text="PERFILES", font=FONTS["label"],
                 bg=COLORS["surface"], fg=COLORS["accent"]).pack(anchor="w", padx=16, pady=(16, 8))

        self.profile_list_frame = tk.Frame(parent, bg=COLORS["surface"])
        self.profile_list_frame.pack(fill="x", padx=8)
        self._refresh_profile_list()

        btn_frame = tk.Frame(parent, bg=COLORS["surface"])
        btn_frame.pack(fill="x", padx=8, pady=8)
        for text, cmd in [
            ("Guardar perfil", self._save_profile_dialog),
            ("Importar",       self._import_profile),
            ("Exportar",       self._export_profile),
            ("Eliminar",       self._delete_profile),
        ]:
            tk.Button(btn_frame, text=text, command=cmd,
                      bg=COLORS["btn"], fg=COLORS["text"], font=FONTS["small"],
                      relief="flat", cursor="hand2", pady=5,
                      activebackground=COLORS["btn_hover"], activeforeground=COLORS["accent"],
                      bd=0).pack(fill="x", pady=2)

        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        tk.Label(parent, text="PERFIL AL INICIO", font=FONTS["label"],
                 bg=COLORS["surface"], fg=COLORS["accent"]).pack(anchor="w", padx=16, pady=(4, 4))
        tk.Label(parent, text="Se aplica en bandeja al arrancar",
                 font=FONTS["small"], bg=COLORS["surface"], fg=COLORS["text_muted"],
                 wraplength=190, justify="left").pack(anchor="w", padx=16)

        self.startup_profile_combo = ttk.Combobox(
            parent, textvariable=self.startup_profile_var,
            state="readonly", font=FONTS["small"],
        )
        self.startup_profile_combo.pack(fill="x", padx=8, pady=6)
        self.startup_profile_combo.bind("<<ComboboxSelected>>", self._on_startup_profile_change)
        self._refresh_startup_profile_combo()

        saved_pid = load_startup_profile()
        if saved_pid:
            self.startup_profile_var.set(saved_pid)

        tk.Frame(parent, bg=COLORS["border"], height=1).pack(fill="x", pady=8)

        tk.Label(parent, text="ACCIONES RAPIDAS", font=FONTS["label"],
                 bg=COLORS["surface"], fg=COLORS["accent"]).pack(anchor="w", padx=16, pady=(4, 8))
        for text, cmd in [
            ("Seleccionar todo",   self._select_all),
            ("Deseleccionar todo", self._deselect_all),
            ("Revertir cambios",   self._revert_all),
            ("Re-escanear sistema", self._start_scan),
        ]:
            tk.Button(parent, text=text, command=cmd,
                      bg=COLORS["bg"], fg=COLORS["text_muted"], font=FONTS["small"],
                      relief="flat", cursor="hand2", pady=4,
                      activebackground=COLORS["btn"], activeforeground=COLORS["text"],
                      bd=0).pack(fill="x", padx=8, pady=2)

    def _build_content(self, parent):
        style = ttk.Style()
        style.configure("WC.TNotebook", background=COLORS["bg"], borderwidth=0)
        style.configure("WC.TNotebook.Tab", background=COLORS["surface"],
                        foreground=COLORS["text_muted"], padding=[16, 8], font=FONTS["body"])
        style.map("WC.TNotebook.Tab",
                  background=[("selected", COLORS["bg"])],
                  foreground=[("selected", COLORS["accent"])])

        nb = ttk.Notebook(parent, style="WC.TNotebook")
        nb.pack(fill="both", expand=True, padx=12, pady=12)

        self.apps_tab_frame  = tk.Frame(nb, bg=COLORS["bg"])
        self.svcs_tab_frame  = tk.Frame(nb, bg=COLORS["bg"])
        tweaks_tab           = tk.Frame(nb, bg=COLORS["bg"])
        self.res_tab_frame   = tk.Frame(nb, bg=COLORS["bg"])
        self.locks_tab_frame = tk.Frame(nb, bg=COLORS["bg"])

        nb.add(self.apps_tab_frame,  text="Apps & Bloatware")
        nb.add(self.svcs_tab_frame,  text="Servicios")
        nb.add(tweaks_tab,           text="Tweaks & Privacidad")
        nb.add(self.res_tab_frame,   text="⚡ Recursos")
        nb.add(self.locks_tab_frame, text="🔒 Bloqueos de Función")

        # W11-exclusive AI tab
        if self.win11:
            self.ai_tab_frame = tk.Frame(nb, bg=COLORS["bg"])
            nb.add(self.ai_tab_frame, text="🤖 IA Windows 11")
            self._build_ai_tab(self.ai_tab_frame)

        self.apps_canvas, self.apps_inner = self._make_scrollable(self.apps_tab_frame)
        SectionHeader(self.apps_inner, "Aplicaciones Preinstaladas",
                      "Solo se muestran las apps instaladas en tu PC. Marca las que quieres DESINSTALAR permanentemente.").pack(
            fill="x", padx=16, pady=(16, 4))
        self.app_card_frames = {}

        self.svcs_canvas, self.svcs_inner = self._make_scrollable(self.svcs_tab_frame)
        SectionHeader(self.svcs_inner, "Servicios de Windows",
                      "Solo se muestran los servicios presentes en tu sistema. "
                      "Marca los servicios que quieres DESACTIVAR y pulsa 'Aplicar configuración'. "
                      "Estado actual:  Verde=En ejecución  Amarillo=Detenido  Gris=Desactivado  Morado=Bloqueado").pack(
            fill="x", padx=16, pady=(16, 4))
        self.svc_card_frames = {}

        self._build_tweaks_tab_content(tweaks_tab)
        self._build_resources_tab(self.res_tab_frame)
        self._build_locks_tab(self.locks_tab_frame)

        af = tk.Frame(parent, bg=COLORS["bg"])
        af.pack(fill="x", padx=12, pady=(0, 12))
        self.apply_btn = tk.Button(
            af, text="APLICAR CONFIGURACION SELECCIONADA",
            command=self._apply_selected,
            bg=COLORS["accent"], fg="#000000", font=FONTS["button"],
            relief="flat", cursor="hand2", pady=12, padx=24,
            activebackground=COLORS["accent_hover"], activeforeground="#000000",
        )
        self.apply_btn.pack(fill="x")

    def _make_scrollable(self, parent):
        canvas = tk.Canvas(parent, bg=COLORS["bg"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLORS["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        return canvas, inner

    # ── App cards ─────────────────────────────────────────────────────

    def _refresh_app_cards(self):
        for w in self.app_card_frames.values():
            w.destroy()
        self.app_card_frames.clear()

        risk_colors = {"low": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}
        found = 0

        # Base apps (W10+)
        base_apps = [a for a in BLOATWARE_APPS if not a.get("win11")]
        for app in base_apps:
            if not is_app_installed(app["package"], self.installed_apps):
                continue
            found += 1
            var = self.check_vars[app["id"]]
            card = ItemCard(
                self.apps_inner, app["name"], app["description"],
                var=var, risk=app["risk"], risk_color=risk_colors[app["risk"]],
                alert=app.get("alert"),
            )
            card.pack(fill="x", padx=16, pady=2)
            self.app_card_frames[app["id"]] = card

        # W11 apps section
        if self.win11:
            w11_apps = [a for a in BLOATWARE_APPS if a.get("win11")]
            w11_found = [a for a in w11_apps if is_app_installed(a["package"], self.installed_apps)]
            if w11_found:
                sep = self._w11_section_header(self.apps_inner, "Apps exclusivas de Windows 11",
                                               "Apps con IA de Microsoft incluidas en Windows 11")
                sep.pack(fill="x", padx=16, pady=(20, 4))
                self.app_card_frames["_w11_sep_apps"] = sep
                for app in w11_found:
                    found += 1
                    var = self.check_vars[app["id"]]
                    card = ItemCard(
                        self.apps_inner, app["name"], app["description"],
                        var=var, risk=app["risk"], risk_color=risk_colors[app["risk"]],
                        alert=app.get("alert"),
                    )
                    card.pack(fill="x", padx=16, pady=2)
                    self.app_card_frames[app["id"]] = card

        if found == 0:
            lbl = tk.Label(self.apps_inner,
                           text="No se encontró bloatware conocido instalado en este equipo.",
                           font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["success"])
            lbl.pack(padx=16, pady=20)
            self.app_card_frames["_empty"] = lbl

    # ── Service cards ──────────────────────────────────────────────────

    def _refresh_service_cards(self):
        for w in self.svc_card_frames.values():
            w.destroy()
        self.svc_card_frames.clear()

        risk_colors = {"low": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}
        found = 0

        base_svcs = [s for s in SERVICES if not s.get("win11")]
        for svc in base_svcs:
            status = self.svc_status_cache.get(svc["service"], SVC_NOT_FOUND)
            if status == SVC_NOT_FOUND:
                continue
            found += 1
            var = self.check_vars[svc["id"]]
            card = ServiceCard(
                self.svcs_inner,
                name=svc["name"], description=svc["description"],
                var=var, risk=svc["risk"], risk_color=risk_colors[svc["risk"]],
                status=status,
                on_block=lambda s=svc: self._block_service_action(s),
                on_unblock=lambda s=svc: self._unblock_service_action(s),
                alert=svc.get("alert"),
            )
            card.pack(fill="x", padx=16, pady=2)
            self.svc_card_frames[svc["id"]] = card

        # W11 services section
        if self.win11:
            w11_svcs = [s for s in SERVICES if s.get("win11")]
            w11_found = []
            for svc in w11_svcs:
                status = self.svc_status_cache.get(svc["service"], SVC_NOT_FOUND)
                if status != SVC_NOT_FOUND:
                    w11_found.append((svc, status))
            if w11_found:
                sep = self._w11_section_header(self.svcs_inner, "Servicios exclusivos de Windows 11",
                                               "Servicios de IA y telemetría avanzada de W11")
                sep.pack(fill="x", padx=16, pady=(20, 4))
                self.svc_card_frames["_w11_sep_svcs"] = sep
                for svc, status in w11_found:
                    found += 1
                    var = self.check_vars[svc["id"]]
                    card = ServiceCard(
                        self.svcs_inner,
                        name=svc["name"], description=svc["description"],
                        var=var, risk=svc["risk"], risk_color=risk_colors[svc["risk"]],
                        status=status,
                        on_block=lambda s=svc: self._block_service_action(s),
                        on_unblock=lambda s=svc: self._unblock_service_action(s),
                        alert=svc.get("alert"),
                    )
                    card.pack(fill="x", padx=16, pady=2)
                    self.svc_card_frames[svc["id"]] = card

        if found == 0:
            lbl = tk.Label(self.svcs_inner,
                           text="No se encontraron servicios reconocidos.",
                           font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["text_muted"])
            lbl.pack(padx=16, pady=20)
            self.svc_card_frames["_empty"] = lbl


    # ── AI state persistence ──────────────────────────────────────────

    def _get_ai_state_path(self) -> str:
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ai_states.json")

    def _save_ai_states(self):
        """Persist all AI tab tweak toggle states to disk."""
        ai_ids = [item["id"] for item in self._get_all_ai_items()]
        states = {}
        for tid in ai_ids:
            card = self._tweak_cards.get(tid)
            if card:
                states[tid] = card._active
        try:
            path = self._get_ai_state_path()
            with open(path, "w", encoding="utf-8") as f:
                json.dump(states, f)
        except Exception:
            pass

    def _load_ai_states(self) -> dict:
        """Load persisted AI toggle states."""
        try:
            path = self._get_ai_state_path()
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _get_all_ai_items(self) -> list:
        return [
            {"id": "w11_recall"}, {"id": "w11_ai_search"}, {"id": "w11_typing_insights"},
            {"id": "w11_personalized_ads"}, {"id": "w11_voice_typing"},
            {"id": "w11_copilot_taskbar"}, {"id": "w11_widgets"}, {"id": "w11_snap_suggest"},
        ]

    def _restore_ai_states_from_disk(self):
        """After scan, override AI tweak states with persisted user choices."""
        saved = self._load_ai_states()
        if not saved:
            return
        for tid, active in saved.items():
            card = self._tweak_cards.get(tid)
            if card:
                card.set_active(active)
    def _block_service_action(self, svc: dict):
        if not messagebox.askyesno("Bloquear servicio",
                                   f"Bloquear '{svc['name']}'?\n\n"
                                   f"Se eliminan los trigger-start para que Windows no pueda activarlo automáticamente."):
            return
        ok, msg = block_service(svc["service"])
        if ok:
            self.svc_status_cache[svc["service"]] = SVC_BLOCKED
            self.status_text.set(f"{svc['name']} bloqueado")
        else:
            messagebox.showerror("Error", msg)
        self._refresh_service_cards()

    def _unblock_service_action(self, svc: dict):
        ok, msg = unblock_service(svc["service"])
        if ok:
            self.svc_status_cache[svc["service"]] = SVC_RUNNING
            self.status_text.set(f"{svc['name']} reactivado")
        else:
            messagebox.showerror("Error", msg)
        self._refresh_service_cards()

    # ── Tweaks tab ────────────────────────────────────────────────────

    def _build_tweaks_tab_content(self, parent):
        _, inner = self._make_scrollable(parent)
        categories = {
            "privacy":     "Privacidad y Telemetría",
            "performance": "Rendimiento",
            "gaming":      "Gaming",
        }
        risk_colors = {
            "low":    COLORS["success"],
            "medium": COLORS["warning"],
            "high":   COLORS["danger"],
        }
        self._tweak_cards = {}

        SectionHeader(inner, "Tweaks y Privacidad",
                      "ON = WinClean ha aplicado la restricción / optimización. "
                      "OFF = comportamiento original de Windows. "
                      "El estado se lee del sistema real al arrancar.").pack(
            fill="x", padx=16, pady=(16, 4))

        # Base tweaks by category
        for cat_id, cat_name in categories.items():
            cat_tweaks = [t for t in TWEAKS if t["category"] == cat_id and not t.get("win11")]
            if not cat_tweaks:
                continue
            SectionHeader(inner, cat_name, "").pack(fill="x", padx=16, pady=(16, 4))
            for tweak in cat_tweaks:
                initial = self.tweak_states.get(tweak["id"], False)
                card = TweakCard(
                    inner,
                    tweak_id=tweak["id"],
                    name=tweak["name"],
                    description=tweak["description"],
                    risk=tweak["risk"],
                    risk_color=risk_colors[tweak["risk"]],
                    on_enable=self._on_tweak_enable,
                    on_disable=self._on_tweak_disable,
                    initial_state=initial,
                    alert=tweak.get("alert"),
                )
                card.pack(fill="x", padx=16, pady=2)
                self._tweak_cards[tweak["id"]] = card

        # W11 tweaks section
        if self.win11:
            w11_tweaks = [t for t in TWEAKS if t.get("win11")]
            if w11_tweaks:
                sep = self._w11_section_header(inner, "Tweaks exclusivos de Windows 11",
                                               "Ajustes de IA, Recall y características específicas de W11")
                sep.pack(fill="x", padx=16, pady=(24, 4))
                for tweak in w11_tweaks:
                    initial = self.tweak_states.get(tweak["id"], False)
                    card = TweakCard(
                        inner,
                        tweak_id=tweak["id"],
                        name=tweak["name"],
                        description=tweak["description"],
                        risk=tweak["risk"],
                        risk_color=risk_colors[tweak["risk"]],
                        on_enable=self._on_tweak_enable,
                        on_disable=self._on_tweak_disable,
                        initial_state=initial,
                        alert=tweak.get("alert"),
                    )
                    card.pack(fill="x", padx=16, pady=2)
                    self._tweak_cards[tweak["id"]] = card

    def _refresh_tweak_states(self):
        """After a scan, update all existing tweak card toggle states."""
        for tweak_id, card in self._tweak_cards.items():
            state = self.tweak_states.get(tweak_id, False)
            card.set_active(state)

    def _on_tweak_enable(self, tweak_id: str):
        self.status_text.set(f"Aplicando: {tweak_id}...")
        def do():
            ok, msg = apply_tweak(tweak_id)
            name = next((t["name"] for t in TWEAKS if t["id"] == tweak_id), tweak_id)
            self.after(0, lambda: self.status_text.set(
                f"✅ {name} — restricción aplicada" if ok else f"Error: {msg[:60]}"
            ))
            self.after(100, self._save_ai_states)
        threading.Thread(target=do, daemon=True).start()

    def _on_tweak_disable(self, tweak_id: str):
        self.status_text.set(f"Revirtiendo: {tweak_id}...")
        def do():
            ok, msg = revert_tweak(tweak_id)
            name = next((t["name"] for t in TWEAKS if t["id"] == tweak_id), tweak_id)
            self.after(0, lambda: self.status_text.set(
                f"✅ {name} — restaurado a original" if ok else f"Error: {msg[:60]}"
            ))
            self.after(100, self._save_ai_states)
        threading.Thread(target=do, daemon=True).start()

    # ── AI tab (W11 only) ──────────────────────────────────────────────

    def _build_ai_tab(self, parent):
        _, inner = self._make_scrollable(parent)

        SectionHeader(
            inner,
            "🤖  Características de IA de Windows 11",
            "Funciones y servicios de IA de W11. "
            "Toggle ON/OFF: ON = WinClean ha desactivado la característica · OFF = activa (estado original de Microsoft). "
            "Servicios: marca los que quieres desactivar y pulsa 'Aplicar configuración'."
        ).pack(fill="x", padx=16, pady=(16, 8))

        risk_colors = {"low": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}

        # ── Group 1: Privacy / data collection AI ────────────────────
        ai_privacy = [
            {
                "id": "w11_recall",
                "name": "Windows Recall",
                "description": "⚠ Captura pantallas cada pocos segundos y las analiza con IA local. "
                               "Alto riesgo de privacidad — almacena TODO lo que haces en tu PC.",
                "risk": "high",
            },
            {
                "id": "w11_ai_search",
                "name": "Búsqueda con IA mejorada",
                "description": "El menú inicio y la barra de búsqueda usan IA para sugerir resultados. "
                               "Envía consultas a servidores de Microsoft.",
                "risk": "low",
            },
            {
                "id": "w11_typing_insights",
                "name": "Typing Insights (Estadísticas de escritura)",
                "description": "Recopila datos de tu teclado para 'mejorar' el autocompletado con IA. "
                               "Inútil en la práctica.",
                "risk": "low",
            },
            {
                "id": "w11_personalized_ads",
                "name": "Experiencias personalizadas por IA",
                "description": "Usa datos de uso del sistema para personalizar sugerencias y anuncios "
                               "en Windows y apps de Microsoft.",
                "risk": "low",
            },
            {
                "id": "w11_voice_typing",
                "name": "Escritura por voz (nube)",
                "description": "El dictado de W11 puede enviar audio a Microsoft para procesarlo. "
                               "Si usas dictado, actívalo solo en local.",
                "risk": "medium",
            },
        ]

        SectionHeader(inner, "IA de recopilación de datos", "").pack(fill="x", padx=16, pady=(12, 4))
        for item in ai_privacy:
            initial = self.tweak_states.get(item["id"], False)
            card = TweakCard(
                inner,
                tweak_id=item["id"],
                name=item["name"],
                description=item["description"],
                risk=item["risk"],
                risk_color=risk_colors[item["risk"]],
                on_enable=self._on_tweak_enable,
                on_disable=self._on_tweak_disable,
                initial_state=initial,
            )
            card.pack(fill="x", padx=16, pady=2)
            # share card with tweaks dict so states sync
            self._tweak_cards[item["id"]] = card

        # ── Group 2: UI / interface AI bloat ─────────────────────────
        ai_ui = [
            {
                "id": "w11_copilot_taskbar",
                "name": "Botón Copilot en barra de tareas",
                "description": "El icono de Copilot ocupa espacio en la barra y lanza el panel de IA al hacer clic. "
                               "Completamente prescindible.",
                "risk": "low",
            },
            {
                "id": "w11_widgets",
                "name": "Panel de Widgets",
                "description": "El panel lateral de W11 muestra noticias, bolsa y clima personalizado por IA. "
                               "Carga en segundo plano aunque no lo uses.",
                "risk": "low",
            },
            {
                "id": "w11_snap_suggest",
                "name": "Sugerencias de Snap Layout",
                "description": "W11 usa IA para sugerir cómo distribuir ventanas al pasar el cursor por el botón maximizar. "
                               "Tiene latencia visible y consume CPU.",
                "risk": "low",
            },
        ]

        SectionHeader(inner, "IA de interfaz de usuario", "").pack(fill="x", padx=16, pady=(16, 4))
        for item in ai_ui:
            initial = self.tweak_states.get(item["id"], False)
            card = TweakCard(
                inner,
                tweak_id=item["id"],
                name=item["name"],
                description=item["description"],
                risk=item["risk"],
                risk_color=risk_colors[item["risk"]],
                on_enable=self._on_tweak_enable,
                on_disable=self._on_tweak_disable,
                initial_state=initial,
            )
            card.pack(fill="x", padx=16, pady=2)
            self._tweak_cards[item["id"]] = card

        # ── Group 3: AI services consuming resources ──────────────────
        SectionHeader(inner, "Servicios de IA que más consumen",
                      "Marca los que quieres DESACTIVAR y pulsa 'Aplicar configuración'. "
                      "Estado actual:  Verde=En ejecución  Amarillo=Detenido  Gris=Desactivado  Morado=Bloqueado"
                      ).pack(fill="x", padx=16, pady=(16, 4))

        # Store reference to inner so _refresh_ai_svc_cards can populate it
        self._ai_svc_inner = inner

    def _refresh_ai_svc_cards(self):
        """Rebuild AI service cards in the IA tab after a scan."""
        if not hasattr(self, "_ai_svc_inner"):
            return
        for w in self._ai_svc_card_frames.values():
            w.destroy()
        self._ai_svc_card_frames.clear()

        risk_colors = {"low": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}
        found = 0
        for svc in AI_SERVICES:
            status = self.svc_status_cache.get(svc["service"], SVC_NOT_FOUND)
            if status == SVC_NOT_FOUND:
                continue
            found += 1
            var = self.check_vars[svc["id"]]
            card = ServiceCard(
                self._ai_svc_inner,
                name=svc["name"], description=svc["description"],
                var=var, risk=svc["risk"], risk_color=risk_colors[svc["risk"]],
                status=status,
                on_block=lambda s=svc: self._block_ai_svc_action(s),
                on_unblock=lambda s=svc: self._unblock_ai_svc_action(s),
            )
            card.pack(fill="x", padx=16, pady=2)
            self._ai_svc_card_frames[svc["id"]] = card

        if found == 0:
            lbl = tk.Label(self._ai_svc_inner,
                           text="No se encontraron servicios de IA en este sistema.",
                           font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["text_muted"])
            lbl.pack(padx=16, pady=8)
            self._ai_svc_card_frames["_empty"] = lbl

    def _block_ai_svc_action(self, svc: dict):
        if not messagebox.askyesno("Bloquear servicio de IA",
                                   f"¿Bloquear '{svc['name']}'?\n"
                                   f"Se eliminan los trigger-start para que Windows no pueda activarlo automáticamente."):
            return
        ok, msg = block_service(svc["service"])
        if ok:
            self.svc_status_cache[svc["service"]] = SVC_BLOCKED
            self.status_text.set(f"{svc['name']} bloqueado")
        else:
            messagebox.showerror("Error", msg)
        self._refresh_ai_svc_cards()

    def _unblock_ai_svc_action(self, svc: dict):
        ok, msg = unblock_service(svc["service"])
        if ok:
            self.svc_status_cache[svc["service"]] = SVC_RUNNING
            self.status_text.set(f"{svc['name']} reactivado")
        else:
            messagebox.showerror("Error", msg)
        self._refresh_ai_svc_cards()

    # ── Resources tab ──────────────────────────────────────────────────

    def _build_resources_tab(self, parent):
        # ── Power plan selector (top) ──────────────────────────────
        top = tk.Frame(parent, bg=COLORS["surface"], pady=10, padx=16)
        top.pack(fill="x")

        tk.Label(top, text="⚡  GESTOR DE RECURSOS", font=FONTS["label"],
                 bg=COLORS["surface"], fg=COLORS["accent"]).pack(side="left")

        refresh_btn = tk.Button(
            top, text="↺  Actualizar lista",
            command=self._scan_resources,
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=3,
            activebackground=COLORS["btn_hover"],
        )
        refresh_btn.pack(side="right")

        # ── Power profiles bar ─────────────────────────────────────
        power_frame = tk.Frame(parent, bg=COLORS["bg"], pady=6, padx=16)
        power_frame.pack(fill="x")

        tk.Label(power_frame, text="⚡ Perfil de energía:", font=FONTS["small"],
                 bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(side="left", padx=(0, 8))

        self._power_var = tk.StringVar(value="system_default")
        self._power_btns = {}

        # Predeterminado del sistema
        btn_sys = tk.Button(
            power_frame, text="🖥️  Predeterminado del sistema",
            command=lambda: self._set_power_plan("system_default"),
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=4, activebackground=COLORS["btn_hover"],
        )
        btn_sys.pack(side="left", padx=3)
        self._power_btns["system_default"] = btn_sys

        # Subgrupo ahorro
        saver_outer = tk.Frame(power_frame, bg=COLORS["bg"])
        saver_outer.pack(side="left", padx=3)
        tk.Label(saver_outer, text="🔋 Ahorro:", font=FONTS["small"],
                 bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(side="left", padx=(0, 2))

        if self.is_laptop:
            btn_sw = tk.Button(
                saver_outer, text="Batería (Windows)",
                command=lambda: self._set_power_plan("saver_windows"),
                bg=COLORS["btn"], fg=COLORS["text_muted"],
                font=FONTS["small"], relief="flat", cursor="hand2",
                padx=6, pady=4, activebackground=COLORS["btn_hover"],
            )
            btn_sw.pack(side="left", padx=2)
            self._power_btns["saver_windows"] = btn_sw

        btn_sl = tk.Button(
            saver_outer, text="🌿 Liviano",
            command=lambda: self._set_power_plan("saver_light"),
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=6, pady=4, activebackground=COLORS["btn_hover"],
        )
        btn_sl.pack(side="left", padx=2)
        self._power_btns["saver_light"] = btn_sl

        btn_se = tk.Button(
            saver_outer, text="⚡ Extremo",
            command=lambda: self._set_power_plan("saver_extreme"),
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=6, pady=4, activebackground=COLORS["btn_hover"],
        )
        btn_se.pack(side="left", padx=2)
        self._power_btns["saver_extreme"] = btn_se

        # Alto rendimiento (con aviso en portátil)
        high_wrap = tk.Frame(power_frame, bg=COLORS["bg"])
        high_wrap.pack(side="left", padx=3)
        btn_high = tk.Button(
            high_wrap, text="🚀 Alto rendimiento",
            command=lambda: self._set_power_plan("high"),
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=4, activebackground=COLORS["btn_hover"],
        )
        btn_high.pack(side="top")
        self._power_btns["high"] = btn_high
        if self.is_laptop:
            tk.Label(
                high_wrap,
                text="⚠️ Consume batería considerablemente",
                font=("Segoe UI", 7), bg=COLORS["bg"], fg="#f5a623",
            ).pack(side="top")

        # Leer plan actual y resaltar
        self.after(300, self._refresh_power_btn_states)

        # ── Info bar ───────────────────────────────────────────────
        sub = tk.Frame(parent, bg=COLORS["bg"], pady=4, padx=16)
        sub.pack(fill="x")
        tk.Label(sub,
                 text="Ajusta CPU, RAM y GPU individualmente por proceso. "
                      "Pulsa Aplicar en cada app para ejercer el límite. Restablecer elimina el límite.",
                 font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"],
                 wraplength=800, justify="left").pack(side="left")

        # ── Scrollable process list ────────────────────────────────
        self._res_canvas, self._res_inner = self._make_scrollable(parent)
        self.after(500, self._scan_resources)

    def _set_power_plan(self, plan_id: str):
        def do():
            ok, name = set_power_plan(plan_id)
            self.after(0, lambda: self.status_text.set(
                f"✅ Perfil activado: {name}" if ok else f"Error al cambiar perfil de energía"
            ))
            self.after(0, self._refresh_power_btn_states)
        threading.Thread(target=do, daemon=True).start()

    def _refresh_power_btn_states(self):
        active = get_active_power_plan()
        for plan_id, btn in self._power_btns.items():
            is_active = (plan_id == active) or (
                plan_id == "saver_windows" and active in ("saver_extreme", "saver_light")
            )
            if is_active:
                btn.config(bg=COLORS["accent"], fg="#000000",
                           activebackground=COLORS["accent_hover"])
            else:
                btn.config(bg=COLORS["btn"], fg=COLORS["text_muted"],
                           activebackground=COLORS["btn_hover"])

    def _scan_resources(self):
        self.status_text.set("Escaneando procesos activos...")
        def do():
            procs = rm.get_running_processes()
            self.after(0, lambda: self._render_resource_cards(procs))
        threading.Thread(target=do, daemon=True).start()

    def _render_resource_cards(self, procs: list):
        for w in self._res_inner.winfo_children():
            w.destroy()
        self._resource_cards.clear()
        self._resource_procs = procs

        SectionHeader(
            self._res_inner,
            f"Procesos activos ({len(procs)})",
            "Cada fila muestra el proceso y sus controles individuales de CPU, RAM y GPU. "
            "Pulsa Aplicar en cada proceso para activar el límite. Restablecer lo quita.",
        ).pack(fill="x", padx=16, pady=(12, 6))

        if not procs:
            tk.Label(self._res_inner,
                     text="No se encontraron procesos con ventana activa.",
                     font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(pady=20)
            self.status_text.set("No se encontraron procesos")
            return

        for proc in procs:
            card = ProcessResourceCard(
                self._res_inner,
                proc=proc,
                on_apply=self._on_resource_apply,
                on_reset=self._on_resource_reset,
                on_kill=self._on_resource_kill,
            )
            card.pack(fill="x", padx=16, pady=2)
            self._resource_cards[proc["name"]] = card

        self.status_text.set(f"{len(procs)} procesos cargados — ajusta individualmente y pulsa Aplicar")

    def _on_resource_apply(self, pid, name, cpu_pct, ram_mb, ram_min, gpu_pct):
        self.status_text.set(f"Aplicando límites a {name}...")
        def do():
            results = rm.apply_limits(pid, name, cpu_pct, ram_mb, ram_min, gpu_pct)
            errors = [f"{k}: {v[1]}" for k, v in results.items() if not v[0] and v[1] != "N/A"]
            if errors:
                self.after(0, lambda: self.status_text.set(f"⚠ {name}: {', '.join(errors[:2])}"))
            else:
                self.after(0, lambda: self.status_text.set(f"✅ Límites aplicados a {name}"))
        threading.Thread(target=do, daemon=True).start()

    def _on_resource_reset(self, pid, name):
        self.status_text.set(f"Restableciendo {name}...")
        def do():
            rm.reset_limits(pid)
            self.after(0, lambda: self.status_text.set(f"✅ {name} restablecido"))
        threading.Thread(target=do, daemon=True).start()

    def _on_resource_kill(self, pid, name):
        from tkinter import messagebox
        msg = ("Terminar FORZOSAMENTE el proceso '" + name + "' (PID " + str(pid) + ")?"
               " Cualquier trabajo sin guardar se perdera.")
        if not messagebox.askyesno("Matar proceso", msg, icon="warning"):
            return
        self.status_text.set(f"Matando proceso {name}...")
        def do():
            import subprocess
            try:
                subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
                self.after(0, lambda: self.status_text.set(f"✅ Proceso {name} terminado"))
                self.after(500, self._scan_resources)
            except Exception as e:
                self.after(0, lambda: self.status_text.set(f"Error al matar {name}: {e}"))
        threading.Thread(target=do, daemon=True).start()

    # ── Locks tab ─────────────────────────────────────────────────────

    # Definition of all function locks
    _LOCK_ITEMS = [
        {
            "id":      "lock_rdp",
            "name":    "Acceso Remoto (RDP)",
            "desc":    "Desactiva el servicio de Escritorio Remoto y cierra el puerto 3389. "
                       "Impide que alguien controle la pantalla del PC desde la red.",
            "svc":     "TermService",
            "port":    3389,
            "reg_key": r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server",
            "reg_val": "fDenyTSConnections",
            "fw_rule": "WinClean_Block_RDP",
        },
        {
            "id":    "lock_remote_assist",
            "name":  "Asistencia Remota",
            "desc":  "Desactiva la Asistencia Remota de Windows (MSRA). "
                     "Evita que otro usuario reciba o solicite control del equipo.",
            "svc":   None,
            "port":  None,
            "reg_key": r"HKLM\SYSTEM\CurrentControlSet\Control\Remote Assistance",
            "reg_val": "fAllowToGetHelp",
        },
        {
            "id":    "lock_winrm",
            "name":  "WinRM (PowerShell remoto)",
            "desc":  "Desactiva el servicio Windows Remote Management. "
                     "Bloquea la ejecución remota de comandos PowerShell/WMI.",
            "svc":   "WinRM",
            "port":  5985,
            "fw_rule": "WinClean_Block_WinRM",
        },
        {
            "id":    "lock_vnc_port",
            "name":  "Puerto VNC (5900)",
            "desc":  "Añade regla de Firewall de Windows para bloquear el puerto TCP 5900. "
                     "Impide conexiones de herramientas VNC (RealVNC, TightVNC, etc.).",
            "svc":   None,
            "port":  5900,
            "fw_rule": "WinClean_Block_VNC",
        },
        {
            "id":    "lock_net_share",
            "name":  "Uso Compartido de Red (SMB)",
            "desc":  "Detiene y desactiva LanmanServer (el servidor SMB). "
                     "Ningún otro equipo de la red podrá acceder a carpetas compartidas de este PC.",
            "svc":   "LanmanServer",
            "port":  445,
            "fw_rule": "WinClean_Block_SMB",
        },
        {
            "id":    "lock_screen_capture",
            "name":  "Captura de pantalla remota (DXGI)",
            "desc":  "Aplica una restricción de registro que impide la duplicación DXGI en sesiones remotas. "
                     "Herramientas de captura/espejo de pantalla no funcionarán desde fuera.",
            "svc":   None,
            "port":  None,
            "reg_key": r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services",
            "reg_val": "fDisableScreenCapture",
        },
        {
            "id":    "lock_spice",
            "name":  "Puerto SPICE (5910)",
            "desc":  "Bloquea el puerto TCP 5910 usado por el protocolo SPICE (Simple Protocol for Independent Computing Environments). "
                     "Impide control remoto de pantalla en entornos virtualizados (KVM, QEMU, oVirt).",
            "svc":   None,
            "port":  5910,
            "fw_rule": "WinClean_Block_SPICE",
        },
        {
            "id":    "lock_nx",
            "name":  "Puerto NX/NoMachine (4000)",
            "desc":  "Bloquea el puerto TCP 4000 usado por NoMachine NX y herramientas similares de escritorio remoto. "
                     "Impide sesiones remotas de pantalla a través de este protocolo.",
            "svc":   None,
            "port":  4000,
            "fw_rule": "WinClean_Block_NX",
        },
        {
            "id":    "lock_teamviewer",
            "name":  "Puerto TeamViewer (5938)",
            "desc":  "Bloquea el puerto TCP/UDP 5938 principal de TeamViewer. "
                     "Dificulta las conexiones entrantes y salientes de control remoto y compartición de pantalla de TeamViewer.",
            "svc":   None,
            "port":  5938,
            "fw_rule": "WinClean_Block_TeamViewer",
            "fw_rule_udp": "WinClean_Block_TeamViewer_UDP",
        },
        {
            "id":    "lock_anydesk",
            "name":  "Puerto AnyDesk (7070)",
            "desc":  "Bloquea el puerto TCP 7070 usado por AnyDesk para conexiones directas de escritorio remoto entre equipos de la red local.",
            "svc":   None,
            "port":  7070,
            "fw_rule": "WinClean_Block_AnyDesk",
        },
        {
            "id":    "lock_rdp_udp",
            "name":  "RDP UDP (3389 UDP)",
            "desc":  "Bloquea el puerto UDP 3389 usado por las versiones modernas de RDP para transporte de vídeo acelerado (RDP-UDP). "
                     "Complemento al bloqueo RDP TCP para una protección completa del escritorio remoto.",
            "svc":   None,
            "port":  3389,
            "fw_rule": "WinClean_Block_RDP_UDP",
            "protocol": "UDP",
        },
        {
            "id":    "lock_winrm_https",
            "name":  "WinRM HTTPS (5986)",
            "desc":  "Bloquea el puerto TCP 5986 usado por WinRM sobre HTTPS. "
                     "Impide la ejecución remota cifrada de comandos PowerShell/WMI que evita el puerto 5985.",
            "svc":   None,
            "port":  5986,
            "fw_rule": "WinClean_Block_WinRM_HTTPS",
        },
        {
            "id":    "lock_netbios",
            "name":  "NetBIOS (137-139)",
            "desc":  "Bloquea los puertos TCP/UDP 137, 138 y 139 de NetBIOS. "
                     "Impide la resolución de nombres y transferencias de archivos legacy en la red local que pueden exponer recursos del equipo.",
            "svc":   None,
            "port":  137,
            "fw_rule": "WinClean_Block_NetBIOS",
        },
        {
            "id":    "lock_faronics",
            "name":  "Faronics Insight (796, 11796, 1053, 8080, 8085, 8888-8890)",
            "desc":  "Bloquea todos los puertos usados por Faronics Insight: 796 y 11796 (control remoto alumno/profesor), "
                     "1053 UDP (estado), 8080/8085 (Connection Server), 8888/8889/8890 (WebSocket Insight 11). "
                     "Impide que el software de monitorización escolar controle o vea la pantalla de este equipo.",
            "svc":   None,
            "port":  796,
            "fw_rule": "WinClean_Block_Faronics",
        },
    ]

    def _build_locks_tab(self, parent):
        """Build the BLOQUEOS DE FUNCIÓN tab with internal sub-notebook."""
        self._lock_states  = {}
        self._lock_btns    = {}
        self._lock_ind     = {}
        self._lock_status  = {}

        # ── Internal sub-notebook ────────────────────────────────────
        sub_nb = ttk.Notebook(parent)
        sub_nb.pack(fill="both", expand=True)

        locks_frame = tk.Frame(sub_nb, bg=COLORS["bg"])
        apps_frame  = tk.Frame(sub_nb, bg=COLORS["bg"])
        sub_nb.add(locks_frame, text="🔒 Puertos y Servicios")
        sub_nb.add(apps_frame,  text="🛡️ Control de Aplicaciones")

        self._build_locks_subtab(locks_frame)
        self._build_appcontrol_tab(apps_frame)

    def _build_locks_subtab(self, parent):
        """Build the ports/services lock cards sub-tab."""
        # ── Header ──────────────────────────────────────────────────
        hdr = tk.Frame(parent, bg=COLORS["surface"], pady=10, padx=16)
        hdr.pack(fill="x")

        tk.Label(hdr, text="🔒  BLOQUEOS DE FUNCIÓN", font=FONTS["label"],
                 bg=COLORS["surface"], fg=COLORS["accent"]).pack(side="left")

        rescan_btn = tk.Button(
            hdr, text="↺  Detectar red",
            command=self._locks_detect_network,
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=3, activebackground=COLORS["btn_hover"],
        )
        rescan_btn.pack(side="right")

        # ── LAN alert banner ────────────────────────────────────────
        self._lan_banner_frame = tk.Frame(parent, bg=COLORS["bg"], pady=6, padx=16)
        self._lan_banner_frame.pack(fill="x")
        self._lan_alert_lbl = tk.Label(
            self._lan_banner_frame,
            text="⏳  Detectando red local...",
            font=FONTS["body"],
            bg=COLORS["bg"], fg=COLORS["text_muted"],
            anchor="w",
        )
        self._lan_alert_lbl.pack(fill="x")

        # ── Subtitle ─────────────────────────────────────────────────
        sub = tk.Frame(parent, bg=COLORS["bg"], pady=2, padx=16)
        sub.pack(fill="x")
        tk.Label(
            sub,
            text="ON = restricción activa (WinClean bloquea el acceso)  ·  OFF = comportamiento original de Windows sin restricciones",
            font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"],
            anchor="w",
        ).pack(fill="x")

        # ── Scrollable lock cards ────────────────────────────────────
        _, inner = self._make_scrollable(parent)

        for item in self._LOCK_ITEMS:
            self._lock_states[item["id"]] = False
            self._build_lock_card(inner, item)

        # ── Botón de Aislamiento Total ───────────────────────────────
        tk.Frame(inner, bg=COLORS["bg"], height=8).pack(fill="x")
        tk.Frame(inner, bg="#441111", height=1).pack(fill="x", padx=16)

        iso_frame = tk.Frame(inner, bg="#1a0a0a", pady=16, padx=16)
        iso_frame.pack(fill="x", pady=(0, 8))

        iso_left = tk.Frame(iso_frame, bg="#1a0a0a")
        iso_left.pack(side="left", fill="both", expand=True)

        tk.Label(iso_left,
                 text="🚨  AISLAMIENTO TOTAL DE RED",
                 font=FONTS["label"],
                 bg="#1a0a0a", fg="#ff4444").pack(anchor="w")
        tk.Label(iso_left,
                 text="Bloquea TODO el tráfico de red entrante y saliente mediante el Firewall de Windows.\n"
                      "Para bloquear solo aplicaciones específicas, usa la pestaña 🛡️ Control de Aplicaciones.\n"
                      "El equipo sigue funcionando de forma local. Para restaurar, pulsa el botón de nuevo.",
                 font=FONTS["small"],
                 bg="#1a0a0a", fg="#cc8888",
                 wraplength=620, justify="left", anchor="w").pack(anchor="w", pady=(2, 0))

        self._iso_status_lbl = tk.Label(iso_left,
                 text="Estado: conectado a la red",
                 font=FONTS["small"],
                 bg="#1a0a0a", fg="#cc4444", anchor="w")
        self._iso_status_lbl.pack(anchor="w", pady=(4, 0))

        self._iso_btn = tk.Button(
            iso_frame,
            text="⛔  AISLAR\nEQUIPO",
            width=12,
            command=self._toggle_isolation,
            bg="#5a1010", fg="#ff6666",
            font=("Segoe UI", 9, "bold"),
            relief="flat", cursor="hand2",
            pady=10, activebackground="#7a1515",
            wraplength=90,
        )
        self._iso_btn.pack(side="right", padx=(10, 0))

        self._isolation_active = False
        self.after(600, self._check_isolation_state)

        # Start async network detection + state read
        self.after(400, self._locks_detect_network)
        self.after(500, self._locks_read_all_states)

    def _check_isolation_state(self):
        """Check if network isolation is currently active and update UI."""
        def do():
            import subprocess
            try:
                result = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule",
                     "name=WinClean_ISOLATION_IN"],
                    capture_output=True, text=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                active = "No rules match" not in result.stdout and "WinClean_ISOLATION_IN" in result.stdout
            except Exception:
                active = False
            self.after(0, lambda: self._update_isolation_ui(active))
        threading.Thread(target=do, daemon=True).start()

    def _update_isolation_ui(self, active: bool):
        self._isolation_active = active
        if not hasattr(self, '_iso_btn'):
            return
        if active:
            self._iso_btn.config(
                text="✅  REACTIVAR\nRED",
                bg="#0a3a0a", fg="#55ee55",
                activebackground="#0e500e",
            )
            self._iso_status_lbl.config(
                text="🔴  AISLADO — Sin acceso a red. El equipo funciona solo de forma local.",
                fg="#ff4444",
            )
        else:
            self._iso_btn.config(
                text="⛔  AISLAR\nEQUIPO",
                bg="#5a1010", fg="#ff6666",
                activebackground="#7a1515",
            )
            self._iso_status_lbl.config(
                text="🟢  Estado: conectado a la red (sin aislamiento activo)",
                fg="#55aa55",
            )

    def _toggle_isolation(self):
        """Toggle complete network isolation on/off."""
        if self._isolation_active:
            msg = ("¿Desactivar el aislamiento de red?\n\n"
                   "El equipo volverá a tener acceso completo a la red.")
            confirm_title = "Desactivar aislamiento"
        else:
            msg = ("⚠️  ¿AISLAR COMPLETAMENTE ESTE EQUIPO DE LA RED?\n\n"
                   "Se bloqueará TODO el tráfico de red (entrante y saliente).\n"
                   "Internet y la red local dejarán de funcionar.\n\n"
                   "El equipo seguirá funcionando con normalidad de forma local.\n"
                   "Para restaurar la red, pulsa el botón de nuevo.")
            confirm_title = "Aislamiento total de red"

        if not messagebox.askyesno(confirm_title, msg):
            return

        self._iso_btn.config(state="disabled")
        self.status_text.set("Aplicando cambios de aislamiento de red...")

        def do():
            import subprocess
            cf = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            ok = True
            err = ""
            try:
                if not self._isolation_active:
                    # Block ALL inbound traffic
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        "name=WinClean_ISOLATION_IN", "dir=in", "action=block",
                        "protocol=any", "localip=any", "remoteip=any",
                    ], check=True, capture_output=True, creationflags=cf)
                    # Block ALL outbound traffic
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        "name=WinClean_ISOLATION_OUT", "dir=out", "action=block",
                        "protocol=any", "localip=any", "remoteip=any",
                    ], check=True, capture_output=True, creationflags=cf)
                    new_state = True
                else:
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        "name=WinClean_ISOLATION_IN",
                    ], capture_output=True, creationflags=cf)
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        "name=WinClean_ISOLATION_OUT",
                    ], capture_output=True, creationflags=cf)
                    new_state = False
            except subprocess.CalledProcessError as e:
                ok = False
                new_state = self._isolation_active
                err = e.stderr.decode(errors="replace") if e.stderr else str(e)
            except Exception as e:
                ok = False
                new_state = self._isolation_active
                err = str(e)

            def finish():
                self._iso_btn.config(state="normal")
                if ok:
                    self._update_isolation_ui(new_state)
                    verb = "AISLADO" if new_state else "Aislamiento desactivado — red restaurada"
                    self.status_text.set(f"{'🔴 Equipo ' if new_state else '🟢 '}{verb}")
                else:
                    self.status_text.set(f"❌ Error en aislamiento: {err[:80]}")
                    messagebox.showerror("Error de aislamiento",
                                         f"No se pudo cambiar el estado de aislamiento:\n\n{err}\n\n"
                                         "Comprueba que WinClean se ejecuta como Administrador.")
            self.after(0, finish)

        threading.Thread(target=do, daemon=True).start()

    # ══════════════════════════════════════════════════════════════════
    # APP CONTROL TAB — scan running connections, block per process
    # ══════════════════════════════════════════════════════════════════

    def _build_appcontrol_tab(self, parent):
        """Build the per-application network control tab."""
        self._appctrl_blocked  = {}   # proc_name -> bool
        self._appctrl_cards    = {}   # proc_name -> frame
        self._appctrl_btns     = {}   # proc_name -> button
        self._appctrl_dot      = {}   # proc_name -> dot label
        self._appctrl_scanning = False

        # ── Header ──────────────────────────────────────────────────
        hdr = tk.Frame(parent, bg=COLORS["surface"], pady=10, padx=16)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🛡️  CONTROL DE APLICACIONES EN RED",
                 font=FONTS["label"], bg=COLORS["surface"], fg=COLORS["accent"]).pack(side="left")

        scan_btn = tk.Button(
            hdr, text="↺  Escanear",
            command=self._appctrl_scan,
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=3, activebackground=COLORS["btn_hover"],
        )
        scan_btn.pack(side="right")
        self._appctrl_scan_btn = scan_btn

        block_all_btn = tk.Button(
            hdr, text="⛔  Bloquear todas",
            command=self._appctrl_block_all,
            bg="#5a1010", fg="#ff6666",
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=3, activebackground="#7a1515",
        )
        block_all_btn.pack(side="right", padx=(0, 6))

        unblock_all_btn = tk.Button(
            hdr, text="✅  Restaurar todas",
            command=self._appctrl_unblock_all,
            bg="#0a3a0a", fg="#55ee55",
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=3, activebackground="#0e500e",
        )
        unblock_all_btn.pack(side="right", padx=(0, 6))

        # ── Subtitle ────────────────────────────────────────────────
        sub = tk.Frame(parent, bg=COLORS["bg"], pady=4, padx=16)
        sub.pack(fill="x")
        tk.Label(
            sub,
            text="Aplicaciones detectadas usando la red ahora mismo. Puedes bloquear su tráfico saliente individualmente o todas a la vez.",
            font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"],
            anchor="w", wraplength=780,
        ).pack(fill="x")

        # ── Scan status label ────────────────────────────────────────
        self._appctrl_status_lbl = tk.Label(
            parent, text="Pulsa ↺ Escanear para detectar aplicaciones activas en red.",
            font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"],
            anchor="w", padx=16,
        )
        self._appctrl_status_lbl.pack(fill="x", pady=(0, 4))

        # ── Scrollable results area ──────────────────────────────────
        _, self._appctrl_inner = self._make_scrollable(parent)

    def _appctrl_scan(self):
        """Async: scan netstat for active connections and populate cards."""
        if self._appctrl_scanning:
            return
        self._appctrl_scanning = True
        self._appctrl_scan_btn.config(state="disabled", text="⏳  Escaneando...")
        self._appctrl_status_lbl.config(text="Escaneando conexiones activas...", fg=COLORS["text_muted"])

        def do():
            import subprocess, re
            procs = {}   # name -> {pids, ports, protos}

            # netstat -ano gives: Proto  Local  Foreign  State  PID
            try:
                out = subprocess.check_output(
                    ["netstat", "-ano"],
                    text=True, timeout=15,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
            except Exception as e:
                self.after(0, lambda: self._appctrl_done(procs, f"Error netstat: {e}"))
                return

            pid_to_name = {}
            # Build PID->name map via tasklist
            try:
                tl = subprocess.check_output(
                    ["tasklist", "/fo", "csv", "/nh"],
                    text=True, timeout=10,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                for line in tl.splitlines():
                    parts = [p.strip('"') for p in line.split('","')]
                    if len(parts) >= 2:
                        try:
                            pid_to_name[int(parts[1])] = parts[0]
                        except ValueError:
                            pass
            except Exception:
                pass

            for line in out.splitlines():
                line = line.strip()
                m = re.match(
                    r"(TCP|UDP)\s+[\d\.\[\]:]+:(\d+)\s+[\d\.\[\]:]+:\S+\s+(?:ESTABLISHED|LISTENING|TIME_WAIT|CLOSE_WAIT|SYN_SENT)?\s*(\d+)",
                    line,
                )
                if not m:
                    continue
                proto, port, pid_str = m.group(1), int(m.group(2)), int(m.group(3))
                if pid_str == 0:
                    continue
                name = pid_to_name.get(pid_str, f"PID {pid_str}")
                # Skip system noise
                if name.lower() in ("system", "svchost.exe", "lsass.exe", "services.exe",
                                    "wininit.exe", "csrss.exe", "smss.exe", "ntoskrnl.exe"):
                    continue
                if name not in procs:
                    procs[name] = {"ports": set(), "protos": set(), "pids": set()}
                procs[name]["ports"].add(port)
                procs[name]["protos"].add(proto)
                procs[name]["pids"].add(pid_str)

            self.after(0, lambda: self._appctrl_done(procs, None))

        threading.Thread(target=do, daemon=True).start()

    def _appctrl_done(self, procs: dict, error: str | None):
        """Populate the cards area after a scan."""
        self._appctrl_scanning = False
        self._appctrl_scan_btn.config(state="normal", text="↺  Escanear")

        if error:
            self._appctrl_status_lbl.config(text=f"❌ {error}", fg=COLORS["danger"])
            return

        # Clear old cards
        for w in self._appctrl_inner.winfo_children():
            w.destroy()
        self._appctrl_cards.clear()
        self._appctrl_btns.clear()
        self._appctrl_dot.clear()

        if not procs:
            tk.Label(self._appctrl_inner,
                     text="No se detectaron aplicaciones con conexiones activas.",
                     font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["text_muted"],
                     anchor="w", padx=16).pack(fill="x", pady=20)
            self._appctrl_status_lbl.config(
                text="Sin conexiones activas detectadas.", fg=COLORS["text_muted"])
            return

        for name, info in sorted(procs.items(), key=lambda x: x[0].lower()):
            self._appctrl_build_card(name, info)
            # Read current block state
            self._appctrl_read_state_async(name)

        n = len(procs)
        self._appctrl_status_lbl.config(
            text=f"✅ {n} aplicación{'es' if n != 1 else ''} detectada{'s' if n != 1 else ''} usando la red.",
            fg=COLORS["success"],
        )

    def _appctrl_build_card(self, name: str, info: dict):
        """Build a card for one process."""
        card = tk.Frame(self._appctrl_inner, bg=COLORS["surface"], pady=10, padx=14)
        card.pack(fill="x", padx=16, pady=3)
        self._appctrl_cards[name] = card

        dot = tk.Label(card, text="●", font=("Segoe UI", 14),
                       bg=COLORS["surface"], fg=COLORS["text_muted"])
        dot.pack(side="left", padx=(0, 10))
        self._appctrl_dot[name] = dot

        mid = tk.Frame(card, bg=COLORS["surface"])
        mid.pack(side="left", fill="both", expand=True)

        ports_str = ", ".join(str(p) for p in sorted(info["ports"])[:12])
        if len(info["ports"]) > 12:
            ports_str += f" (+{len(info['ports'])-12} más)"
        protos_str = "/".join(sorted(info["protos"]))
        pids_str   = ", ".join(str(p) for p in sorted(info["pids"])[:5])

        tk.Label(mid, text=name, font=FONTS["body"],
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w").pack(anchor="w")
        tk.Label(mid,
                 text=f"Protocolo: {protos_str}  ·  Puertos: {ports_str}  ·  PID: {pids_str}",
                 font=FONTS["small"], bg=COLORS["surface"], fg=COLORS["text_muted"],
                 anchor="w").pack(anchor="w")
        self._appctrl_blocked.setdefault(name, False)

        btn = tk.Button(
            card, text="BLOQUEAR",
            width=10,
            command=lambda n=name: self._appctrl_toggle(n),
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["button"], relief="flat", cursor="hand2",
            pady=6, activebackground=COLORS["btn_hover"],
        )
        btn.pack(side="right", padx=(10, 0))
        self._appctrl_btns[name] = btn

    def _appctrl_rule_name(self, proc_name: str) -> str:
        safe = proc_name.replace(" ", "_").replace(".", "_")[:40]
        return f"WinClean_AppBlock_{safe}"

    def _appctrl_read_state_async(self, name: str):
        def do():
            import subprocess
            rule = self._appctrl_rule_name(name)
            try:
                result = subprocess.run(
                    ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule}"],
                    capture_output=True, text=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                active = "No rules match" not in result.stdout and rule in result.stdout
            except Exception:
                active = False
            self.after(0, lambda: self._appctrl_update_card_ui(name, active))
        threading.Thread(target=do, daemon=True).start()

    def _appctrl_update_card_ui(self, name: str, blocked: bool):
        self._appctrl_blocked[name] = blocked
        btn = self._appctrl_btns.get(name)
        dot = self._appctrl_dot.get(name)
        if blocked:
            if btn: btn.config(text="BLOQUEADA", bg="#2a0a0a", fg="#ff6666",
                               activebackground="#3a1010")
            if dot: dot.config(fg="#ff4444")
        else:
            if btn: btn.config(text="BLOQUEAR", bg=COLORS["btn"], fg=COLORS["text_muted"],
                               activebackground=COLORS["btn_hover"])
            if dot: dot.config(fg=COLORS["text_muted"])

    def _appctrl_toggle(self, name: str):
        import subprocess
        blocked = self._appctrl_blocked.get(name, False)
        rule    = self._appctrl_rule_name(name)
        btn     = self._appctrl_btns.get(name)
        if btn: btn.config(state="disabled")

        def do():
            cf = getattr(subprocess, 'CREATE_NO_WINDOW', 0)
            try:
                if not blocked:
                    # Block outbound traffic for this exe name
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "add", "rule",
                        f"name={rule}", "dir=out", "action=block",
                        "protocol=any", f"program=%SystemRoot%\\*",
                    ], capture_output=True, creationflags=cf)
                    # More reliable: block by program name via PowerShell
                    subprocess.run([
                        "powershell", "-WindowStyle", "Hidden", "-Command",
                        f"New-NetFirewallRule -DisplayName '{rule}' -Direction Outbound "
                        f"-Action Block -Program (Get-Process | Where-Object {{$_.Name -eq '{name.replace('.exe','')}' }} | "
                        f"Select-Object -First 1 -ExpandProperty Path) -ErrorAction SilentlyContinue"
                    ], capture_output=True, creationflags=cf, timeout=15)
                    new_state = True
                else:
                    subprocess.run([
                        "netsh", "advfirewall", "firewall", "delete", "rule",
                        f"name={rule}",
                    ], capture_output=True, creationflags=cf)
                    subprocess.run([
                        "powershell", "-WindowStyle", "Hidden", "-Command",
                        f"Remove-NetFirewallRule -DisplayName '{rule}' -ErrorAction SilentlyContinue"
                    ], capture_output=True, creationflags=cf, timeout=10)
                    new_state = False
            except Exception:
                new_state = blocked  # revert

            def finish():
                if btn: btn.config(state="normal")
                self._appctrl_update_card_ui(name, new_state)
                verb = "bloqueada 🔴" if new_state else "desbloqueada 🟢"
                self.status_text.set(f"Aplicación {name} {verb}")
            self.after(0, finish)

        threading.Thread(target=do, daemon=True).start()

    def _appctrl_block_all(self):
        names = [n for n, blocked in self._appctrl_blocked.items() if not blocked]
        if not names:
            messagebox.showinfo("Sin cambios", "Todas las aplicaciones detectadas ya están bloqueadas.")
            return
        if not messagebox.askyesno("Bloquear todas",
                f"¿Bloquear el tráfico saliente de {len(names)} aplicación(es) activa(s)?"):
            return
        for name in names:
            self._appctrl_toggle(name)

    def _appctrl_unblock_all(self):
        names = [n for n, blocked in self._appctrl_blocked.items() if blocked]
        if not names:
            messagebox.showinfo("Sin cambios", "Ninguna aplicación está bloqueada actualmente.")
            return
        if not messagebox.askyesno("Restaurar todas",
                f"¿Restaurar el acceso a red de {len(names)} aplicación(es) bloqueada(s)?"):
            return
        for name in names:
            self._appctrl_toggle(name)

    def _build_lock_card(self, parent, item: dict):
        """Build a single lock card with ON/OFF toggle."""
        card = tk.Frame(parent, bg=COLORS["surface"], pady=10, padx=14)
        card.pack(fill="x", padx=16, pady=3)

        # Left: indicator dot
        dot = tk.Label(card, text="●", font=("Segoe UI", 14),
                       bg=COLORS["surface"], fg=COLORS["text_muted"])
        dot.pack(side="left", padx=(0, 10))
        self._lock_ind[item["id"]] = dot

        # Middle: name + description + status
        mid = tk.Frame(card, bg=COLORS["surface"])
        mid.pack(side="left", fill="both", expand=True)

        tk.Label(mid, text=item["name"], font=FONTS["body"],
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w").pack(anchor="w")
        tk.Label(mid, text=item["desc"], font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"],
                 wraplength=600, justify="left", anchor="w").pack(anchor="w")
        status_lbl = tk.Label(mid, text="Leyendo estado...", font=FONTS["small"],
                               bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w")
        status_lbl.pack(anchor="w", pady=(2, 0))
        self._lock_status[item["id"]] = status_lbl

        # Right: ON/OFF button
        btn = tk.Button(
            card,
            text="OFF",
            width=6,
            command=lambda i=item: self._toggle_lock(i),
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["button"], relief="flat", cursor="hand2",
            pady=6, activebackground=COLORS["btn_hover"],
        )
        btn.pack(side="right", padx=(10, 0))
        self._lock_btns[item["id"]] = btn

    def _update_lock_card_ui(self, lock_id: str, active: bool):
        """Refresh the card visual state for a lock."""
        self._lock_states[lock_id] = active
        btn = self._lock_btns.get(lock_id)
        dot = self._lock_ind.get(lock_id)
        lbl = self._lock_status.get(lock_id)
        if active:
            if btn: btn.config(text="ON",  bg="#2a5c2a", fg="#55dd55",
                               activebackground="#336633")
            if dot: dot.config(fg="#55dd55")  # green
            if lbl: lbl.config(text="🔒 Restricción ACTIVA — acceso bloqueado", fg="#55dd55")
        else:
            if btn: btn.config(text="OFF", bg=COLORS["btn"], fg=COLORS["text_muted"],
                               activebackground=COLORS["btn_hover"])
            if dot: dot.config(fg=COLORS["text_muted"])
            if lbl: lbl.config(text="🔓 Sin restricción — comportamiento original de Windows",
                               fg=COLORS["text_muted"])

    # ── Network detection ──────────────────────────────────────────

    def _locks_detect_network(self):
        """Async: detect LAN + open ports and update banner."""
        def do():
            result = self._do_detect_network()
            self.after(0, lambda: self._apply_network_banner(result))
        threading.Thread(target=do, daemon=True).start()

    def _do_detect_network(self) -> dict:
        """Return dict with: has_lan, lan_ip, rdp_open, risk_level."""
        import subprocess, socket, re
        has_lan = False
        lan_ip  = None
        rdp_open = False

        # Detect private IP via ipconfig
        try:
            out = subprocess.check_output("ipconfig", capture_output=False,
                                          text=True, timeout=6,
                                          creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0)
            for line in out.splitlines():
                m = re.search(r"IPv4.*?:\s*([\d.]+)", line)
                if m:
                    ip = m.group(1)
                    if (ip.startswith("192.168.") or ip.startswith("10.") or
                            re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip)):
                        has_lan = True
                        lan_ip  = ip
                        break
        except Exception:
            pass

        # Try socket if ipconfig failed
        if not has_lan:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip = s.getsockname()[0]
                s.close()
                if (ip.startswith("192.168.") or ip.startswith("10.") or
                        re.match(r"172\.(1[6-9]|2\d|3[01])\.", ip)):
                    has_lan = True
                    lan_ip  = ip
            except Exception:
                pass

        # Check if RDP port is listening locally
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                rdp_open = (s.connect_ex(("127.0.0.1", 3389)) == 0)
        except Exception:
            pass

        if not has_lan:
            risk = "none"
        elif rdp_open:
            risk = "high"
        else:
            risk = "medium"

        return {"has_lan": has_lan, "lan_ip": lan_ip, "rdp_open": rdp_open, "risk": risk}

    def _apply_network_banner(self, result: dict):
        """Update the LAN alert banner with colored text."""
        risk = result["risk"]
        ip   = result.get("lan_ip", "")
        rdp  = result.get("rdp_open", False)

        if risk == "none":
            color = COLORS["success"]   # green
            icon  = "🟢"
            msg   = "🟢  Sin red LAN detectada — riesgo de acceso remoto BAJO. El equipo no parece estar conectado a una red local."
        elif risk == "medium":
            color = COLORS["warning"]   # yellow/orange
            icon  = "🟡"
            msg   = f"🟡  Red LAN detectada (IP: {ip}) — riesgo MEDIO. El equipo está en una red local. Activa los bloqueos que necesites."
        else:
            color = COLORS["danger"]    # red
            icon  = "🔴"
            msg   = (f"🔴  ALERTA: Red LAN detectada (IP: {ip}) y el puerto RDP 3389 está ABIERTO — riesgo ALTO. "
                     f"Este equipo puede ser controlado remotamente. Se recomienda activar el bloqueo RDP inmediatamente.")

        self._lan_alert_lbl.config(text=msg, fg=color)

    # ── Read current lock states ────────────────────────────────────

    def _locks_read_all_states(self):
        """Read actual system state for all locks asynchronously."""
        def do():
            for item in self._LOCK_ITEMS:
                active = self._read_lock_state(item)
                lid = item["id"]
                self.after(0, lambda i=lid, a=active: self._update_lock_card_ui(i, a))
        threading.Thread(target=do, daemon=True).start()

    def _read_lock_state(self, item: dict) -> bool:
        """Return True if the restriction for this lock is currently active."""
        import subprocess
        lid = item["id"]

        try:
            if lid == "lock_rdp":
                result = subprocess.run(
                    ["reg", "query",
                     r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server",
                     "/v", "fDenyTSConnections"],
                    capture_output=True, text=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                return "0x1" in result.stdout

            elif lid == "lock_remote_assist":
                result = subprocess.run(
                    ["reg", "query",
                     r"HKLM\SYSTEM\CurrentControlSet\Control\Remote Assistance",
                     "/v", "fAllowToGetHelp"],
                    capture_output=True, text=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                return "0x0" in result.stdout

            elif lid == "lock_winrm":
                result = subprocess.run(
                    ["sc", "query", "WinRM"],
                    capture_output=True, text=True,
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                )
                return "STOPPED" in result.stdout or "DISABLED" in result.stdout

            elif lid in ("lock_vnc_port", "lock_net_share", "lock_screen_capture",
                         "lock_spice", "lock_nx", "lock_teamviewer", "lock_anydesk",
                         "lock_rdp_udp", "lock_winrm_https", "lock_netbios", "lock_faronics"):
                rule = item.get("fw_rule", "")
                if rule:
                    result = subprocess.run(
                        ["netsh", "advfirewall", "firewall", "show", "rule", f"name={rule}"],
                        capture_output=True, text=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    )
                    return "No rules match" not in result.stdout and rule in result.stdout

                if lid == "lock_net_share":
                    result = subprocess.run(
                        ["sc", "query", "LanmanServer"],
                        capture_output=True, text=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    )
                    return "STOPPED" in result.stdout or "DISABLED" in result.stdout

                if lid == "lock_screen_capture":
                    result = subprocess.run(
                        ["reg", "query",
                         r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services",
                         "/v", "fDisableScreenCapture"],
                        capture_output=True, text=True,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0),
                    )
                    return "0x1" in result.stdout

        except Exception:
            pass
        return False

    # ── Toggle a lock ───────────────────────────────────────────────

    def _toggle_lock(self, item: dict):
        """Toggle a lock ON (apply restriction) or OFF (remove restriction)."""
        lid     = item["id"]
        current = self._lock_states.get(lid, False)
        new_state = not current

        verb = "Activando" if new_state else "Desactivando"
        self.status_text.set(f"{verb} bloqueo: {item['name']}...")

        # Disable button while working
        btn = self._lock_btns.get(lid)
        if btn:
            btn.config(state="disabled")

        def do():
            if new_state:
                ok, msg = self._apply_lock(item)
            else:
                ok, msg = self._remove_lock(item)

            def finish():
                if btn:
                    btn.config(state="normal")
                if ok:
                    self._update_lock_card_ui(lid, new_state)
                    state_str = "activado 🔒" if new_state else "desactivado 🔓"
                    self.status_text.set(f"✅ Bloqueo {item['name']} {state_str}")
                else:
                    self._update_lock_card_ui(lid, current)  # revert visual
                    self.status_text.set(f"❌ Error: {msg[:80]}")
                    messagebox.showerror("Error de bloqueo",
                                         f"No se pudo {'activar' if new_state else 'desactivar'} "
                                         f"'{item['name']}':\n\n{msg}\n\n"
                                         "Comprueba que WinClean se ejecuta como Administrador.")
            self.after(0, finish)

        threading.Thread(target=do, daemon=True).start()

    def _apply_lock(self, item: dict) -> tuple:
        """Apply (enable) the restriction for a lock item. Returns (ok, msg)."""
        import subprocess
        lid = item["id"]
        cf  = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

        try:
            if lid == "lock_rdp":
                subprocess.run(["reg", "add",
                    r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server",
                    "/v", "fDenyTSConnections", "/t", "REG_DWORD", "/d", "1", "/f"],
                    check=True, capture_output=True, creationflags=cf)
                subprocess.run(["sc", "stop", "TermService"], capture_output=True, creationflags=cf)
                subprocess.run(["sc", "config", "TermService", "start=", "disabled"],
                               capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_RDP", "protocol=TCP", "dir=in",
                    "localport=3389", "action=block"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_remote_assist":
                subprocess.run(["reg", "add",
                    r"HKLM\SYSTEM\CurrentControlSet\Control\Remote Assistance",
                    "/v", "fAllowToGetHelp", "/t", "REG_DWORD", "/d", "0", "/f"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_winrm":
                subprocess.run(["sc", "stop", "WinRM"], capture_output=True, creationflags=cf)
                subprocess.run(["sc", "config", "WinRM", "start=", "disabled"],
                               capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_WinRM", "protocol=TCP", "dir=in",
                    "localport=5985", "action=block"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_vnc_port":
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_VNC", "protocol=TCP", "dir=in",
                    "localport=5900", "action=block"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_net_share":
                subprocess.run(["sc", "stop", "LanmanServer"], capture_output=True, creationflags=cf)
                subprocess.run(["sc", "config", "LanmanServer", "start=", "disabled"],
                               capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_SMB", "protocol=TCP", "dir=in",
                    "localport=445", "action=block"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_screen_capture":
                subprocess.run(["reg", "add",
                    r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services",
                    "/v", "fDisableScreenCapture", "/t", "REG_DWORD", "/d", "1", "/f"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_spice":
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_SPICE", "protocol=TCP", "dir=in",
                    "localport=5910", "action=block"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_nx":
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_NX", "protocol=TCP", "dir=in",
                    "localport=4000", "action=block"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_teamviewer":
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_TeamViewer", "protocol=TCP", "dir=in",
                    "localport=5938", "action=block"],
                    capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_TeamViewer_UDP", "protocol=UDP", "dir=in",
                    "localport=5938", "action=block"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_anydesk":
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_AnyDesk", "protocol=TCP", "dir=in",
                    "localport=7070", "action=block"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_rdp_udp":
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_RDP_UDP", "protocol=UDP", "dir=in",
                    "localport=3389", "action=block"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_winrm_https":
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_WinRM_HTTPS", "protocol=TCP", "dir=in",
                    "localport=5986", "action=block"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_netbios":
                for port in ["137", "138", "139"]:
                    for proto in ["TCP", "UDP"]:
                        subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                            f"name=WinClean_Block_NetBIOS", f"protocol={proto}", "dir=in",
                            f"localport={port}", "action=block"],
                            capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_faronics":
                # Block all Faronics Insight ports: 796, 11796 (TCP+UDP), 1053 UDP, 8080, 8085, 8888, 8889, 8890 TCP
                for proto in ["TCP", "UDP"]:
                    for port in ["796", "11796"]:
                        subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                            f"name=WinClean_Block_Faronics", f"protocol={proto}", "dir=in",
                            f"localport={port}", "action=block"],
                            capture_output=True, creationflags=cf)
                        subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                            f"name=WinClean_Block_Faronics", f"protocol={proto}", "dir=out",
                            f"localport={port}", "action=block"],
                            capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_Faronics", "protocol=UDP", "dir=in",
                    "localport=1053", "action=block"],
                    capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                    "name=WinClean_Block_Faronics", "protocol=UDP", "dir=out",
                    "localport=1053", "action=block"],
                    capture_output=True, creationflags=cf)
                for port in ["8080", "8085", "8888", "8889", "8890"]:
                    subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                        "name=WinClean_Block_Faronics", "protocol=TCP", "dir=in",
                        f"localport={port}", "action=block"],
                        capture_output=True, creationflags=cf)
                    subprocess.run(["netsh", "advfirewall", "firewall", "add", "rule",
                        "name=WinClean_Block_Faronics", "protocol=TCP", "dir=out",
                        f"remoteport={port}", "action=block"],
                        capture_output=True, creationflags=cf)
                return True, ""

        except subprocess.CalledProcessError as e:
            return False, e.stderr.decode(errors="replace") if e.stderr else str(e)
        except Exception as e:
            return False, str(e)

        return False, "Acción desconocida"

    def _remove_lock(self, item: dict) -> tuple:
        """Remove (disable) the restriction for a lock item. Returns (ok, msg)."""
        import subprocess
        lid = item["id"]
        cf  = getattr(subprocess, 'CREATE_NO_WINDOW', 0)

        try:
            if lid == "lock_rdp":
                subprocess.run(["reg", "add",
                    r"HKLM\SYSTEM\CurrentControlSet\Control\Terminal Server",
                    "/v", "fDenyTSConnections", "/t", "REG_DWORD", "/d", "0", "/f"],
                    check=True, capture_output=True, creationflags=cf)
                subprocess.run(["sc", "config", "TermService", "start=", "auto"],
                               capture_output=True, creationflags=cf)
                subprocess.run(["sc", "start", "TermService"], capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_RDP"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_remote_assist":
                subprocess.run(["reg", "add",
                    r"HKLM\SYSTEM\CurrentControlSet\Control\Remote Assistance",
                    "/v", "fAllowToGetHelp", "/t", "REG_DWORD", "/d", "1", "/f"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_winrm":
                subprocess.run(["sc", "config", "WinRM", "start=", "manual"],
                               capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_WinRM"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_vnc_port":
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_VNC"],
                    check=True, capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_net_share":
                subprocess.run(["sc", "config", "LanmanServer", "start=", "auto"],
                               capture_output=True, creationflags=cf)
                subprocess.run(["sc", "start", "LanmanServer"], capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_SMB"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_screen_capture":
                subprocess.run(["reg", "delete",
                    r"HKLM\SOFTWARE\Policies\Microsoft\Windows NT\Terminal Services",
                    "/v", "fDisableScreenCapture", "/f"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid in ("lock_spice", "lock_nx", "lock_anydesk", "lock_rdp_udp",
                         "lock_winrm_https"):
                rule = item.get("fw_rule", "")
                if rule:
                    subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                        f"name={rule}"],
                        capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_teamviewer":
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_TeamViewer"],
                    capture_output=True, creationflags=cf)
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_TeamViewer_UDP"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_netbios":
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_NetBIOS"],
                    capture_output=True, creationflags=cf)
                return True, ""

            elif lid == "lock_faronics":
                subprocess.run(["netsh", "advfirewall", "firewall", "delete", "rule",
                    "name=WinClean_Block_Faronics"],
                    capture_output=True, creationflags=cf)
                return True, ""

        except subprocess.CalledProcessError as e:
            return False, e.stderr.decode(errors="replace") if e.stderr else str(e)
        except Exception as e:
            return False, str(e)

        return False, "Acción desconocida"

    # ── W11 helpers ───────────────────────────────────────────────────

    def _w11_section_header(self, parent, title: str, subtitle: str) -> tk.Frame:
        """A visually distinct header for W11-only sections."""
        f = tk.Frame(parent, bg=COLORS["bg"])
        tk.Frame(f, bg=W11_BADGE_COLOR, width=3).pack(side="left", fill="y", padx=(0, 10), pady=2)
        right = tk.Frame(f, bg=COLORS["bg"])
        right.pack(side="left", fill="both", expand=True)
        head = tk.Frame(right, bg=COLORS["bg"])
        head.pack(anchor="w")
        tk.Label(head, text=title.upper(), font=FONTS["label"],
                 bg=COLORS["bg"], fg=W11_BADGE_COLOR, anchor="w").pack(side="left")
        tk.Label(head, text=f"  [{W11_BADGE_TEXT}]",
                 font=("Segoe UI", 7, "bold"),
                 bg=W11_BADGE_COLOR, fg="#ffffff",
                 padx=4, pady=1).pack(side="left", padx=(6, 0))
        if subtitle:
            tk.Label(right, text=subtitle, font=FONTS["small"],
                     bg=COLORS["bg"], fg=COLORS["text_muted"],
                     anchor="w", wraplength=720, justify="left").pack(anchor="w")
        return f

    # ── Profiles ──────────────────────────────────────────────────────

    def _refresh_profile_list(self):
        for w in self.profile_list_frame.winfo_children():
            w.destroy()
        for p in list_profiles():
            selected = p["id"] == self.current_profile.get()
            tk.Button(
                self.profile_list_frame,
                text=p["name"],
                command=lambda pid=p["id"]: self._load_profile(pid),
                bg=COLORS["accent"] if selected else COLORS["btn"],
                fg="#000" if selected else COLORS["text"],
                font=FONTS["small"], relief="flat", cursor="hand2",
                pady=7, padx=8, anchor="w",
                activebackground=COLORS["accent"], activeforeground="#000",
            ).pack(fill="x", pady=1)

    def _refresh_startup_profile_combo(self):
        profiles = list_profiles()
        values = [p["name"] for p in profiles]
        ids = [p["id"] for p in profiles]
        self.startup_profile_combo["values"] = values
        self._startup_profile_ids = ids

    def _on_startup_profile_change(self, event=None):
        idx = self.startup_profile_combo.current()
        if 0 <= idx < len(self._startup_profile_ids):
            pid = self._startup_profile_ids[idx]
            save_startup_profile(pid)
            self.status_text.set(f"Perfil de inicio guardado: {self.startup_profile_var.get()}")

    def _load_profile(self, profile_id: str):
        profile = load_profile(profile_id)
        if not profile:
            return
        for var in self.check_vars.values():
            var.set(False)
        for item_id in profile.get("apps", []) + profile.get("services", []) + profile.get("tweaks", []):
            if item_id in self.check_vars:
                self.check_vars[item_id].set(True)
        self.current_profile.set(profile_id)
        self._refresh_profile_list()
        self.status_text.set(f"Perfil cargado: {profile.get('name', profile_id)}")

    def _save_profile_dialog(self):
        dialog = tk.Toplevel(self)
        dialog.title("Guardar Perfil")
        dialog.geometry("420x280")
        dialog.configure(bg=COLORS["bg"])
        dialog.transient(self)
        dialog.grab_set()

        for label, attr in [("Nombre del perfil:", "name_e"), ("Descripcion:", "desc_e")]:
            tk.Label(dialog, text=label, bg=COLORS["bg"], fg=COLORS["text"], font=FONTS["body"]).pack(
                anchor="w", padx=20, pady=(16 if "Nombre" in label else 12, 4))
            e = tk.Entry(dialog, bg=COLORS["surface"], fg=COLORS["text"], font=FONTS["body"],
                         relief="flat", bd=0, insertbackground=COLORS["accent"])
            e.pack(fill="x", padx=20, ipady=8)
            setattr(dialog, attr, e)

        def do_save():
            name = dialog.name_e.get().strip()
            if not name:
                messagebox.showerror("Error", "El nombre no puede estar vacío", parent=dialog)
                return
            apps = [a["id"] for a in BLOATWARE_APPS if self.check_vars[a["id"]].get()]
            services = [s["id"] for s in SERVICES if self.check_vars[s["id"]].get()]
            tweaks = [t["id"] for t in TWEAKS if self.check_vars[t["id"]].get()]
            save_profile(name, dialog.desc_e.get().strip(), apps, services, tweaks)
            dialog.destroy()
            self._refresh_profile_list()
            self._refresh_startup_profile_combo()
            self.status_text.set(f"Perfil '{name}' guardado")

        tk.Button(dialog, text="Guardar", command=do_save,
                  bg=COLORS["accent"], fg="#000", font=FONTS["button"],
                  relief="flat", pady=10, cursor="hand2").pack(fill="x", padx=20, pady=20)

    def _import_profile(self):
        path = filedialog.askopenfilename(title="Importar perfil",
                                          filetypes=[("JSON", "*.json"), ("Todos", "*.*")])
        if path:
            try:
                name = import_profile(path)
                self._refresh_profile_list()
                self._refresh_startup_profile_combo()
                self.status_text.set(f"Perfil '{name}' importado")
            except Exception as e:
                messagebox.showerror("Error al importar", str(e))

    def _export_profile(self):
        pid = self.current_profile.get()
        if not pid:
            messagebox.showwarning("Sin perfil", "Selecciona un perfil para exportar")
            return
        path = filedialog.asksaveasfilename(title="Exportar perfil",
                                             defaultextension=".json",
                                             filetypes=[("JSON", "*.json")])
        if path:
            export_profile(pid, path)
            self.status_text.set(f"Exportado: {os.path.basename(path)}")

    def _delete_profile(self):
        pid = self.current_profile.get()
        if not pid:
            messagebox.showwarning("Sin perfil", "Selecciona un perfil para eliminar")
            return
        if any(p["id"] == pid and p.get("preset") for p in list_profiles()):
            messagebox.showwarning("Predefinido", "Los perfiles predefinidos no se pueden eliminar")
            return
        if messagebox.askyesno("Confirmar", f"Eliminar el perfil '{pid}'?"):
            delete_profile(pid)
            self.current_profile.set("")
            self._refresh_profile_list()
            self._refresh_startup_profile_combo()
            self.status_text.set("Perfil eliminado")

    # ── Quick actions ──────────────────────────────────────────────────

    def _select_all(self):
        for var in self.check_vars.values():
            var.set(True)

    def _deselect_all(self):
        for var in self.check_vars.values():
            var.set(False)

    def _revert_all(self):
        if not messagebox.askyesno("Revertir todo",
                                   "Revertir TODOS los cambios aplicados por WinClean?\n"
                                   "Se restaurarán servicios y tweaks a sus valores originales.\n"
                                   "(Las apps desinstaladas no se pueden restaurar automáticamente)"):
            return
        self._run_in_thread(self._do_revert_all, "Revirtiendo cambios...")

    def _do_revert_all(self):
        errors = []
        for svc in SERVICES + AI_SERVICES:
            ok, msg = enable_service(svc["service"])
            if not ok:
                errors.append(f"{svc['name']}: {msg}")
        for tweak in TWEAKS:
            ok, msg = revert_tweak(tweak["id"])
            if not ok:
                errors.append(f"{tweak['name']}: {msg}")
        if errors:
            self.after(0, lambda: messagebox.showwarning("Errores al revertir", "\n".join(errors[:10])))
        self.after(0, lambda: self.status_text.set("Revertido. Reinicia para que todos los cambios surtan efecto."))
        self.after(100, self._start_scan)

    # ── Apply ──────────────────────────────────────────────────────────

    def _apply_selected(self):
        sel_apps   = [a for a in BLOATWARE_APPS if self.check_vars[a["id"]].get() and a["id"] in self.app_card_frames]
        sel_svcs   = [s for s in SERVICES + AI_SERVICES if self.check_vars[s["id"]].get()
                      and self.svc_status_cache.get(s["service"]) not in (SVC_NOT_FOUND,)]
        sel_tweaks = [t for t in TWEAKS if self.check_vars[t["id"]].get()]

        total = len(sel_apps) + len(sel_svcs) + len(sel_tweaks)
        if total == 0:
            messagebox.showinfo("Nada seleccionado", "Selecciona al menos un elemento")
            return

        lines = [f"Se van a aplicar {total} cambio(s):\n"]
        if sel_apps:   lines.append(f"- {len(sel_apps)} app(s) a DESINSTALAR (permanente)")
        if sel_svcs:   lines.append(f"- {len(sel_svcs)} servicio(s) a desactivar")
        if sel_tweaks: lines.append(f"- {len(sel_tweaks)} tweak(s) de sistema")
        lines.append("\nContinuar?")

        if not messagebox.askyesno("Confirmar", "\n".join(lines)):
            return

        self.apply_btn.config(state="disabled", text="Aplicando...")
        self._run_in_thread(
            lambda: self._do_apply(sel_apps, sel_svcs, sel_tweaks),
            "Aplicando cambios..."
        )

    def _do_apply(self, apps, services, tweaks):
        errors = []
        total = len(apps) + len(services) + len(tweaks)

        for app in apps:
            self.after(0, lambda n=app["name"]: self.status_text.set(f"Desinstalando {n}..."))
            ok, msg = uninstall_app(app["package"])
            if not ok:
                errors.append(f"[App] {app['name']}: {msg[:80]}")
            else:
                self.installed_apps.discard(app["package"].lower())

        for svc in services:
            self.after(0, lambda n=svc["name"]: self.status_text.set(f"Desactivando {n}..."))
            ok, msg = disable_service(svc["service"])
            if not ok:
                errors.append(f"[Servicio] {svc['name']}: {msg[:80]}")
            else:
                self.svc_status_cache[svc["service"]] = SVC_DISABLED

        for tweak in tweaks:
            self.after(0, lambda n=tweak["name"]: self.status_text.set(f"Aplicando {n}..."))
            ok, msg = apply_tweak(tweak["id"])
            if not ok:
                errors.append(f"[Tweak] {tweak['name']}: {msg[:80]}")

        def finish():
            self.apply_btn.config(state="normal", text="APLICAR CONFIGURACION SELECCIONADA")
            if errors:
                messagebox.showwarning("Aplicado con advertencias",
                                       f"Completado con {len(errors)} error(s):\n\n" + "\n".join(errors[:8]))
                self.status_text.set(f"Aplicado con {len(errors)} advertencia(s)")
            else:
                messagebox.showinfo("Listo",
                                    f"Se han aplicado {total} cambios correctamente.\n\n"
                                    "Algunos cambios requieren reiniciar el PC.")
                self.status_text.set(f"{total} cambios aplicados correctamente")
            self._refresh_app_cards()
            self._refresh_service_cards()

        self.after(0, finish)

    # ── Cleaner window ─────────────────────────────────────────────────

    def _open_cleaner(self):
        win = CleanerWindow(self)
        win.focus_force()

    # ── Startup toggle ─────────────────────────────────────────────────

    def _toggle_startup(self):
        enabled = self.startup_var.get()
        self.status_text.set("Configurando inicio automático...")
        self.apply_btn.config(state="disabled")

        def do_toggle():
            ok, msg = set_startup(enabled)
            def after():
                self.apply_btn.config(state="normal")
                if ok:
                    state = "activado" if enabled else "desactivado"
                    self.status_text.set(f"Inicio automático {state}")
                else:
                    messagebox.showerror("Error al configurar inicio",
                                         f"No se pudo {'activar' if enabled else 'desactivar'} el inicio automático.\n\n{msg}")
                    self.startup_var.set(not enabled)
                    self.status_text.set("Error al configurar inicio automático")
            self.after(0, after)

        threading.Thread(target=do_toggle, daemon=True).start()

    # ── Thread helper ──────────────────────────────────────────────────

    def _run_in_thread(self, fn, status_msg="Trabajando..."):
        self.status_text.set(status_msg)
        threading.Thread(target=fn, daemon=True).start()
