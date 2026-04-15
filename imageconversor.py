"""
Conversor de imágenes por lotes
Requiere: pip install Pillow
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from PIL import Image, ImageTk
import threading
import os


# ── Colores y fuentes ───────────────────────────────────────────────────────
BG        = "#1a1a2e"
SURFACE   = "#16213e"
CARD      = "#0f3460"
ACCENT    = "#e94560"
ACCENT2   = "#53d8fb"
TEXT      = "#eaeaea"
TEXT_MUTED= "#8892a4"
SUCCESS   = "#4ade80"
FONT      = ("Segoe UI", 10)
FONT_BOLD = ("Segoe UI", 10, "bold")
FONT_BIG  = ("Segoe UI", 13, "bold")
FONT_TITLE= ("Segoe UI", 18, "bold")


FORMATOS = ["JPG", "PNG", "WebP", "BMP", "TIFF", "ICO"]
EXTENSIONES = {
    "JPG":  ".jpg",
    "PNG":  ".png",
    "WebP": ".webp",
    "BMP":  ".bmp",
    "TIFF": ".tiff",
    "ICO":  ".ico",
}
PIL_FORMAT = {
    "JPG":  "JPEG",
    "PNG":  "PNG",
    "WebP": "WEBP",
    "BMP":  "BMP",
    "TIFF": "TIFF",
    "ICO":  "ICO",
}

# Tamaños estándar que se incluyen dentro del .ico
ICO_SIZES = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


class ConversorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Conversor de imágenes")
        self.geometry("900x650")
        self.minsize(750, 550)
        self.configure(bg=BG)
        self.resizable(True, True)

        self.archivos = []          # rutas absolutas
        self.thumbs   = {}          # ruta -> PhotoImage (para no perder referencia)
        self.formato_var  = tk.StringVar(value="WebP")
        self.calidad_var  = tk.IntVar(value=85)
        self.destino_var  = tk.StringVar(value="misma")  # "misma" | "elegir"
        self.destino_path = tk.StringVar(value="")
        self.progreso_var = tk.DoubleVar(value=0)
        # ICO: checkboxes para cada tamaño
        self.ico_sizes_vars = {s: tk.BooleanVar(value=True) for s in ICO_SIZES}

        self._build_ui()

    # ── Construcción de UI ─────────────────────────────────────────────────

    def _build_ui(self):
        # Título
        header = tk.Frame(self, bg=BG, pady=14)
        header.pack(fill="x", padx=24)
        tk.Label(header, text="🖼  Conversor de imágenes", font=FONT_TITLE,
                 bg=BG, fg=ACCENT2).pack(side="left")
        tk.Label(header, text="por lotes · local · gratuito", font=FONT,
                 bg=BG, fg=TEXT_MUTED).pack(side="left", padx=10, pady=4)

        # Cuerpo principal (izq + der)
        body = tk.Frame(self, bg=BG)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 8))

        self._panel_izquierdo(body)
        self._panel_derecho(body)

        # Barra de progreso + botón convertir
        self._panel_inferior()

    def _panel_izquierdo(self, parent):
        frame = tk.Frame(parent, bg=SURFACE, bd=0, relief="flat")
        frame.pack(side="left", fill="both", expand=True, padx=(0, 10))

        tk.Label(frame, text="Imágenes seleccionadas", font=FONT_BOLD,
                 bg=SURFACE, fg=TEXT).pack(anchor="w", padx=14, pady=(12, 4))

        # Zona drop / lista
        self.lista_frame = tk.Frame(frame, bg=SURFACE)
        self.lista_frame.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self.canvas_lista = tk.Canvas(self.lista_frame, bg=SURFACE,
                                      highlightthickness=0)
        scroll = ttk.Scrollbar(self.lista_frame, orient="vertical",
                               command=self.canvas_lista.yview)
        self.canvas_lista.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.canvas_lista.pack(side="left", fill="both", expand=True)

        self.inner = tk.Frame(self.canvas_lista, bg=SURFACE)
        self.canvas_win = self.canvas_lista.create_window(
            (0, 0), window=self.inner, anchor="nw")
        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas_lista.bind("<Configure>", self._on_canvas_configure)

        self._mostrar_placeholder()

        # Botones añadir / limpiar
        btns = tk.Frame(frame, bg=SURFACE)
        btns.pack(fill="x", padx=10, pady=(0, 12))
        self._btn(btns, "＋  Añadir imágenes", self._añadir_archivos,
                  ACCENT).pack(side="left", padx=(0, 6))
        self._btn(btns, "✕  Limpiar todo", self._limpiar,
                  CARD).pack(side="left")
        tk.Label(btns, textvariable=self._contador_label(),
                 font=FONT, bg=SURFACE, fg=TEXT_MUTED).pack(side="right", padx=6)

    def _contador_label(self):
        self._count_var = tk.StringVar(value="0 archivos")
        return self._count_var

    def _panel_derecho(self, parent):
        frame = tk.Frame(parent, bg=SURFACE, width=240)
        frame.pack(side="right", fill="y")
        frame.pack_propagate(False)

        def sección(titulo):
            tk.Label(frame, text=titulo, font=FONT_BOLD,
                     bg=SURFACE, fg=ACCENT2).pack(anchor="w", padx=14, pady=(14, 4))
            sep = tk.Frame(frame, bg=CARD, height=1)
            sep.pack(fill="x", padx=14, pady=(0, 8))

        # Formato de salida
        sección("Formato de salida")
        fmts = tk.Frame(frame, bg=SURFACE)
        fmts.pack(fill="x", padx=14)
        for i, fmt in enumerate(FORMATOS):
            rb = tk.Radiobutton(fmts, text=fmt, variable=self.formato_var,
                                value=fmt, font=FONT, bg=SURFACE, fg=TEXT,
                                activebackground=SURFACE, activeforeground=ACCENT,
                                selectcolor=CARD, indicatoron=0,
                                relief="flat", bd=0,
                                padx=10, pady=5, cursor="hand2",
                                command=self._actualizar_calidad_visibilidad)
            rb.grid(row=i // 2, column=i % 2, sticky="w", padx=3, pady=2)

        # Tamaños ICO (solo visible cuando formato == ICO)
        self.ico_frame = tk.Frame(frame, bg=SURFACE)
        self.ico_frame.pack(fill="x", padx=14, pady=(4, 0))
        tk.Label(self.ico_frame, text="Tamaños a incluir:", font=("Segoe UI", 9),
                 bg=SURFACE, fg=TEXT_MUTED).pack(anchor="w")
        grid_ico = tk.Frame(self.ico_frame, bg=SURFACE)
        grid_ico.pack(anchor="w")
        for idx, size in enumerate(ICO_SIZES):
            lbl = f"{size[0]}px"
            cb = tk.Checkbutton(grid_ico, text=lbl,
                                variable=self.ico_sizes_vars[size],
                                font=("Segoe UI", 9), bg=SURFACE, fg=TEXT,
                                activebackground=SURFACE, selectcolor=CARD,
                                relief="flat", bd=0, cursor="hand2")
            cb.grid(row=idx // 3, column=idx % 3, sticky="w", padx=4, pady=1)
        self.ico_frame.pack_forget()  # oculto por defecto

        # Calidad
        sección("Calidad")
        self.calidad_frame = tk.Frame(frame, bg=SURFACE)
        self.calidad_frame.pack(fill="x", padx=14)
        self.lbl_calidad = tk.Label(self.calidad_frame,
                                    text=f"85%", font=FONT_BOLD,
                                    bg=SURFACE, fg=ACCENT)
        self.lbl_calidad.pack(anchor="w")
        self.slider_calidad = ttk.Scale(self.calidad_frame,
                                        from_=1, to=100,
                                        variable=self.calidad_var,
                                        orient="horizontal",
                                        command=self._on_calidad)
        self.slider_calidad.pack(fill="x", pady=(2, 0))
        tk.Label(self.calidad_frame, text="Menor peso          Mayor calidad",
                 font=("Segoe UI", 8), bg=SURFACE, fg=TEXT_MUTED).pack(anchor="w")

        # Destino
        sección("Carpeta de destino")
        dest = tk.Frame(frame, bg=SURFACE)
        dest.pack(fill="x", padx=14)
        for val, txt in [("misma", "Misma carpeta que origen"),
                         ("elegir", "Elegir carpeta…")]:
            tk.Radiobutton(dest, text=txt, variable=self.destino_var,
                           value=val, font=FONT, bg=SURFACE, fg=TEXT,
                           activebackground=SURFACE, selectcolor=CARD,
                           indicatoron=1, relief="flat", bd=0,
                           command=self._on_destino_cambia,
                           cursor="hand2").pack(anchor="w", pady=1)
        self.lbl_destino = tk.Label(dest, textvariable=self.destino_path,
                                    font=("Segoe UI", 8), bg=SURFACE,
                                    fg=TEXT_MUTED, wraplength=200,
                                    justify="left")
        self.lbl_destino.pack(anchor="w", pady=(2, 0))

        # Notas
        sección("Info")
        notas = (
            "• BMP y PNG no usan\n  compresión con pérdida\n"
            "• WebP = mejor balance\n  tamaño/calidad\n"
            "• ICO incluye múltiples\n  tamaños en un archivo\n"
            "• Los originales no se\n  modifican nunca"
        )
        tk.Label(frame, text=notas, font=("Segoe UI", 9),
                 bg=SURFACE, fg=TEXT_MUTED, justify="left").pack(
                     anchor="w", padx=14, pady=(0, 8))

    def _panel_inferior(self):
        bottom = tk.Frame(self, bg=BG, pady=10)
        bottom.pack(fill="x", padx=24, pady=(0, 14))

        self.lbl_estado = tk.Label(bottom, text="Listo para convertir.",
                                   font=FONT, bg=BG, fg=TEXT_MUTED)
        self.lbl_estado.pack(side="left")

        self.btn_convertir = self._btn(bottom, "⚡  Convertir todo",
                                       self._iniciar_conversion, ACCENT,
                                       font=FONT_BIG, padx=22, pady=10)
        self.btn_convertir.pack(side="right")

        self.barra = ttk.Progressbar(bottom, variable=self.progreso_var,
                                     maximum=100, length=220, mode="determinate")
        self.barra.pack(side="right", padx=14)

    # ── Helpers de UI ──────────────────────────────────────────────────────

    def _btn(self, parent, texto, comando, color, font=FONT,
             padx=14, pady=7):
        btn = tk.Button(parent, text=texto, command=comando,
                        bg=color, fg=TEXT, font=font,
                        relief="flat", bd=0, cursor="hand2",
                        padx=padx, pady=pady, activebackground=ACCENT2,
                        activeforeground=BG)
        btn.bind("<Enter>", lambda e: btn.configure(bg=ACCENT2, fg=BG))
        btn.bind("<Leave>", lambda e: btn.configure(bg=color, fg=TEXT))
        return btn

    def _mostrar_placeholder(self):
        for w in self.inner.winfo_children():
            w.destroy()
        lbl = tk.Label(self.inner,
                       text="Haz clic en '＋ Añadir imágenes'\npara empezar",
                       font=FONT, bg=SURFACE, fg=TEXT_MUTED,
                       justify="center", pady=40)
        lbl.pack(expand=True)

    def _on_inner_configure(self, event=None):
        self.canvas_lista.configure(
            scrollregion=self.canvas_lista.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas_lista.itemconfig(self.canvas_win, width=event.width)

    def _on_calidad(self, val):
        self.lbl_calidad.config(text=f"{int(float(val))}%")

    def _actualizar_calidad_visibilidad(self):
        fmt = self.formato_var.get()
        # Slider de calidad: solo JPG y WebP
        estado = "normal" if fmt in ("JPG", "WebP") else "disabled"
        self.slider_calidad.configure(state=estado)
        # Panel de tamaños ICO
        if fmt == "ICO":
            self.ico_frame.pack(fill="x", padx=14, pady=(4, 0),
                                before=self.calidad_frame)
        else:
            self.ico_frame.pack_forget()

    def _on_destino_cambia(self):
        if self.destino_var.get() == "elegir":
            ruta = filedialog.askdirectory(title="Selecciona carpeta de destino")
            if ruta:
                self.destino_path.set(ruta)
            else:
                self.destino_var.set("misma")
                self.destino_path.set("")
        else:
            self.destino_path.set("")

    # ── Lógica de archivos ─────────────────────────────────────────────────

    def _añadir_archivos(self):
        tipos = [("Imágenes", "*.jpg *.jpeg *.png *.webp *.bmp *.tiff *.gif"),
                 ("Todos", "*.*")]
        rutas = filedialog.askopenfilenames(title="Selecciona imágenes",
                                            filetypes=tipos)
        nuevas = [r for r in rutas if r not in self.archivos]
        self.archivos.extend(nuevas)
        self._actualizar_lista()

    def _limpiar(self):
        self.archivos.clear()
        self.thumbs.clear()
        self._mostrar_placeholder()
        self._count_var.set("0 archivos")
        self.progreso_var.set(0)
        self.lbl_estado.config(text="Listo para convertir.", fg=TEXT_MUTED)

    def _actualizar_lista(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.thumbs.clear()
        self._count_var.set(f"{len(self.archivos)} archivo(s)")

        for ruta in self.archivos:
            self._fila_archivo(ruta)

    def _fila_archivo(self, ruta):
        fila = tk.Frame(self.inner, bg=CARD, pady=4)
        fila.pack(fill="x", padx=4, pady=2)

        # Thumbnail
        try:
            img = Image.open(ruta)
            img.thumbnail((48, 48))
            photo = ImageTk.PhotoImage(img)
            self.thumbs[ruta] = photo
            tk.Label(fila, image=photo, bg=CARD).pack(side="left", padx=8)
        except Exception:
            tk.Label(fila, text="?", bg=CARD, fg=TEXT_MUTED,
                     width=4).pack(side="left", padx=8)

        # Info
        info = tk.Frame(fila, bg=CARD)
        info.pack(side="left", fill="both", expand=True)
        nombre = Path(ruta).name
        tk.Label(info, text=nombre, font=FONT_BOLD, bg=CARD, fg=TEXT,
                 anchor="w").pack(anchor="w")
        try:
            tam = os.path.getsize(ruta)
            img2 = Image.open(ruta)
            detalle = f"{img2.width}×{img2.height}  ·  {tam/1024:.1f} KB  ·  {img2.format or '?'}"
        except Exception:
            detalle = "No se pudo leer la info"
        tk.Label(info, text=detalle, font=("Segoe UI", 8),
                 bg=CARD, fg=TEXT_MUTED, anchor="w").pack(anchor="w")

        # Botón eliminar
        def eliminar(r=ruta):
            self.archivos.remove(r)
            self._actualizar_lista()

        tk.Button(fila, text="✕", command=eliminar,
                  bg=CARD, fg=TEXT_MUTED, font=FONT,
                  relief="flat", bd=0, cursor="hand2",
                  activebackground=ACCENT, activeforeground=TEXT).pack(
                      side="right", padx=8)

    # ── Conversión ─────────────────────────────────────────────────────────

    def _iniciar_conversion(self):
        if not self.archivos:
            messagebox.showwarning("Sin imágenes",
                                   "Añade al menos una imagen para convertir.")
            return
        self.btn_convertir.configure(state="disabled")
        self.progreso_var.set(0)
        hilo = threading.Thread(target=self._convertir, daemon=True)
        hilo.start()

    def _convertir(self):
        fmt     = self.formato_var.get()
        calidad = self.calidad_var.get()
        ext     = EXTENSIONES[fmt]
        pil_fmt = PIL_FORMAT[fmt]
        total   = len(self.archivos)
        errores = []

        # Tamaños ICO seleccionados
        ico_sizes = [s for s, var in self.ico_sizes_vars.items() if var.get()]
        if fmt == "ICO" and not ico_sizes:
            ico_sizes = [(32, 32)]  # fallback mínimo

        for i, ruta in enumerate(self.archivos, 1):
            try:
                origen = Path(ruta)
                if self.destino_var.get() == "elegir" and self.destino_path.get():
                    carpeta_salida = Path(self.destino_path.get())
                else:
                    carpeta_salida = origen.parent

                nombre_salida = carpeta_salida / (origen.stem + ext)

                # Evitar sobreescribir si es el mismo formato
                if nombre_salida == origen:
                    nombre_salida = carpeta_salida / (origen.stem + "_convertido" + ext)

                img_original = Image.open(ruta)

                if fmt == "ICO":
                    # Convertir a RGBA para transparencia correcta en ICO
                    img_rgba = img_original.convert("RGBA")
                    # Generar una versión redimensionada por cada tamaño elegido
                    imagenes_ico = []
                    for size in sorted(ico_sizes):
                        copia = img_rgba.copy()
                        copia.thumbnail(size, Image.LANCZOS)
                        # Crear lienzo exacto del tamaño objetivo
                        lienzo = Image.new("RGBA", size, (0, 0, 0, 0))
                        offset = ((size[0] - copia.width) // 2,
                                  (size[1] - copia.height) // 2)
                        lienzo.paste(copia, offset)
                        imagenes_ico.append(lienzo)
                    # Guardar todas las resoluciones en un único .ico
                    imagenes_ico[0].save(
                        nombre_salida,
                        format="ICO",
                        sizes=[im.size for im in imagenes_ico],
                        append_images=imagenes_ico[1:],
                    )
                else:
                    img = img_original.convert("RGB") if fmt in ("JPG", "WebP") \
                          else img_original
                    kwargs = {}
                    if fmt in ("JPG", "WebP"):
                        kwargs["quality"] = calidad
                    if fmt == "PNG":
                        kwargs["optimize"] = True
                    img.save(nombre_salida, pil_fmt, **kwargs)

            except Exception as e:
                errores.append(f"{Path(ruta).name}: {e}")

            progreso = (i / total) * 100
            self.after(0, self.progreso_var.set, progreso)
            self.after(0, self.lbl_estado.config,
                       {"text": f"Convirtiendo… {i}/{total}", "fg": ACCENT2})

        # Finalizado
        self.after(0, self._fin_conversion, errores, total)

    def _fin_conversion(self, errores, total):
        self.btn_convertir.configure(state="normal")
        if errores:
            msg = f"Completado con {len(errores)} error(es):\n\n" + "\n".join(errores)
            messagebox.showwarning("Conversión incompleta", msg)
            self.lbl_estado.config(text=f"Completado con errores.", fg=ACCENT)
        else:
            self.lbl_estado.config(
                text=f"✓ {total} imagen(es) convertidas con éxito.", fg=SUCCESS)
            messagebox.showinfo("¡Listo!",
                                f"Se convirtieron {total} imagen(es) correctamente.")


# ── Entrada ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    app = ConversorApp()
    app.mainloop()