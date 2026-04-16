"""
Custom reusable widgets for WinClean
"""
import tkinter as tk
from ui.styles import COLORS, FONTS

RISK_LABELS = {
    "low":    "SEGURO",
    "medium": "MEDIO",
    "high":   "PRECAUCIÓN",
}

SVC_STATUS_DISPLAY = {
    "running":   ("● EN EJECUCIÓN", COLORS["success"]),
    "stopped":   ("● DETENIDO",     COLORS["warning"]),
    "disabled":  ("● DESACTIVADO",  COLORS["text_muted"]),
    "blocked":   ("● BLOQUEADO",    "#9966cc"),
    "not_found": ("  NO EXISTE",    COLORS["border"]),
}


def _safe_set_bg(widget, color):
    """
    Recursively set background color on a widget tree.
    Guards against destroyed widgets (TclError: bad window path).

    ROOT CAUSE OF THE ORIGINAL CRASH:
      var.trace_add("write", lambda *a: self._on_toggle())
    When cards are destroyed during _refresh_app_cards / _refresh_service_cards
    while the tab is scrolled, the BooleanVar trace still fires into the old
    (destroyed) widget, causing:
      TclError: bad window path name ".!frame2.!frame2.!notebook.!frame..."

    The fix is two-part:
      1. _safe_set_bg checks winfo_exists() before touching any widget.
      2. ItemCard/ServiceCard remove the var trace on <Destroy>.
    """
    try:
        if not widget.winfo_exists():
            return
        widget.configure(bg=color)
    except tk.TclError:
        return
    except Exception:
        pass

    try:
        children = widget.winfo_children()
    except tk.TclError:
        return

    for child in children:
        _safe_set_bg(child, color)


class SectionHeader(tk.Frame):
    def __init__(self, parent, title: str, subtitle: str, **kwargs):
        super().__init__(parent, bg=COLORS["bg"], **kwargs)

        tk.Frame(self, bg=COLORS["accent"], width=3).pack(side="left", fill="y", padx=(0, 10), pady=2)

        text_frame = tk.Frame(self, bg=COLORS["bg"])
        text_frame.pack(side="left", fill="both", expand=True)

        tk.Label(text_frame, text=title.upper(), font=FONTS["label"],
                 bg=COLORS["bg"], fg=COLORS["accent"], anchor="w").pack(anchor="w")

        if subtitle:
            tk.Label(text_frame, text=subtitle, font=FONTS["small"],
                     bg=COLORS["bg"], fg=COLORS["text_muted"],
                     anchor="w", wraplength=720, justify="left").pack(anchor="w")


