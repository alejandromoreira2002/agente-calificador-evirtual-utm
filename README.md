# 🎓 Calificador Moodle

Aplicación web que **califica automáticamente las tareas de Moodle con un agente de IA**, mostrando la nota propuesta, el desglose por criterio y la justificación **antes** de escribir nada en el aula virtual.

Pensada para docentes que **no tienen acceso de administrador** al Moodle institucional: funciona con la **API REST nativa** (servicio `moodle_mobile_app`), sin instalar ningún plugin.

> 📚 **¿Quieres entender cómo funciona por dentro?** Consulta **[DOCUMENTACION.md](DOCUMENTACION.md)**: arquitectura, flujo de datos, integración con Moodle y con el modelo de IA, modelo de datos, decisiones de diseño y limitaciones.

---

## ✨ Características

**Navegación**
- Login con el **usuario y contraseña de Moodle** — cada docente entra con su propia cuenta.
- Cursos y tareas **agrupados por unidades/secciones** (como en el aula virtual).
- Badge azul de avance por tarea (`calificados / entregas`).

**Calificación con IA**
- **Selección de estudiantes**: marca individualmente, en bloque o a todos. No siempre se califica a todo el curso.
- Descarga automática de las entregas y **extracción de texto**: PDF, DOCX, TXT, código fuente, ZIP y RAR.
- La **consigna enviada al agente** incluye la descripción de la tarea **y los archivos adjuntos** que subió el docente (guías, enunciados).
- **Rúbricas**: modo simple (criterios + puntos) o **por niveles** (p. ej. Excelente / Satisfactorio / Insuficiente, donde la IA elige el nivel).
- Gestión de rúbricas desde la interfaz: crear, editar, borrar e **importar desde Excel/CSV**.

**Control antes de publicar**
- **Previsualización** con nota, criterios evaluados, justificación y retroalimentación sugerida.
- Edición manual de la nota y del comentario.
- Descarga de las entregas originales para revisarlas.
- **Publicación selectiva**: elige qué estudiantes se registran en Moodle.

**Robustez**
- Progreso en vivo: `3/9 procesadas · ahora: Nombre Apellido`.
- **Reintentos automáticos** y segunda pasada para los que fallan por cuelgues transitorios del proveedor del modelo.
- Si un estudiante no se puede calificar, queda marcado como error y el resto continúa.

---

## 🧩 Requisitos

