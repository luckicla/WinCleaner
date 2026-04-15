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


class StatusBar(tk.Frame):
    def __init__(self, parent, text_var: tk.StringVar, **kwargs):
        super().__init__(parent, bg=COLORS["surface"], height=28, **kwargs)
        self.pack_propagate(False)

        self.dot = tk.Label(self, text="●", font=("Segoe UI", 8),
                            bg=COLORS["surface"], fg=COLORS["success"])
        self.dot.pack(side="left", padx=(12, 4))

        tk.Label(self, textvariable=text_var, font=FONTS["small"],
                 bg=COLORS["surface"], fg=COLORS["text_muted"], anchor="w").pack(side="left", fill="x", expand=True)

        tk.Label(self, text="WinClean v1.2 • Windows 10",
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