class ItemCard(tk.Frame):
    """Checkbox card for apps and tweaks."""

    def __init__(self, parent, name: str, description: str,
                 var: tk.BooleanVar, risk: str, risk_color: str, **kwargs):
        super().__init__(parent, bg=COLORS["surface"], **kwargs)
        self.var = var

        inner = tk.Frame(self, bg=COLORS["surface"], padx=12, pady=8)
        inner.pack(fill="both", expand=True)

        cb = tk.Checkbutton(inner, variable=var,
                             bg=COLORS["surface"], activebackground=COLORS["surface2"],
                             selectcolor=COLORS["bg"], cursor="hand2",
                             command=self._on_toggle)
        cb.grid(row=0, column=0, rowspan=2, padx=(0, 10), sticky="ns")

        tk.Label(inner, text=name, font=FONTS["body"],
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(inner, text=description, font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w").grid(row=1, column=1, sticky="w")

        tk.Label(inner, text=RISK_LABELS.get(risk, risk.upper()),
                 font=("Segoe UI", 7, "bold"),
                 bg=risk_color, fg="#000000" if risk == "low" else "#ffffff",
                 padx=5, pady=1).grid(row=0, column=2, padx=(8, 0), sticky="e")

        inner.columnconfigure(1, weight=1)

        for w in [self, inner]:
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        # Store trace id so we can remove it when widget is destroyed
        self._trace_id = var.trace_add("write", self._on_var_write)
        self.bind("<Destroy>", self._on_destroy)

        self._on_toggle()

    def _on_destroy(self, event):
        """Remove var trace when this widget is destroyed — prevents stale callbacks."""
        if event.widget is self:
            try:
                self.var.trace_remove("write", self._trace_id)
            except Exception:
                pass

    def _on_var_write(self, *_):
        """Var trace callback — guards against already-destroyed widget."""
        try:
            if self.winfo_exists():
                self._on_toggle()
        except tk.TclError:
            pass

    def _on_toggle(self):
        color = COLORS["surface2"] if self.var.get() else COLORS["surface"]
        _safe_set_bg(self, color)

    def _on_enter(self, _):
        if not self.var.get():
            _safe_set_bg(self, COLORS["surface2"])

    def _on_leave(self, _):
        if not self.var.get():
            _safe_set_bg(self, COLORS["surface"])


class ServiceCard(tk.Frame):
    """
    Card for a Windows service.
    Shows:
      - Checkbox (to select for bulk disable)
      - Name + description
      - Status badge (colored)
      - Risk badge
      - Block button  (if disabled -> block triggers)
      - Unblock button (if blocked -> restore)
    """

    def __init__(self, parent, name: str, description: str,
                 var: tk.BooleanVar, risk: str, risk_color: str,
                 status: str,
                 on_block=None, on_unblock=None, **kwargs):
        super().__init__(parent, bg=COLORS["surface"], **kwargs)
        self.var = var
        self.status = status
        self.on_block = on_block
        self.on_unblock = on_unblock

        inner = tk.Frame(self, bg=COLORS["surface"], padx=12, pady=7)
        inner.pack(fill="both", expand=True)

        cb = tk.Checkbutton(inner, variable=var,
                             bg=COLORS["surface"], activebackground=COLORS["surface2"],
                             selectcolor=COLORS["bg"], cursor="hand2",
                             command=self._on_toggle)
        cb.grid(row=0, column=0, rowspan=2, padx=(0, 10), sticky="ns")

        tk.Label(inner, text=name, font=FONTS["body"],
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w").grid(row=0, column=1, sticky="w")
        tk.Label(inner, text=description, font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w").grid(row=1, column=1, sticky="w")

        right = tk.Frame(inner, bg=COLORS["surface"])
        right.grid(row=0, column=2, rowspan=2, padx=(8, 0), sticky="e")

        status_text, status_color = SVC_STATUS_DISPLAY.get(status, ("? DESCONOCIDO", COLORS["border"]))
        tk.Label(right, text=status_text,
                 font=("Segoe UI", 8, "bold"),
                 bg=COLORS["bg"], fg=status_color,
                 padx=6, pady=2).pack(anchor="e", pady=(0, 2))

        tk.Label(right, text=RISK_LABELS.get(risk, risk.upper()),
                 font=("Segoe UI", 7, "bold"),
                 bg=risk_color, fg="#000000" if risk == "low" else "#ffffff",
                 padx=5, pady=1).pack(anchor="e", pady=(0, 2))

        if status == "disabled" and on_block:
            tk.Button(right, text="Bloquear triggers",
                      command=on_block,
                      bg=COLORS["surface2"], fg="#9966cc",
                      font=("Segoe UI", 8), relief="flat", cursor="hand2",
                      padx=4, pady=2,
                      activebackground=COLORS["btn_hover"]).pack(anchor="e")
        elif status == "blocked" and on_unblock:
            tk.Button(right, text="Desbloquear",
                      command=on_unblock,
                      bg=COLORS["surface2"], fg=COLORS["warning"],
                      font=("Segoe UI", 8), relief="flat", cursor="hand2",
                      padx=4, pady=2,
                      activebackground=COLORS["btn_hover"]).pack(anchor="e")

        inner.columnconfigure(1, weight=1)

        for w in [self, inner]:
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        self._trace_id = var.trace_add("write", self._on_var_write)
        self.bind("<Destroy>", self._on_destroy)

        self._on_toggle()

    def _on_destroy(self, event):
        if event.widget is self:
            try:
                self.var.trace_remove("write", self._trace_id)
            except Exception:
                pass

    def _on_var_write(self, *_):
        try:
            if self.winfo_exists():
                self._on_toggle()
        except tk.TclError:
            pass

    def _on_toggle(self):
        color = COLORS["surface2"] if self.var.get() else COLORS["surface"]
        _safe_set_bg(self, color)

    def _on_enter(self, _):
        if not self.var.get():
            _safe_set_bg(self, COLORS["surface2"])

    def _on_leave(self, _):
        if not self.var.get():
            _safe_set_bg(self, COLORS["surface"])


class TweakCard(tk.Frame):
    """
    Card for a Tweak with an ON/OFF toggle switch (like ServiceCard).
    on_enable(tweak_id) and on_disable(tweak_id) are called on toggle.
    """

    def __init__(self, parent, tweak_id: str, name: str, description: str,
                 risk: str, risk_color: str,
                 on_enable=None, on_disable=None, initial_state: bool = False, **kwargs):
        super().__init__(parent, bg=COLORS["surface"], **kwargs)
        self.tweak_id   = tweak_id
        self.on_enable  = on_enable
        self.on_disable = on_disable
        self._active    = initial_state   # reflects real system state

        inner = tk.Frame(self, bg=COLORS["surface"], padx=12, pady=8)
        inner.pack(fill="both", expand=True)

        # Left: name + description
        text_f = tk.Frame(inner, bg=COLORS["surface"])
        text_f.pack(side="left", fill="both", expand=True)
        tk.Label(text_f, text=name, font=FONTS["body"],
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w").pack(anchor="w")
        tk.Label(text_f, text=description, font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w").pack(anchor="w")

        # Right: risk badge + toggle
        right = tk.Frame(inner, bg=COLORS["surface"])
        right.pack(side="right", padx=(8, 0))

        tk.Label(right, text=RISK_LABELS.get(risk, risk.upper()),
                 font=("Segoe UI", 7, "bold"),
                 bg=risk_color, fg="#000000" if risk == "low" else "#ffffff",
                 padx=5, pady=1).pack(anchor="e", pady=(0, 6))

        self._toggle_btn = tk.Button(
            right, text="○  OFF",
            command=self._on_toggle,
            font=("Segoe UI", 8, "bold"),
            bg=COLORS["surface2"], fg=COLORS["text_muted"],
            relief="flat", cursor="hand2", padx=8, pady=3,
            activebackground=COLORS["btn_hover"],
        )
        self._toggle_btn.pack(anchor="e")

        for w in [self, inner, text_f]:
            w.bind("<Enter>", self._on_enter)
            w.bind("<Leave>", self._on_leave)

        # Render the initial state (may be ON if read from real system)
        self._update_visuals()

    def _on_toggle(self):
        self._active = not self._active
        self._update_visuals()
        if self._active and self.on_enable:
            self.on_enable(self.tweak_id)
        elif not self._active and self.on_disable:
            self.on_disable(self.tweak_id)

    def _update_visuals(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        if self._active:
            self._toggle_btn.config(
                text="●  ON", bg=COLORS["accent"], fg="#000000",
                activebackground=COLORS["accent_hover"],
            )
            _safe_set_bg(self, COLORS["surface2"])
        else:
            self._toggle_btn.config(
                text="○  OFF", bg=COLORS["surface2"], fg=COLORS["text_muted"],
                activebackground=COLORS["btn_hover"],
            )
            _safe_set_bg(self, COLORS["surface"])

    def set_active(self, value: bool):
        self._active = value
        self._update_visuals()

    def _on_enter(self, _):
        if not self._active:
            _safe_set_bg(self, COLORS["surface2"])

    def _on_leave(self, _):
        if not self._active:
            _safe_set_bg(self, COLORS["surface"])


class ProcessResourceCard(tk.Frame):
    """
    Card showing resource usage + manual limits for one running process.
    Always in manual mode — user adjusts CPU/RAM/GPU per process and clicks Apply.

    Layout:
      [name + RAM info]  [CPU slider] [RAM slider] [GPU slider]  [Aplicar] [Restablecer]
    """

    def __init__(self, parent, proc: dict,
                 on_apply=None,
                 on_reset=None,
                 **kwargs):
        super().__init__(parent, bg=COLORS["surface"], **kwargs)
        self.proc       = proc
        self.on_apply   = on_apply
        self.on_reset   = on_reset

        ncores = max(1, __import__("os").cpu_count() or 4)

        # Vars — default to no restriction (100% / current RAM)
        self.cpu_var = tk.IntVar(value=100)
        self.ram_var = tk.IntVar(value=max(proc["ram_min_mb"], proc["ram_mb"]))
        self.gpu_var = tk.IntVar(value=100)

        inner = tk.Frame(self, bg=COLORS["surface"], padx=10, pady=6)
        inner.pack(fill="both", expand=True)

        # ── Name + RAM usage ──────────────────────────────────────────
        left = tk.Frame(inner, bg=COLORS["surface"], width=180)
        left.pack(side="left", fill="y")
        left.pack_propagate(False)

        name_short = proc["name"][:22]
        tk.Label(left, text=name_short, font=FONTS["body"],
                 bg=COLORS["surface"], fg=COLORS["text"], anchor="w").pack(anchor="w")

        ram_color = COLORS["warning"] if proc["ram_mb"] > 500 else COLORS["text_muted"]
        tk.Label(left, text=f"RAM actual: {proc['ram_mb']} MB",
                 font=FONTS["small"], bg=COLORS["surface"],
                 fg=ram_color, anchor="w").pack(anchor="w")
        tk.Label(left, text=f"Min seguro: {proc['ram_min_mb']} MB",
                 font=FONTS["small"], bg=COLORS["surface"],
                 fg=COLORS["border"], anchor="w").pack(anchor="w")

        # ── Sliders frame ─────────────────────────────────────────────
        sliders = tk.Frame(inner, bg=COLORS["surface"])
        sliders.pack(side="left", fill="both", expand=True, padx=(8, 0))

        self._build_slider(sliders, "CPU",
                           self.cpu_var, 10, 100, 1, "%",
                           f"{ncores} núcleos → % de afinidad")
        self._build_slider(sliders, "RAM",
                           self.ram_var,
                           proc["ram_min_mb"],
                           max(proc["ram_min_mb"] + 100, proc["ram_mb"] * 4, 4096),
                           50, "MB",
                           f"Mín. {proc['ram_min_mb']} MB")
        self._build_slider(sliders, "GPU",
                           self.gpu_var, 10, 100, 1, "%",
                           "Frecuencia relativa (NVIDIA)")

        # ── Buttons ───────────────────────────────────────────────────
        btn_f = tk.Frame(inner, bg=COLORS["surface"])
        btn_f.pack(side="right", padx=(8, 0))

        tk.Button(
            btn_f, text="Aplicar",
            command=self._do_apply,
            bg=COLORS["accent"], fg="#000",
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=4,
            activebackground=COLORS["accent_hover"],
        ).pack(fill="x", pady=(0, 4))

        tk.Button(
            btn_f, text="Restablecer",
            command=self._do_reset,
            bg=COLORS["surface2"], fg=COLORS["text_muted"],
            font=FONTS["small"], relief="flat", cursor="hand2",
            padx=8, pady=4,
            activebackground=COLORS["btn_hover"],
        ).pack(fill="x")

    def _build_slider(self, parent, label, var, from_, to, resolution, unit, hint):
        row = tk.Frame(parent, bg=COLORS["surface"])
        row.pack(fill="x", pady=1)

        tk.Label(row, text=f"{label}:", font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"],
                 width=4, anchor="e").pack(side="left")

        scale = tk.Scale(
            row, variable=var, from_=from_, to=to,
            resolution=resolution, orient="horizontal",
            bg=COLORS["surface"], fg=COLORS["text"],
            troughcolor=COLORS["bg"], highlightthickness=0,
            activebackground=COLORS["accent"],
            sliderlength=14, width=8, length=220,
            showvalue=False,
        )
        scale.pack(side="left")

        val_lbl = tk.Label(row, textvariable=var, font=FONTS["small"],
                           bg=COLORS["surface"], fg=COLORS["accent"], width=5, anchor="w")
        val_lbl.pack(side="left")
        tk.Label(row, text=unit, font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"]).pack(side="left")
        tk.Label(row, text=f"  {hint}", font=("Segoe UI", 7),
                 bg=COLORS["surface"], fg=COLORS["border"]).pack(side="left")

    def _do_apply(self):
        if self.on_apply:
            self.on_apply(
                self.proc["pid"],
                self.proc["name"],
                self.cpu_var.get(),
                self.ram_var.get(),
                self.proc["ram_min_mb"],
                self.gpu_var.get(),
            )

    def _do_reset(self):
        if self.on_reset:
            self.on_reset(self.proc["pid"], self.proc["name"])


class StatusBar(tk.Frame):
    def __init__(self, parent, text_var: tk.StringVar, **kwargs):
        super().__init__(parent, bg=COLORS["surface"], height=28, **kwargs)
        self.pack_propagate(False)

        self.dot = tk.Label(self, text="●", font=("Segoe UI", 8),
                            bg=COLORS["surface"], fg=COLORS["success"])
        self.dot.pack(side="left", padx=(12, 4))

        tk.Label(self, textvariable=text_var, font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w").pack(side="left", fill="x", expand=True)

        tk.Label(self, text="WinClean v2.1 • Windows 10/11",
                 font=FONTS["small"], bg=COLORS["surface"], fg=COLORS["border"]).pack(side="right", padx=12)

        text_var.trace_add("write", lambda *a: self._update_dot(text_var.get()))

    def _update_dot(self, text: str):
        t = text.lower()
        if "✅" in text:
            color = COLORS["success"]
        elif "error" in t or "fallo" in t or "advertencia" in t:
            color = COLORS["danger"]
        elif "aplicando" in t or "desinstal" in t or "bloqueando" in t or "escaneando" in t:
            color = COLORS["warning"]
        else:
            color = COLORS["accent"]
        try:
            self.dot.config(fg=color)
        except tk.TclError:
            pass