| Requisito | Detalle |
|---|---|
| **Sistema operativo** | Linux, macOS o Windows |
| **Python** | 3.10 o superior |
| **Moodle** | Con servicios web activados y el servicio `moodle_mobile_app` habilitado |
| **Rol** | Docente del curso (no se necesita administrador) |
| **API de IA** | Una clave de [DeepSeek](https://platform.deepseek.com/) (o cualquier endpoint compatible con la API de OpenAI) |

---

## 🚀 Instalación

Elige tu sistema operativo. En los tres casos terminas con la app en **http://localhost:5050/**.

**Antes de empezar necesitas:** Python 3.10+, Git y una clave de API del modelo (ver [Configuración](#️-configuración)).

### 🐧 Linux

<details open>
<summary><b>Debian / Ubuntu / Mint</b></summary>

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git

git clone https://github.com/TU_USUARIO/calificador-moodle.git
cd calificador-moodle

cp .env.example .env
nano .env            # rellena DEEPSEEK_API_KEY, MOODLE_SITE y SECRET_KEY

cd webapp
chmod +x run.sh
./run.sh
```
</details>

<details>
<summary><b>Fedora / RHEL / CentOS</b></summary>

```bash
sudo dnf install -y python3 python3-pip git

git clone https://github.com/TU_USUARIO/calificador-moodle.git
cd calificador-moodle

cp .env.example .env && nano .env

cd webapp && chmod +x run.sh && ./run.sh
```
</details>

<details>
<summary><b>Arch / Manjaro</b></summary>

```bash
sudo pacman -S --needed python python-pip git

git clone https://github.com/TU_USUARIO/calificador-moodle.git
cd calificador-moodle

cp .env.example .env && nano .env

cd webapp && chmod +x run.sh && ./run.sh
```
</details>

**Extras útiles en Linux**

| Tema | Comando |
|---|---|
| Leer entregas `.rar` | `sudo apt install unrar p7zip-full` (o `unar`) |
| Abrir el puerto a la red local | `sudo ufw allow 5050/tcp` |
| Ver tu IP local | `hostname -I` |

**Opcional — dejarlo corriendo como servicio (systemd)**

```ini
# /etc/systemd/system/calificador-moodle.service
[Unit]
Description=Calificador Moodle
After=network.target

[Service]
User=TU_USUARIO
WorkingDirectory=/opt/calificador-moodle/webapp
ExecStart=/opt/calificador-moodle/webapp/venv/bin/python app.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now calificador-moodle
```

### 🍎 macOS

```bash
# 1. Python 3.10+ (si no lo tienes)
brew install python          # o descárgalo de https://www.python.org/downloads/

# 2. Clonar
git clone https://github.com/TU_USUARIO/calificador-moodle.git
cd calificador-moodle

# 3. Credenciales
cp .env.example .env
open -e .env                 # rellena DEEPSEEK_API_KEY, MOODLE_SITE y SECRET_KEY

# 4. Arrancar
cd webapp
chmod +x run.sh
./run.sh
```

- La primera vez macOS pregunta si permites **conexiones entrantes** → *Permitir* (solo si quieres usarlo desde otra PC).
- Para `.rar` no hace falta nada extra: macOS ya incluye `bsdtar`.
- Ver tu IP local: `ipconfig getifaddr en0`

### 🪟 Windows

Necesitas **Python 3.10+** desde [python.org](https://www.python.org/downloads/) marcando la casilla **«Add Python to PATH»**.

```bat
:: 1. Clonar (o descargar el ZIP del repositorio y descomprimirlo)
git clone https://github.com/TU_USUARIO/calificador-moodle.git
cd calificador-moodle

:: 2. Credenciales
copy .env.example .env
notepad .env

:: 3. Arrancar (o simplemente doble clic en run.bat)
cd webapp
run.bat
```

- La primera vez Windows preguntará por el **firewall** → permitir en redes **privadas**.
- Para leer `.rar` instala [7-Zip](https://www.7-zip.org/) (Windows 10+ ya trae `tar.exe`, que suele bastar).
- Ver tu IP local: `ipconfig` → «Dirección IPv4».
- Guía detallada: **[webapp/SETUP_WINDOWS.md](webapp/SETUP_WINDOWS.md)**.

### 📦 Instalación manual (cualquier sistema)

<details>
<summary>Si prefieres no usar los lanzadores</summary>

```bash
cd webapp
python3 -m venv venv
venv/bin/pip install -r requirements.txt    # Windows: venv\Scripts\pip.exe install -r requirements.txt
venv/bin/python app.py                      # Windows: venv\Scripts\python.exe app.py
```
</details>

---

## ⚙️ Configuración

Toda credencial vive en un archivo **`.env`** en la raíz del proyecto. Ese archivo **está en `.gitignore` y nunca debe subirse**.

```bash
cp .env.example .env
# edita .env con tus valores
```

| Variable | Obligatoria | Descripción |
|---|---|---|
| `DEEPSEEK_API_KEY` | ✅ | Clave del modelo que califica |
| `DEEPSEEK_BASE_URL` | — | Endpoint del proveedor (por defecto `https://api.deepseek.com/v1`) |
| `GRADER_MODEL` | — | Modelo a usar (por defecto `deepseek-v4-flash`) |
| `MOODLE_SITE` | ✅ | URL del Moodle, p. ej. `https://moodle.miuniversidad.edu` |
| `SECRET_KEY` | ✅ | Clave de firma de las sesiones web. Genera una con `python3 -c "import secrets; print(secrets.token_hex(32))"` |
| `HOST` | — | `0.0.0.0` para acceder desde la red local (por defecto), `127.0.0.1` solo local |
| `PORT` | — | Puerto del servidor (por defecto `5050`) |

> El **token de Moodle** no se guarda en disco: se obtiene al iniciar sesión y viaja dentro de la cookie de sesión firmada. Al cerrar sesión desaparece.

---

## 🌐 Acceso desde otras PC de la red local

Con `HOST=0.0.0.0` (valor por defecto) el servidor es accesible desde cualquier equipo de la misma red Wi-Fi/LAN. Al arrancar, el lanzador te muestra la dirección:

```
Iniciando el Calificador Moodle…
  (en la red local: http://192.168.1.25:5050/)
```

| Sistema | Cómo ver tu IP local |
|---|---|
| 🐧 Linux | `hostname -I` |
| 🍎 macOS | `ipconfig getifaddr en0` |
| 🪟 Windows | `ipconfig` → «Dirección IPv4» |

Desde el otro equipo, abre `http://<esa-IP>:5050/`.

Si no carga, revisa: **(1)** que estén en la misma red, **(2)** el firewall, y **(3)** que la red Wi-Fi no tenga activado el «aislamiento de clientes».

| Sistema | Abrir el puerto 5050 |
|---|---|
| 🐧 Linux | `sudo ufw allow 5050/tcp` |
| 🍎 macOS | Ajustes → Red → Firewall → permitir la conexión entrante |
| 🪟 Windows | Aceptar el aviso del firewall para redes **privadas** |

> Si solo lo usarás en tu propio equipo, pon `HOST=127.0.0.1` en el `.env` y no quedará expuesto a la red.

---

## 📖 Uso

1. **Inicia sesión** con tu usuario y contraseña de Moodle.
2. Elige un **curso** y luego una **tarea**.
3. Revisa la lista de entregas y **marca los estudiantes** que quieras calificar.
4. Selecciona o crea una **rúbrica**.
5. Pulsa **🤖 Calificar con agente**.
6. Revisa la **previsualización**: nota, criterios, justificación y retroalimentación. Ajusta lo que quieras.
7. Marca los estudiantes a publicar y pulsa **Publicar en Moodle**.

> ⚠️ **Publicar escribe notas reales en el aula virtual.** Haz una primera prueba con un solo estudiante antes de publicar todo el curso.

---

## 📊 Rúbricas

Se guardan como JSON en `webapp/rubrics/` y también se pueden crear desde la interfaz.

**Formato A — simple**

| Criterio | Descripción | Puntos |
|---|---|---|
| Introducción | Presenta el tema y los objetivos | 2 |
| Desarrollo | Argumenta y ejemplifica | 5 |
| Conclusiones | Sintetiza los hallazgos | 3 |

**Formato B — por niveles** (matriz criterios × niveles)

| Criterio | Excelente 100% | Satisfactorio 50% | Insuficiente 0% | Pts |
|---|---|---|---|---|
| Introducción | Clara y completa | Parcial | Ausente | 0.3 |
| Aplicaciones | 3+ ejemplos propios | 1-2 ejemplos | Sin ejemplos | 0.8 |

Los porcentajes son opcionales: si se omiten, se reparten automáticamente (100% / 50% / 0% para tres niveles). La columna de puntos también es opcional (si falta, todos los criterios pesan igual).

Se pueden **importar desde Excel/CSV** con el botón correspondiente: los nombres de columna son flexibles (no importan acentos ni mayúsculas).

La nota final se escala a la nota máxima de la tarea:

```
nota = (puntaje obtenido / puntaje total de la rúbrica) × nota máxima de la tarea
```

---

## 🔒 Seguridad y privacidad

**Qué se envía al modelo de IA** (y qué no):

Se envían a la API del proveedor: el **nombre completo del estudiante**, el **texto de su entrega** (hasta 30.000 caracteres) y la consigna + rúbrica. **No** se envían calificaciones previas, correos, ni credenciales de Moodle.

**Qué no se sube al repositorio** (ver `.gitignore`):

- `.env` y `secret_key` — credenciales.
- `submissions/` y `webapp/cache/` — **entregas reales de estudiantes**.
- `report_*.md` — reportes con nombres y notas.

Si vas a publicar este proyecto, revisa tu `.env` y tu historial de Git antes de hacer el primer *push*.

---

## 📁 Estructura del proyecto

```
.
├── api.py                  # Cliente de la API REST de Moodle
├── config.json             # URL del sitio (alternativa a MOODLE_SITE)
├── .env                    # Credenciales ⚠️ NO se sube (creado desde .env.example)
├── .env.example            # Plantilla de credenciales
├── .gitignore
├── .gitattributes          # Finales de línea consistentes entre Windows/Linux/macOS
├── LICENSE                 # MIT
├── README.md               # Guía de instalación y uso
├── DOCUMENTACION.md        # Documentación técnica en profundidad
└── webapp/
    ├── app.py              # Backend Flask (endpoints, trabajos de calificación)
    ├── grader.py           # Motor de calificación (extracción de texto + LLM)
    ├── run.sh              # Lanzador para Linux y macOS
    ├── run.bat             # Lanzador para Windows
    ├── requirements.txt
    ├── SETUP_WINDOWS.md    # Guía detallada de instalación en Windows
    ├── README.md           # Nota breve sobre esta carpeta
    ├── rubrics/            # Rúbricas en JSON
    ├── static/             # app.js · style.css
    ├── templates/          # index.html
    ├── cache/              # Entregas descargadas ⚠️ no se sube
    └── venv/               # Entorno virtual ⚠️ no se sube
```

---

## 🛠️ Problemas comunes

| Síntoma | Causa y solución |
|---|---|
| No aparecen cursos | El usuario no es docente de ningún curso, o el `MOODLE_SITE` es incorrecto |
| «Credenciales inválidas» al entrar | Usa tu usuario de Moodle (no el correo), o el servicio `moodle_mobile_app` está deshabilitado en ese Moodle |
| El agente tarda y marca algún error | El proveedor del modelo encola respuestas. La app reintenta automáticamente y continúa; vuelve a calificar solo los que quedaron en error |
| Una entrega sale con nota 0.0 | El archivo es una imagen o un escaneo manuscrito: el agente solo trabaja con texto |
| `Permission denied: ./run.sh` | Ejecuta `chmod +x run.sh` |
| Falla `python3 -m venv` / «No module named venv» | Falta el paquete: `sudo apt install python3-venv` (Debian/Ubuntu) |
| «python no se reconoce como comando» | Reinstala Python marcando *Add Python to PATH* (Windows) |
| El puerto 5050 está ocupado | Define `PORT=5051` en el `.env` |
| No carga desde otra PC | Revisa firewall y red → [Acceso desde la red local](#-acceso-desde-otras-pc-de-la-red-local) |
| Hay que volver a iniciar sesión | Cambiaste `SECRET_KEY` en el `.env`: las sesiones abiertas se invalidan |
| Las entregas `.rar` no se leen | Linux: `sudo apt install unrar p7zip-full` · Windows: instala [7-Zip](https://www.7-zip.org/) |

---

## 📄 Licencia

Distribuido bajo la licencia **MIT** — consulta el archivo [LICENSE](LICENSE). Puedes usarlo, modificarlo y redistribuirlo citando la autoría.

---

## ⚠️ Aviso

Herramienta de **apoyo** a la labor docente. La calificación sugerida por el agente **debe ser revisada** por el docente antes de publicarse: la responsabilidad académica de la nota es siempre humana.
