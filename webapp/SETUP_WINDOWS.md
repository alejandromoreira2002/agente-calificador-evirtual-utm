# Calificador Moodle — Instalación en Windows

Guía para correr el sistema en una PC con Windows.

## Requisitos

| Requisito | Detalle |
|---|---|
| **Windows** | 10 u 11 |
| **Python** | 3.10 o superior ([descargar](https://www.python.org/downloads/)) — **marca "Add Python to PATH"** al instalar |
| **7-Zip** (opcional) | Solo si los estudiantes suben entregas en `.rar`. Windows 10+ ya trae `tar.exe`, así que puede que no lo necesites |
| **Internet** | Para la API de Moodle y la del agente IA (DeepSeek) |

## Paso 1 — Copiar la carpeta

Copia **toda la carpeta del proyecto** (la que contiene `api.py`, `.env.example` y la subcarpeta `webapp/`) a la PC Windows. Por ejemplo:

```
C:\CalificadorMoodle\
    ├── api.py
    ├── config.json
    ├── .env.example
    ├── .env              ← lo crearás en el paso 3
    └── webapp\
        ├── app.py
        ├── grader.py
        ├── run.bat
        ├── requirements.txt
        ├── rubrics\
        ├── static\
        └── templates\
```

> ⚠️ **No copies** la carpeta `venv/` (es del Mac y no sirve en Windows). El `run.bat` la crea sola. Tampoco copies `cache/` ni `__pycache__/` (no hacen falta).

## Paso 2 — Configurar el sitio Moodle

El archivo `config.json` (junto a `api.py`) solo indica el sitio:

```json
{
  "site": "https://evirtual.utm.edu.ec"
}
```

También puedes omitirlo y definir `MOODLE_SITE` en el `.env` (tiene prioridad).

> Ya **no se guarda ningún token aquí**: el token se obtiene al iniciar sesión en la web y vive dentro de la cookie de sesión. Al cerrar sesión, desaparece.

## Paso 3 — Configurar las credenciales (`.env`)

Copia `.env.example` como `.env` (**en la raíz del proyecto**, junto a `api.py`) y rellena los valores:

```
MOODLE_SITE=https://evirtual.utm.edu.ec
GRADER_MODEL=deepseek-v4-flash
SECRET_KEY=una_clave_aleatoria_larga
```

Puedes generar la `SECRET_KEY` con:

```
python -c "import secrets; print(secrets.token_hex(32))"
```

> 🔒 El `.env` contiene credenciales: **no lo compartas ni lo subas a GitHub** (ya está en `.gitignore`).
> Como alternativa, la app también lee `%USERPROFILE%\.hermes\.env`.

## Paso 4 — Ejecutar

Doble clic en **`webapp\run.bat`**.

La primera vez creará el entorno virtual e instalará las dependencias (1-2 minutos). Luego arrancará el servidor y verás:

```
 * Running on http://0.0.0.0:5050
```

Abre el navegador en:

```
http://localhost:5050/
```

E inicia sesión con tu usuario y contraseña del Aula Evirtual.

## Acceso desde otras PC de la red

El servidor escucha en `0.0.0.0`, así que otros equipos pueden entrar con la **IP de la PC Windows**:

1. Averigua la IP: abre `cmd` y ejecuta `ipconfig` → busca "Dirección IPv4" (ej. `192.168.1.25`).
2. Desde otra PC (misma red): `http://192.168.1.25:5050/`

La **primera vez** Windows preguntará si permites el acceso al firewall → acepta para redes **privadas**.

## Notas y solución de problemas

- **"python no se reconoce como comando"** → reinstala Python marcando *Add Python to PATH*.
- **Entregas `.rar` no se leen** → instala [7-Zip](https://www.7-zip.org/) (agrega el comando `7z` al PATH). Nota: Windows 10+ incluye `tar.exe`, que muchas veces ya sirve.
- **El puerto 5050 está ocupado** → define `PORT=5051` en el `.env` (o agrega `set PORT=5051` en `run.bat`).
- **El firewall bloquea el acceso desde otras PC** → permite el puerto 5050 en el Firewall de Windows para redes privadas.
- **"No autenticado" o hay que volver a entrar** → si cambiaste `SECRET_KEY` en el `.env`, las sesiones abiertas se invalidan; vuelve a iniciar sesión.
- **El agente tarda o marca algún error** → el proveedor del modelo encola respuestas; la app reintenta y continúa con el resto. Vuelve a calificar solo los que quedaron en error.

## Diferencias respecto al Mac

| Aspecto | Mac | Windows |
|---|---|---|
| Lanzador | `run.sh` | `run.bat` |
| Extracción `.rar` | `bsdtar` (incluido) | `tar.exe` (Windows 10+) o 7-Zip |
| Entorno virtual | `venv/bin/` | `venv\Scripts\` |
| Nombre fijo `.local` | Bonjour (`mac.local`) | No aplica; usar la IP |
