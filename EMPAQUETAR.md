# 📦 Cómo generar WinClean.exe

## Herramienta elegida: **PyInstaller**

Es la opción más madura para Python + tkinter + Windows. Genera un `.exe` standalone que incluye Python embebido y todas las dependencias. No requiere instalación en el PC destino.

---

## Requisitos en tu PC de compilación

| Requisito | Notas |
|---|---|
| Windows 10 u 11 (64-bit) | El EXE generado es para Windows — compila en Windows |
| Python 3.11 (recomendado) | Desde https://python.org — marca "Add to PATH" |
| Conexión a internet | Solo para descargar PyInstaller y dependencias |

> ⚠️ El EXE debe compilarse **en Windows**. No funciona compilar desde Linux/Mac para Windows con esta configuración.

---

## Pasos para compilar

### Opción A — Automático (recomendada)

1. Copia toda la carpeta `winclean_v2/` a tu PC Windows
2. Doble-clic en **`build.bat`**
3. Espera 1-3 minutos
4. El resultado estará en `dist\WinClean.exe`

### Opción B — Manual

```bat
:: Desde la carpeta winclean_v2\ en CMD o PowerShell:

pip install pyinstaller pystray pillow
pyinstaller WinClean.spec --noconfirm
```

---

## Qué incluye el EXE generado

- ✅ Python 3.11 embebido (el usuario final NO necesita Python)
- ✅ tkinter (GUI nativa)
- ✅ pystray + Pillow (icono en bandeja del sistema)
- ✅ Todos los módulos del proyecto (core/, ui/)
- ✅ Solicitud de UAC automática al abrir (requireAdministrator)
- ✅ Sin ventana de consola negra
- ✅ Compresión UPX (si instalas UPX reduce ~30% el tamaño)

---

## Tamaño esperado del EXE

| Configuración | Tamaño aprox. |
|---|---|
| Sin UPX | ~25-35 MB |
| Con UPX instalado | ~18-25 MB |

---

## Añadir icono personalizado (opcional)

1. Crea o consigue un archivo `.ico` (puedes convertir PNG en https://icoconvert.com)
2. Guárdalo como `assets\winclean.ico`
3. El `build.bat` lo detectará automáticamente

---

## Añadir metadatos al EXE (versión, nombre, copyright)

El archivo `version_info.txt` incluido ya está configurado.
Para activarlo, edita `WinClean.spec` y cambia en `EXE()`:

```python
version=None,
# por:
version='version_info.txt',
```

---

## Solución de problemas frecuentes

### El EXE se abre y se cierra inmediatamente
Activa la consola temporalmente para ver el error:
- En `WinClean.spec`, cambia `console=False` → `console=True`
- Recompila y ejecuta desde CMD para ver el traceback

### Error "pystray no encontrado" o tray no funciona
```bat
pip install pystray pillow --force-reinstall
```

### Antivirus lo bloquea (falso positivo)
Normal con PyInstaller. Opciones:
1. Firma el EXE con un certificado de código (costoso)
2. Añade excepción en el antivirus
3. Usa `--key` en PyInstaller para cifrar el bytecode (reduce falsos positivos)

### Quiero que pese menos
Instala UPX: https://upx.github.io — coloca `upx.exe` en PATH y recompila.

---

## Estructura de archivos necesaria para compilar

```
winclean_v2/
├── main.py              ← punto de entrada
├── WinClean.spec        ← configuración PyInstaller  ← NUEVO
├── build.bat            ← script de compilación      ← NUEVO
├── version_info.txt     ← metadatos del EXE          ← NUEVO
├── assets/
│   └── winclean.ico     ← (opcional) icono
├── core/
│   ├── data.py
│   ├── executor.py
│   ├── profiles.py
│   └── resource_manager.py
└── ui/
    ├── app.py
    ├── widgets.py
    ├── styles.py
    └── tray.py
```

---

## Alternativas a PyInstaller (por si acaso)

| Herramienta | Pros | Contras |
|---|---|---|
| **PyInstaller** ✅ | Madura, amplio soporte tkinter | EXE grande |
| **Nuitka** | EXE más rápido y pequeño | Compilación más lenta, requiere compilador C |
| **cx_Freeze** | Alternativa sólida | Menos documentación |
| **py2exe** | Clásico | Solo Python 3.x reciente con fork |

Para este proyecto, **PyInstaller es la mejor opción** por su compatibilidad con tkinter y pystray.
