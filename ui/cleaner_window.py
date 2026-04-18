"""
ui/cleaner_window.py — Ventana modal del Limpiador de Windows
Layout rediseñado para pantallas pequeñas:
  · Cabecera compacta
  · Botones SIEMPRE visibles arriba (sticky top)
  · Panel de pasos compacto con scroll si hay muchos
  · Log ocupa el espacio restante con altura mínima garantizada
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import ctypes
import os
import sys

from core.cleaner import CLEANER_STEPS
from ui.styles import COLORS, FONTS


def _is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


class CleanerWindow(tk.Toplevel):
    """Ventana del limpiador de disco."""

    _LOG_COLORS = {
        "✅": "#4caf80",
        "✓":  "#4caf80",
        "✗":  "#e05c5c",
        "⚠":  "#f5a623",
        "→":  "#7a8099",
        "[":  "#4da6ff",
    }

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Limpiador de Windows")
        self.geometry("860x620")
        self.minsize(640, 460)
        self.configure(bg=COLORS["bg"])
        self.transient(parent)
        self.resizable(True, True)
        self.lift()
        self.focus_force()

        self._stop_event = threading.Event()
        self._running = False
        self._step_vars: dict[str, tk.BooleanVar] = {}
        self._total_freed = 0

        self._build_ui()
        self._center(parent)

        if not _is_admin():
            self._log_line(
                "⚠  Sin privilegios de Administrador — algunos pasos pueden fallar. "
                "Reinicia con 'Ejecutar como administrador'.",
                color=COLORS["warning"]
            )

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Cabecera compacta ────────────────────────────────────────
        header = tk.Frame(self, bg=COLORS["surface"], pady=8, padx=16)
        header.pack(fill="x", side="top")

        tk.Label(
            header, text="🧹  Limpiador de Windows",
            font=FONTS["label"], bg=COLORS["surface"], fg=COLORS["accent"]
        ).pack(side="left")

        tk.Label(
            header, text="Selecciona pasos y pulsa Iniciar.",
            font=FONTS["small"], bg=COLORS["surface"], fg=COLORS["text_muted"]
        ).pack(side="left", padx=12)

        # ── Barra de botones — SIEMPRE VISIBLE, pegada arriba ────────
        btn_bar = tk.Frame(self, bg=COLORS["surface"], pady=8, padx=16)
        btn_bar.pack(fill="x", side="top")

        self._start_btn = tk.Button(
            btn_bar, text="▶  Iniciar limpieza",
            command=self._on_start,
            bg=COLORS["accent"], fg="#000000",
            font=FONTS["button"], relief="flat", cursor="hand2",
            padx=16, pady=6,
            activebackground=COLORS["accent_hover"],
        )
        self._start_btn.pack(side="left")

        self._cancel_btn = tk.Button(
            btn_bar, text="⏹  Cancelar",
            command=self._on_cancel,
            bg=COLORS["btn"], fg=COLORS["warning"],
            font=FONTS["button"], relief="flat", cursor="hand2",
            padx=12, pady=6,
            state="disabled",
            activebackground=COLORS["btn_hover"],
        )
        self._cancel_btn.pack(side="left", padx=(8, 0))

        self._close_btn = tk.Button(
            btn_bar, text="Cerrar",
            command=self._on_close,
            bg=COLORS["btn"], fg=COLORS["text_muted"],
            font=FONTS["button"], relief="flat", cursor="hand2",
            padx=12, pady=6,
            activebackground=COLORS["btn_hover"],
        )
        self._close_btn.pack(side="left", padx=(8, 0))

        self._freed_label = tk.Label(
            btn_bar, text="",
            font=FONTS["body"], bg=COLORS["surface"], fg=COLORS["success"]
        )
        self._freed_label.pack(side="left", padx=(16, 0))

        # ── Barra de progreso ────────────────────────────────────────
        prog_frame = tk.Frame(self, bg=COLORS["bg"], padx=16, pady=4)
        prog_frame.pack(fill="x", side="top")

        self._prog_label = tk.Label(
            prog_frame, text="Listo para iniciar.",
            font=FONTS["small"], bg=COLORS["bg"], fg=COLORS["text_muted"], anchor="w"
        )
        self._prog_label.pack(fill="x")

        self._progressbar = ttk.Progressbar(
            prog_frame, orient="horizontal", mode="determinate"
        )
        self._progressbar.pack(fill="x", pady=(2, 0))

        # ── Separador ────────────────────────────────────────────────
        tk.Frame(self, bg=COLORS["border"], height=1).pack(fill="x", side="top")

        # ── Cuerpo: pasos (izquierda) + log (derecha/abajo) ─────────
        body = tk.Frame(self, bg=COLORS["bg"])
        body.pack(fill="both", expand=True, side="top")

        # Panel de pasos — ancho fijo, scroll si muchos
        steps_col = tk.Frame(body, bg=COLORS["surface"], width=300)
        steps_col.pack(side="left", fill="y", padx=(0, 1))
        steps_col.pack_propagate(False)

        tk.Label(
            steps_col, text="PASOS A EJECUTAR",
            font=FONTS["label"], bg=COLORS["surface"], fg=COLORS["accent"]
        ).pack(anchor="w", padx=12, pady=(10, 4))

        # Scrollable steps list
        steps_canvas = tk.Canvas(steps_col, bg=COLORS["surface"], highlightthickness=0, bd=0)
        steps_sb = ttk.Scrollbar(steps_col, orient="vertical", command=steps_canvas.yview)
        steps_inner = tk.Frame(steps_canvas, bg=COLORS["surface"])
        steps_inner.bind("<Configure>", lambda e: steps_canvas.configure(
            scrollregion=steps_canvas.bbox("all")))
        steps_canvas.create_window((0, 0), window=steps_inner, anchor="nw")
        steps_canvas.configure(yscrollcommand=steps_sb.set)
        steps_sb.pack(side="right", fill="y")
        steps_canvas.pack(side="left", fill="both", expand=True)

        def _mw(e): steps_canvas.yview_scroll(int(-1*(e.delta/120)), "units")
        steps_canvas.bind("<Enter>", lambda e: steps_canvas.bind_all("<MouseWheel>", _mw))
        steps_canvas.bind("<Leave>", lambda e: steps_canvas.unbind_all("<MouseWheel>"))

        for step in CLEANER_STEPS:
            var = tk.BooleanVar(value=step["default"])
            self._step_vars[step["id"]] = var
            row = tk.Frame(steps_inner, bg=COLORS["surface"])
            row.pack(fill="x", padx=8, pady=3)

            cb = tk.Checkbutton(
                row, variable=var,
                bg=COLORS["surface"], activebackground=COLORS["surface"],
                selectcolor=COLORS["bg"], cursor="hand2",
            )
            cb.pack(side="left", anchor="n", pady=2)

            text_col = tk.Frame(row, bg=COLORS["surface"])
            text_col.pack(side="left", fill="x", expand=True)

            tk.Label(
                text_col, text=step["label"],
                font=FONTS["small"], bg=COLORS["surface"], fg=COLORS["text"],
                anchor="w", wraplength=220, justify="left"
            ).pack(anchor="w")

            tk.Label(
                text_col, text=step["detail"],
                font=("Segoe UI", 7), bg=COLORS["surface"], fg=COLORS["text_muted"],
                anchor="w", wraplength=220, justify="left"
            ).pack(anchor="w")

        # Separador vertical
        tk.Frame(body, bg=COLORS["border"], width=1).pack(side="left", fill="y")

        # Panel de log — ocupa todo el resto
        log_col = tk.Frame(body, bg=COLORS["bg"])
        log_col.pack(side="left", fill="both", expand=True)

        tk.Label(
            log_col, text="LOG EN TIEMPO REAL",
            font=FONTS["label"], bg=COLORS["bg"], fg=COLORS["accent"]
        ).pack(anchor="w", padx=12, pady=(8, 4))

        text_frame = tk.Frame(log_col, bg=COLORS["surface"])
        text_frame.pack(fill="both", expand=True, padx=12, pady=(0, 8))

        self._log = tk.Text(
            text_frame,
            bg=COLORS["surface"], fg=COLORS["text"],
            font=FONTS["mono"],
            relief="flat", bd=0,
            state="disabled",
            wrap="word",
            padx=8, pady=8,
        )
        log_sb = ttk.Scrollbar(text_frame, orient="vertical", command=self._log.yview)
        self._log.configure(yscrollcommand=log_sb.set)
        log_sb.pack(side="right", fill="y")
        self._log.pack(side="left", fill="both", expand=True)

        # Tags de color
        for char, color in self._LOG_COLORS.items():
            self._log.tag_configure(f"color_{char}", foreground=color)
        self._log.tag_configure("header",  foreground=COLORS["accent"],  font=(*FONTS["body"][:2], "bold"))
        self._log.tag_configure("freed",   foreground=COLORS["success"], font=FONTS["mono"])
        self._log.tag_configure("warning", foreground=COLORS["warning"])
        self._log.tag_configure("error",   foreground=COLORS["danger"])
        self._log.tag_configure("muted",   foreground=COLORS["text_muted"])

    def _center(self, parent):
        self.update_idletasks()
        w, h = 860, 620
        px = parent.winfo_x() + (parent.winfo_width()  - w) // 2
        py = parent.winfo_y() + (parent.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{max(px,0)}+{max(py,0)}")

    # ── Log ───────────────────────────────────────────────────────────────────

    def _log_line(self, text: str, color: str | None = None):
        self.after(0, lambda: self._append_log(text, color))

    def _append_log(self, text: str, color: str | None = None):
        self._log.configure(state="normal")
        if color:
            tag = f"_dyn_{color}"
            self._log.tag_configure(tag, foreground=color)
            self._log.insert("end", text + "\n", tag)
        elif text.startswith("  [") or text.startswith("["):
            self._log.insert("end", text + "\n", "header")
        elif "✅" in text or "✓" in text:
            self._log.insert("end", text + "\n", "freed")
        elif "⚠" in text:
            self._log.insert("end", text + "\n", "warning")
        elif "✗" in text:
            self._log.insert("end", text + "\n", "error")
        elif text.strip().startswith("→") or text.strip().startswith("Deteniendo") or text.strip().startswith("Reiniciando"):
            self._log.insert("end", text + "\n", "muted")
        else:
            self._log.insert("end", text + "\n")
        self._log.configure(state="disabled")
        self._log.see("end")

    # ── Botones ───────────────────────────────────────────────────────────────

    def _on_start(self):
        selected = [s for s in CLEANER_STEPS if self._step_vars[s["id"]].get()]
        if not selected:
            messagebox.showwarning("Nada seleccionado",
                                   "Marca al menos un paso antes de iniciar.", parent=self)
            return

        self._stop_event.clear()
        self._running = True
        self._total_freed = 0
        self._start_btn.config(state="disabled")
        self._cancel_btn.config(state="normal")
        self._close_btn.config(state="disabled")
        self._freed_label.config(text="")

        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

        self._progressbar["maximum"] = len(selected)
        self._progressbar["value"] = 0

        threading.Thread(target=self._run_clean, args=(selected,), daemon=True).start()

    def _on_cancel(self):
        self._stop_event.set()
        self._log_line("⚠  Cancelando... (espera a que el paso actual termine)",
                       color=COLORS["warning"])
        self._cancel_btn.config(state="disabled")

    def _on_close(self):
        if self._running:
            if not messagebox.askyesno("Cerrar", "La limpieza está en marcha. ¿Cerrar igualmente?",
                                       parent=self):
                return
            self._stop_event.set()
        self.destroy()

    # ── Limpieza ──────────────────────────────────────────────────────────────

    def _run_clean(self, steps: list):
        total = len(steps)
        freed_total = 0

        for i, step in enumerate(steps, start=1):
            if self._stop_event.is_set():
                break

            header = f"\n{'─'*50}\n  {step['label']}\n{'─'*50}"
            self._log_line(header, color=COLORS["accent"])
            self.after(0, lambda lbl=f"Paso {i}/{total}: {step['label']}":
                       self._prog_label.config(text=lbl))

            try:
                freed = step["fn"](self._log_line, self._stop_event)
                freed_total += freed
            except Exception as e:
                self._log_line(f"  ✗  Error en este paso: {e}", color=COLORS["danger"])

            self.after(0, lambda v=i: self._progressbar.configure(value=v))

        self._total_freed = freed_total
        self.after(0, self._on_finish)

    def _on_finish(self):
        self._running = False
        self._start_btn.config(state="normal")
        self._cancel_btn.config(state="disabled")
        self._close_btn.config(state="normal")

        from core.cleaner import _fmt_bytes
        freed_str = _fmt_bytes(self._total_freed)

        if self._stop_event.is_set():
            self._log_line(f"⚠  Limpieza cancelada. Liberado: {freed_str}",
                           color=COLORS["warning"])
            self._prog_label.config(text=f"Cancelado. Liberado: {freed_str}")
        else:
            self._log_line(
                f"\n{'═'*50}\n✅  Completado.  Espacio liberado: {freed_str}\n{'═'*50}",
                color=COLORS["success"]
            )
            self._prog_label.config(text=f"✅ Completado. Liberado: {freed_str}")

        self._freed_label.config(text=f"Liberado: {freed_str}")
