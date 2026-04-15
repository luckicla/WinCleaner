"""
WinClean - Main Application Window
- Scans real installed apps on load (hides uninstalled ones)
- Shows real service status with color coding
- Service block/unblock for already-disabled services
- Startup via Task Scheduler with profile selector
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
)
from ui.styles import apply_theme, COLORS, FONTS
from ui.widgets import SectionHeader, ItemCard, ServiceCard, StatusBar

SVC_STATUS_DISPLAY = {
    SVC_RUNNING:   ("EN EJECUCION", COLORS["success"]),
    SVC_STOPPED:   ("DETENIDO",     COLORS["warning"]),
    SVC_DISABLED:  ("DESACTIVADO",  COLORS["text_muted"]),
    SVC_BLOCKED:   ("BLOQUEADO",    "#8855cc"),
    SVC_NOT_FOUND: ("NO EXISTE",    COLORS["border"]),
}


class WinCleanApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("WinClean - Optimizador Windows 10")
        self.geometry("1140x740")
        self.minsize(960, 620)
        self.configure(bg=COLORS["bg"])

        # ── State ──────────────────────────────────────────────────────────
        self.check_vars = {}
        self.svc_status_cache = {}
        self.installed_apps = set()
        self.current_profile = tk.StringVar(value="")
        self.status_text = tk.StringVar(value="Escaneando sistema...")
        self.startup_var = tk.BooleanVar(value=False)
        self.startup_profile_var = tk.StringVar(value="")

        # Tray icon reference (created lazily on first minimize-to-tray)
        self._tray_icon = None
        self._tray_thread = None

        self._build_check_vars()
        apply_theme(self)
        self._build_ui()
        self._center_window()

        # Intercept window close button -> minimize to tray
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        # Scan system in background after UI is ready
        self.after(200, self._start_scan)

    # ── Init ──────────────────────────────────────────────────────────────

    def _build_check_vars(self):
        for item in BLOATWARE_APPS + SERVICES + TWEAKS:
            self.check_vars[item["id"]] = tk.BooleanVar(value=False)

    def _center_window(self):
        self.update_idletasks()
        w, h = 1140, 740
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        self.geometry(f"{w}x{h}+{(sw-w)//2}+{(sh-h)//2}")

    # ── Tray / close handling ──────────────────────────────────────────────

    def _on_close(self):
        """
        Instead of destroying the window, minimize it to the system tray.
        First time: creates the tray icon in a background thread.
        """
        self.withdraw()  # hide window immediately

        if self._tray_icon is not None:
            # Already running in tray — just leave it hidden
            return

        # Try to start pystray in background
        self._tray_thread = threading.Thread(target=self._run_tray, daemon=True)
        self._tray_thread.start()

    def _run_tray(self):
        """Create and run a pystray icon (blocking, runs in its own thread)."""
        try:
            import pystray
            from PIL import Image, ImageDraw
        except ImportError:
            # pystray/PIL not installed — show the window again
            self.after(0, self._show_from_tray)
            self.after(0, lambda: messagebox.showwarning(
                "Bandeja no disponible",
                "Para minimizar a la bandeja instala:\n  pip install pystray pillow\n\n"
                "La ventana se mantendra visible."
            ))
            return

        # Build a simple icon
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, size - 2, size - 2], fill=(34, 37, 46, 255))
        draw.ellipse([2, 2, size - 2, size - 2], outline=(77, 166, 255, 255), width=3)
        pts = [(36,6),(20,34),(32,34),(28,58),(44,30),(32,30),(36,6)]
        draw.polygon(pts, fill=(77, 166, 255, 255))

        def on_open(icon, item):
            self.after(0, self._show_from_tray)

        def on_quit(icon, item):
            icon.stop()
            self.after(0, self._quit_app)

        menu = pystray.Menu(
            pystray.MenuItem("Abrir WinClean", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Salir", on_quit),
        )

        self._tray_icon = pystray.Icon(
            "WinClean", img, "WinClean - Optimizador Windows 10", menu
        )
        self._tray_icon.run()  # blocks until icon.stop()

    def _show_from_tray(self):
        """Restore the main window from tray."""
        self.deiconify()
        self.lift()
        self.focus_force()

    def _quit_app(self):
        """Fully exit the application."""
        try:
            self.destroy()
        except Exception:
            pass

    # ── Scan ──────────────────────────────────────────────────────────────

    def _start_scan(self):
        self.status_text.set("Escaneando apps instaladas y servicios...")
        threading.Thread(target=self._do_scan, daemon=True).start()

    def _do_scan(self):
        self.installed_apps = get_all_installed_packages()

        svc_names = [s["service"] for s in SERVICES]
        for name in svc_names:
            self.svc_status_cache[name] = get_service_status(name)

        is_startup = get_startup_status()
        self.after(0, lambda: self._apply_scan_results(is_startup))

    def _apply_scan_results(self, is_startup: bool):
        self.startup_var.set(is_startup)
        self._refresh_app_cards()
        self._refresh_service_cards()

        n_apps = sum(1 for a in BLOATWARE_APPS if is_app_installed(a["package"], self.installed_apps))
        n_svcs = sum(1 for s in SERVICES if self.svc_status_cache.get(s["service"]) != SVC_NOT_FOUND)
        self.status_text.set(f"Escaneado: {n_apps} apps encontradas, {n_svcs} servicios detectados")

    # ── UI Construction ───────────────────────────────────────────────────

    def _build_ui(self):
        topbar = tk.Frame(self, bg=COLORS["surface"], height=56)
        topbar.pack(fill="x", side="top")
        topbar.pack_propagate(False)

        tk.Label(topbar, text="WinClean", font=FONTS["title"],
                 bg=COLORS["surface"], fg=COLORS["accent"]).pack(side="left", padx=20, pady=10)
        tk.Label(topbar, text="Optimizador & Limpiador Windows 10",
                 font=FONTS["subtitle"], bg=COLORS["surface"], fg=COLORS["text_muted"]).pack(side="left", padx=4)

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
            ("Importar", self._import_profile),
            ("Exportar", self._export_profile),
            ("Eliminar", self._delete_profile),
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
            ("Seleccionar todo", self._select_all),
            ("Deseleccionar todo", self._deselect_all),
            ("Revertir cambios", self._revert_all),
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
        tweaks_tab = tk.Frame(nb, bg=COLORS["bg"])

        nb.add(self.apps_tab_frame, text="Apps & Bloatware")
        nb.add(self.svcs_tab_frame, text="Servicios")
        nb.add(tweaks_tab, text="Tweaks & Privacidad")

        # Each tab gets its own scrollable canvas with its own scroll binding
        # (using bind_all was causing all canvases to scroll simultaneously)
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
        """
        Returns (canvas, inner_frame).
        Each canvas binds scroll only to itself (not bind_all),
        so scrolling one tab does not move another tab's canvas.
        """
        canvas = tk.Canvas(parent, bg=COLORS["bg"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLORS["bg"])
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        # Bind scroll to this canvas specifically — avoids the bug where
        # bind_all made ALL canvases scroll when the mouse was anywhere in
        # the window.
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        canvas.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", _on_mousewheel))
        canvas.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))

        return canvas, inner

    # ── App cards ─────────────────────────────────────────────────────────

    def _refresh_app_cards(self):
        for w in self.app_card_frames.values():
            w.destroy()
        self.app_card_frames.clear()

        risk_colors = {"low": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}
        found = 0
        for app in BLOATWARE_APPS:
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

        if found == 0:
            lbl = tk.Label(self.apps_inner,
                           text="No se encontro bloatware conocido instalado en este equipo.",
                           font=FONTS["body"], bg=COLORS["bg"], fg=COLORS["success"])
            lbl.pack(padx=16, pady=20)
            self.app_card_frames["_empty"] = lbl

    # ── Service cards ──────────────────────────────────────────────────────

    def _refresh_service_cards(self):
        for w in self.svc_card_frames.values():
            w.destroy()
        self.svc_card_frames.clear()

        risk_colors = {"low": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}
        found = 0
        for svc in SERVICES:
            status = self.svc_status_cache.get(svc["service"], SVC_NOT_FOUND)
            if status == SVC_NOT_FOUND:
                continue
            found += 1
            var = self.check_vars[svc["id"]]
            card = ServiceCard(
                self.svcs_inner,
                name=svc["name"],
                description=svc["description"],
                var=var,
                risk=svc["risk"],
                risk_color=risk_colors[svc["risk"]],
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
                                   f"Se eliminan los trigger-start para que Windows no pueda activarlo automaticamente."):
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

    def _build_tweaks_tab_content(self, parent):
        _, inner = self._make_scrollable(parent)
        categories = {
            "privacy": "Privacidad y Telemetria",
            "performance": "Rendimiento",
            "gaming": "Gaming",
        }
        risk_colors = {"low": COLORS["success"], "medium": COLORS["warning"], "high": COLORS["danger"]}
        for cat_id, cat_name in categories.items():
            cat_tweaks = [t for t in TWEAKS if t["category"] == cat_id]
            if not cat_tweaks:
                continue
            SectionHeader(inner, cat_name, "").pack(fill="x", padx=16, pady=(16, 4))
            for tweak in cat_tweaks:
                ItemCard(inner, tweak["name"], tweak["description"],
                         var=self.check_vars[tweak["id"]],
                         risk=tweak["risk"], risk_color=risk_colors[tweak["risk"]]).pack(
                    fill="x", padx=16, pady=2)

    # ── Profiles ──────────────────────────────────────────────────────────

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
                messagebox.showerror("Error", "El nombre no puede estar vacio", parent=dialog)
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

    # ── Quick actions ──────────────────────────────────────────────────────

    def _select_all(self):
        for var in self.check_vars.values():
            var.set(True)

    def _deselect_all(self):
        for var in self.check_vars.values():
            var.set(False)

    def _revert_all(self):
        if not messagebox.askyesno("Revertir todo",
                                   "Revertir TODOS los cambios aplicados por WinClean?\n"
                                   "Se restauraran servicios y tweaks a sus valores originales.\n"
                                   "(Las apps desinstaladas no se pueden restaurar automaticamente)"):
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

    # ── Apply ──────────────────────────────────────────────────────────────

    def _apply_selected(self):
        sel_apps   = [a for a in BLOATWARE_APPS if self.check_vars[a["id"]].get() and a["id"] in self.app_card_frames]
        sel_svcs   = [s for s in SERVICES   if self.check_vars[s["id"]].get()
                      and self.svc_status_cache.get(s["service"]) not in (SVC_NOT_FOUND,)]
        sel_tweaks = [t for t in TWEAKS     if self.check_vars[t["id"]].get()]

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

    # ── Startup toggle ─────────────────────────────────────────────────────

    def _toggle_startup(self):
        enabled = self.startup_var.get()
        self.status_text.set("Configurando inicio automatico...")
        self.apply_btn.config(state="disabled")

        def do_toggle():
            ok, msg = set_startup(enabled)
            def after():
                self.apply_btn.config(state="normal")
                if ok:
                    state = "activado" if enabled else "desactivado"
                    self.status_text.set(f"Inicio automatico {state}")
                else:
                    messagebox.showerror("Error al configurar inicio",
                                         f"No se pudo {'activar' if enabled else 'desactivar'} el inicio automatico.\n\n{msg}")
                    self.startup_var.set(not enabled)
                    self.status_text.set("Error al configurar inicio automatico")
            self.after(0, after)

        threading.Thread(target=do_toggle, daemon=True).start()

    # ── Thread helper ──────────────────────────────────────────────────────

    def _run_in_thread(self, fn, status_msg="Trabajando..."):
        self.status_text.set(status_msg)
        threading.Thread(target=fn, daemon=True).start()
