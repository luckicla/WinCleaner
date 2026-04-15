# WinClean v1.2 — Optimizador Windows 10

Herramienta para eliminar bloatware, desactivar servicios innecesarios y aplicar tweaks de privacidad/rendimiento en Windows 10.

## Requisitos

- Windows 10 (x64)
- Python 3.10+
- Dependencias: `pip install pystray pillow`

## Instalación

```bat
pip install pystray pillow
python main.py
```

## Uso

Ejecutar `main.py` o doble click en `ejecutar.bat`. Requiere permisos de administrador (se solicita automáticamente).

## Cambios v1.2

### Bugs corregidos

**TclError: bad window path name** (crash principal)
- Causa: `var.trace_add("write", lambda *a: self._on_toggle())` disparaba el callback DESPUÉS de que los widgets eran destruidos durante un `_refresh_app_cards()` o `_refresh_service_cards()`.
- Solución: Cada `ItemCard` y `ServiceCard` ahora almacena el ID del trace y lo elimina en el evento `<Destroy>`. Además, `_safe_set_bg` verifica `winfo_exists()` antes de tocar cualquier widget.

**Scroll afectaba todos los tabs a la vez**
- Causa: `canvas.bind_all("<MouseWheel>", ...)` registraba el handler globalmente, haciendo que el scroll moviese todos los canvas simultáneamente.
- Solución: Cada canvas ahora usa `bind("<Enter>")` / `bind("<Leave>")` para activar/desactivar su propio handler de scroll solo cuando el ratón está sobre él.

**Cerrar ventana cerraba la aplicación**
- Solución: `protocol("WM_DELETE_WINDOW", self._on_close)` captura el cierre y hace `withdraw()` (oculta la ventana). Si `pystray` y `pillow` están instalados, crea un icono en la bandeja del sistema con menú "Abrir" / "Salir".

## Arquitectura

```
winclean/
  main.py              — Punto de entrada (GUI o tray)
  ejecutar.bat         — Lanzador con elevación UAC
  core/
    data.py            — Listas de apps, servicios y tweaks
    executor.py        — Ejecución real (PowerShell, sc.exe, registro)
    profiles.py        — Carga/guarda perfiles JSON
  ui/
    app.py             — Ventana principal
    widgets.py         — ItemCard, ServiceCard, StatusBar
    styles.py          — Colores y fuentes
    tray.py            — Modo bandeja (inicio silencioso con perfil)
```
