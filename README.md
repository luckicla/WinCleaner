# WinClean v1.4 — Optimizador Windows 10 y 11

Herramienta para eliminar bloatware, desactivar servicios innecesarios y aplicar tweaks de privacidad/rendimiento en Windows 10.

## Requisitos

- Windows 10 (x64)
- Windows 11
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

## Cambios v1.4

He añadido funciones exclusivas para Windows 11 para retirar todo el contenido posible relacionado con la IA. He arreglado errores de reconocimiento de servicios y apps. He mejorado el rendimiento de la aplicación reduciendo el consumo de recursos en segundo plano y eso, poco más.

Tengo varias mejoras pensadas para las siguientes versiones. btw, el código pasa por una IA para optimizarse porque yo aún no sé hacerlo, y además lo ordena muchísimo mejor que yo, que soy una patata xD

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
