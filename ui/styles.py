"""
WinClean visual theme — Modern dark + blue accent
"""
import tkinter as tk
from tkinter import ttk

COLORS = {
    "bg":           "#1a1d23",
    "surface":      "#22252e",
    "surface2":     "#2a2d38",
    "border":       "#33374a",
    "accent":       "#4da6ff",
    "accent_hover": "#6ab8ff",
    "text":         "#e8eaf0",
    "text_muted":   "#7a8099",
    "success":      "#4caf80",
    "warning":      "#f5a623",
    "danger":       "#e05c5c",
    "btn":          "#2a2d38",
    "btn_hover":    "#343848",
}

FONTS = {
    "title":    ("Segoe UI", 14, "bold"),
    "subtitle": ("Segoe UI", 10),
    "body":     ("Segoe UI", 10),
    "small":    ("Segoe UI", 9),
    "label":    ("Segoe UI", 8, "bold"),
    "button":   ("Segoe UI", 10, "bold"),
    "mono":     ("Consolas", 9),
}


def apply_theme(root: tk.Tk):
    style = ttk.Style(root)
    style.theme_use("clam")

    style.configure("TScrollbar",
                    background=COLORS["surface2"],
                    troughcolor=COLORS["bg"],
                    arrowcolor=COLORS["text_muted"],
                    borderwidth=0,
                    relief="flat")

    style.configure("TNotebook",
                    background=COLORS["bg"],
                    borderwidth=0)

    style.configure("TNotebook.Tab",
                    background=COLORS["surface"],
                    foreground=COLORS["text_muted"],
                    padding=[14, 8])

    style.map("TNotebook.Tab",
              background=[("selected", COLORS["bg"])],
              foreground=[("selected", COLORS["accent"])])
