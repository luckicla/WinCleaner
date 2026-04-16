# WinClean v2.0 — Optimizador Windows 10/11

> Limpia. Optimiza. Tú decides qué se queda.

Herramienta de limpieza y optimización para Windows 10 y 11. Elimina bloatware, desactiva servicios innecesarios, aplica tweaks de privacidad y rendimiento, y en Windows 11 cuenta con un módulo específico para retirar toda la integración de IA del sistema.

> ⚠️ Requiere permisos de administrador. Se solicitan automáticamente al iniciar.

---

## ¿Qué hace WinClean?

Windows viene con decenas de aplicaciones, servicios y configuraciones que nunca pediste y que consumen recursos, recopilan datos y llenan tu escritorio de ruido. WinClean te da el control: ves exactamente qué hay, qué está activo, y puedes desactivarlo o eliminarlo con un clic — con indicación del nivel de riesgo de cada acción.

No hay cajas negras. Todo lo que hace la herramienta es ejecutar comandos de PowerShell o modificaciones de registro estándar, los mismos que harías a mano.

---

## Características

- **36 aplicaciones bloatware** detectables y eliminables (Teams, Cortana, Xbox, Candy Crush, apps Bing, Copilot, Clipchamp, etc.)
- **27 servicios de Windows** configurables: desactivar, bloquear o restaurar con un clic
- **27 tweaks** de privacidad, rendimiento y gaming — con lectura del estado real del sistema antes de mostrarse
- **Detección automática de Windows 10 vs 11** — las secciones exclusivas de W11 solo aparecen si corresponde
- **Perfiles predefinidos** (Gaming, Trabajo, Mínimo) y perfiles de usuario personalizables en JSON
- **Modo bandeja del sistema** — se minimiza a la bandeja en lugar de cerrarse
- **Inicio automático con perfil** — puede aplicar un perfil silenciosamente al arrancar Windows
- **Selector de plan de energía** con detección de portátil
- **Límites de recursos por proceso** — control manual de CPU/memoria por aplicación

---

## Tweaks disponibles

### Privacidad
Telemetría · Cortana · Historial de Actividad · ID de Publicidad · Rastreo de Ubicación · Solicitudes de Feedback · Notificaciones del sistema · Informes de Error · Asistencia Remota · Noticias e Intereses · Búsquedas Destacadas

### Rendimiento
Sonido de inicio · Efectos visuales · Reproducción Automática · Hibernación

### Gaming
Modo Juego · GPU Scheduling (HAGS) · Resolución de Timer del Sistema · Throttling de Red

### Windows 11 — Anti-IA *(exclusivos W11)*
Botón Copilot · Windows Recall · Búsqueda con IA · Panel de Widgets · Snap Layout · Typing Insights · Experiencias personalizadas · Escritura por voz

---

## Perfiles predefinidos

| Perfil | Descripción |
|---|---|
| 🎮 Gaming | Máximo rendimiento. Desactiva servicios innecesarios, telemetría y optimiza para juegos |
| 💼 Trabajo | Elimina bloatware y telemetría manteniendo estabilidad y funciones útiles |
| 🧹 Mínimo | Solo elimina el bloatware más evidente. Cambios conservadores para cualquier usuario |

Los perfiles de usuario se guardan en `%USERPROFILE%\.winclean\profiles\` como JSON y se pueden importar/exportar.

---

## Requisitos

- Windows 10 u 11 (x64)
- Python 3.10 o superior
- `pip install pystray pillow`

---

## Instalación y uso

```bat
pip install pystray pillow
python main.py
```

O doble clic en `ejecutar.bat` (eleva UAC automáticamente).

### Modo bandeja (inicio silencioso)

```bat
python main.py --tray
```

Aplica el perfil de inicio guardado sin abrir la ventana y se queda en la bandeja del sistema.

---

## Arquitectura

```
winclean/
  main.py                — Punto de entrada (GUI o --tray)
  ejecutar.bat           — Lanzador con elevación UAC
  build.bat              — Script de compilación a .exe
  WinClean.spec          — Configuración PyInstaller
  version_info.txt       — Metadatos del EXE
  core/
    data.py              — Listas de apps, servicios, tweaks y perfiles preset
    executor.py          — Ejecución real (PowerShell, sc.exe, registro de Windows)
    profiles.py          — Carga/guarda/importa/exporta perfiles JSON
    resource_manager.py  — Límites de recursos por proceso
  ui/
    app.py               — Ventana principal
    widgets.py           — ItemCard, ServiceCard, TweakCard, ProcessResourceCard, StatusBar
    styles.py            — Colores y fuentes
    tray.py              — Modo bandeja (inicio silencioso con perfil)
```

---

## Historial de cambios

### v2.0
- **Fix crítico:** `AttributeError: '_tkinter.tkapp' object has no attribute '_tweak_cards'` — el diccionario `_tweak_cards` no se inicializaba en `__init__`, causando un crash al arrancar en Windows 11

### v1.4
- Nuevas funciones exclusivas para Windows 11: eliminación de toda la integración de IA (Copilot, Recall, búsqueda IA, Widgets, Snap Layout, Typing Insights, experiencias personalizadas, escritura por voz)
- Corrección de errores de reconocimiento de servicios y apps
- Mejora del rendimiento en segundo plano
- Añadidos archivos de compilación a EXE standalone (`build.bat`, `WinClean.spec`, `EMPAQUETAR.md`)

### v1.2
- **Fix:** `TclError: bad window path name` — los callbacks de `trace_add` se disparaban tras destruir widgets
- **Fix:** El scroll afectaba todos los tabs a la vez — cada canvas usa `bind("<Enter>")` / `bind("<Leave>")` para activar su handler solo cuando el ratón está encima
- **Fix:** Cerrar la ventana cerraba la aplicación — ahora `WM_DELETE_WINDOW` hace `withdraw()` y crea icono en bandeja

---

## Notas

Proyecto iniciado el 13/04/2026. El código ha sido reorganizado y optimizado con ayuda de IA (Claude). Cualquier PR o sugerencia es bienvenida.
