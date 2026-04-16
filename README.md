# WinClean v1.4 — Optimizador Windows 10/11

Herramienta de limpieza y optimización para Windows 10 y 11. Elimina bloatware, desactiva servicios innecesarios, aplica tweaks de privacidad y rendimiento, y en Windows 11 cuenta con funciones específicas para retirar toda la integración de IA del sistema.

> ⚠️ Requiere permisos de administrador. Se solicitan automáticamente al iniciar.

---

## Características principales

- **36 aplicaciones bloatware** detectables y eliminables (Teams, Cortana, Xbox, Candy Crush, apps Bing, etc.)
- **27 servicios de Windows** configurables (desactivar, bloquear o restaurar)
- **27 tweaks** de privacidad, rendimiento y gaming, con lectura del estado real del sistema antes de mostrarlos
- **Detección automática de Windows 10 vs 11** — las secciones exclusivas de W11 solo aparecen en W11
- **Perfiles predefinidos** (Gaming, Trabajo, Mínimo) y perfiles de usuario personalizables
- **Modo bandeja del sistema** — se minimiza a la bandeja en lugar de cerrarse, con menú Abrir/Salir
- **Inicio automático con perfil** — puede aplicar un perfil silenciosamente al arrancar Windows
- **Selector de plan de energía** — Ahorro de batería / Equilibrado / Alto rendimiento (con detección de portátil)
- **Límites de recursos por proceso** — control manual

---

## Tweaks disponibles

### Privacidad
- Telemetría de Windows
- Cortana en búsquedas
- Historial de Actividad
- ID de Publicidad
- Rastreo de Ubicación
- Solicitudes de Feedback
- Notificaciones del sistema
- Informes de Error de Windows
- Asistencia Remota
- Noticias e Intereses (barra de tareas)
- Búsquedas Destacadas

### Rendimiento
- Sonido de inicio de Windows
- Efectos visuales
- Reproducción Automática
- Hibernación

### Gaming
- Modo Juego
- GPU Scheduling (HAGS)
- Resolución de Timer del Sistema
- Throttling de Red para Juegos

### Windows 11 — Anti-IA (exclusivos)
- Botón Copilot en barra de tareas
- Windows Recall
- Búsqueda con IA mejorada
- Panel de Widgets
- Sugerencias de Snap Layout
- Estadísticas de escritura (Typing Insights)
- Experiencias personalizadas con IA
- Escritura por voz

---

## Apps bloatware exclusivas de Windows 11

- Microsoft Copilot
- Clipchamp (Editor de vídeo con IA)
- Paint con Cocreator IA
- Dev Home
- Outlook nuevo (con Copilot)
- Vinculación con el Teléfono (Phone Link)

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
- Dependencias: `pip install pystray pillow`

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

### v1.4
- Nuevas funciones exclusivas para Windows 11: eliminación de toda la integración de IA (Copilot, Recall, búsqueda IA, Widgets, Snap Layout, Typing Insights, experiencias personalizadas, escritura por voz)
- Corrección de errores de reconocimiento de servicios y apps
- Mejora del rendimiento en segundo plano (reducción de consumo de recursos)
- Añadidos archivos de compilación a EXE standalone (`build.bat`, `WinClean.spec`, `EMPAQUETAR.md`)

### v1.2
- **Fix:** `TclError: bad window path name` — los callbacks de `trace_add` se disparaban tras destruir widgets. Solución: cada `ItemCard` y `ServiceCard` guarda el ID del trace y lo elimina en `<Destroy>`. `_safe_set_bg` verifica `winfo_exists()` antes de tocar widgets.
- **Fix:** El scroll afectaba todos los tabs a la vez — `canvas.bind_all("<MouseWheel>")` registraba el handler globalmente. Solución: cada canvas usa `bind("<Enter>")` / `bind("<Leave>")` para activar su propio handler solo cuando el ratón está encima.
- **Fix:** Cerrar la ventana cerraba la aplicación — ahora `WM_DELETE_WINDOW` hace `withdraw()` (oculta la ventana) y crea un icono en la bandeja con menú Abrir/Salir si pystray y Pillow están disponibles.

---

## Notas

El código ha sido reorganizado y optimizado con ayuda de IA (Claude) para facilitar la lectura y contribuciones externas. El proyecto empezó el 13/04/2026 y tiene mucho margen de mejora — cualquier PR o sugerencia es bienvenida.
