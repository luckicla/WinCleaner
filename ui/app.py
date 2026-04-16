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
        self.title(f"WinClean - Optimizador {title_os}")
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
        for item in BLOATWARE_APPS + SERVICES + TWEAKS:
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

        n_apps = sum(1 for a in BLOATWARE_APPS if is_app_installed(a["package"], self.installed_apps))
        n_svcs = sum(1 for s in SERVICES if self.svc_status_cache.get(s["service"]) != SVC_NOT_FOUND)
        self.status_text.set(f"Escaneado: {n_apps} apps encontradas, {n_svcs} servicios detectados")

    # ── UI Construction ───────────────────────────────────────────────

    def _build_ui(self):
        topbar = tk.Frame(self, bg=COLORS["surface"], height=56)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="WinClean", font=FONTS["title"],
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

        self.apps_tab_frame = tk.Frame(nb, bg=COLORS["bg"])
        self.svcs_tab_frame = tk.Frame(nb, bg=COLORS["bg"])
        tweaks_tab          = tk.Frame(nb, bg=COLORS["bg"])
        self.res_tab_frame  = tk.Frame(nb, bg=COLORS["bg"])

        nb.add(self.apps_tab_frame, text="Apps & Bloatware")
        nb.add(self.svcs_tab_frame, text="Servicios")
        nb.add(tweaks_tab,          text="Tweaks & Privacidad")
        nb.add(self.res_tab_frame,  text="⚡ Recursos")

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
                      "Verde=En ejecucion  Amarillo=Detenido  Gris=Desactivado  Morado=Bloqueado").pack(
            fill="x", padx=16, pady=(16, 4))
        self.svc_card_frames = {}

        self._build_tweaks_tab_content(tweaks_tab)
        self._build_resources_tab(self.res_tab_frame)

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
                var=var, risk=app["risk"], risk_color=risk_colors[app["risk"]]
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
                        var=var, risk=app["risk"], risk_color=risk_colors[app["risk"]]
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
                    )
                    card.pack(fill="x", padx=16, pady=2)
                    self.svc_card_frames[svc["id"]] = card

        if found == 0:
            lbl = tk.Label(self.svcs_inner,
                           text="No se encontraron servicios reconocidos.",
                           font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["text_muted"])
            lbl.pack(padx=16, pady=20)
            self.svc_card_frames["_empty"] = lbl

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
        threading.Thread(target=do, daemon=True).start()

    def _on_tweak_disable(self, tweak_id: str):
        self.status_text.set(f"Revirtiendo: {tweak_id}...")
        def do():
            ok, msg = revert_tweak(tweak_id)
            name = next((t["name"] for t in TWEAKS if t["id"] == tweak_id), tweak_id)
            self.after(0, lambda: self.status_text.set(
                f"✅ {name} — restaurado a original" if ok else f"Error: {msg[:60]}"
            ))
        threading.Thread(target=do, daemon=True).start()

    # ── AI tab (W11 only) ──────────────────────────────────────────────

    def _build_ai_tab(self, parent):
        _, inner = self._make_scrollable(parent)

        SectionHeader(
            inner,
            "🤖  Características de IA de Windows 11",
            "Estas son las funciones de IA de W11 que más recursos consumen y menos utilidad aportan. "
            "OFF = WinClean ha desactivado la característica. ON = activa (estado original de Microsoft)."
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
        SectionHeader(inner, "Servicios de IA que más consumen", "").pack(fill="x", padx=16, pady=(16, 4))

        ai_svc_info = [
            ("AIXHelper",             "AI Helper Service",          "Proceso de soporte de IA, siempre activo en W11 24H2+"),
            ("cbdhsvc",               "Portapapeles en la nube",    "Sync del portapapeles + sugerencias IA"),
            ("wemsvc",                "Windows Experience Service", "Recopila datos de uso para personalización IA"),
            ("StorSvc",               "Storage Service (Recall)",   "Gestiona las capturas de Recall en disco"),
            ("wisvc",                 "Windows Insider Service",    "Envía telemetría incluso sin ser Insider"),
            ("perceptionsimulation",  "Perception Simulation",      "IA para realidad mixta y cámara inteligente"),
        ]

        for svc_name, label, desc in ai_svc_info:
            status = self.svc_status_cache.get(svc_name, SVC_NOT_FOUND)
            if status == SVC_NOT_FOUND:
                status_text, status_color = "NO ENCONTRADO", COLORS["border"]
            else:
                status_text, status_color = SVC_STATUS_DISPLAY.get(status, ("?", COLORS["border"]))

            row = tk.Frame(inner, bg=COLORS["surface"], pady=0)
            row.pack(fill="x", padx=16, pady=2)
            ri = tk.Frame(row, bg=COLORS["surface"], padx=12, pady=7)
            ri.pack(fill="both", expand=True)

            left = tk.Frame(ri, bg=COLORS["surface"])
            left.pack(side="left", fill="both", expand=True)
            tk.Label(left, text=label, font=FONTS["body"],
                     bg=COLORS["surface"], fg=COLORS["text"], anchor="w").pack(anchor="w")
            tk.Label(left, text=f"{svc_name}  —  {desc}", font=FONTS["small"],
                     bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w").pack(anchor="w")

            tk.Label(ri, text=status_text,
                     font=("Segoe UI", 8, "bold"),
                     bg=COLORS["bg"], fg=status_color,
                     padx=6, pady=3).pack(side="right")

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
        power_bar = tk.Frame(parent, bg=COLORS["bg"], pady=8, padx=16)
        power_bar.pack(fill="x")

        tk.Label(power_bar, text="Perfil de energía:", font=FONTS["small"],
                 bg=COLORS["bg"], fg=COLORS["text_muted"]).pack(side="left", padx=(0, 10))

        self._power_var = tk.StringVar(value="balanced")
        plan_labels = []

        if self.is_laptop:
            plan_labels.append(("saver",    "🔋 Ahorro de batería"))
        plan_labels.append(("balanced", "⚖  Equilibrado"))
        plan_labels.append(("high",     "🚀 Alto rendimiento"))

        self._power_btns = {}
        for plan_id, plan_name in plan_labels:
            btn = tk.Button(
                power_bar, text=plan_name,
                command=lambda pid=plan_id: self._set_power_plan(pid),
                bg=COLORS["btn"], fg=COLORS["text_muted"],
                font=FONTS["small"], relief="flat", cursor="hand2",
                padx=10, pady=4,
                activebackground=COLORS["btn_hover"],
            )
            btn.pack(side="left", padx=4)
            self._power_btns[plan_id] = btn

        if not self.is_laptop:
            tk.Label(power_bar, text="(portátil no detectado — ahorro de batería no disponible)",
                     font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["border"]).pack(side="left", padx=8)

        # Read current plan and highlight
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
            if plan_id == active:
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
        for svc in SERVICES:
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
        sel_svcs   = [s for s in SERVICES if self.check_vars[s["id"]].get()
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
