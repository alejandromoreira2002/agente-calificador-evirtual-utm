# 🎓 Calificador Moodle

Aplicación web que **califica automáticamente las tareas de Moodle con un agente de IA**, mostrando la nota propuesta, el desglose por criterio y la justificación **antes** de escribir nada en el aula virtual.

Pensada para docentes que **no tienen acceso de administrador** al Moodle institucional: funciona con la **API REST nativa** (servicio `moodle_mobile_app`), sin instalar ningún plugin.

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
| **Python** | 3.10 o superior |
| **Moodle** | Con servicios web activados y el servicio `moodle_mobile_app` habilitado |
| **Rol** | Docente del curso (no se necesita administrador) |
| **API de IA** | Una clave de [DeepSeek](https://platform.deepseek.com/) (o cualquier endpoint compatible con la API de OpenAI) |

---

## 🚀 Instalación

```bash
git clone https://github.com/TU_USUARIO/calificador-moodle.git
cd calificador-moodle/webapp
chmod +x run.sh
./run.sh
```

Abre **http://localhost:5050/** en el navegador.

`run.sh` crea el entorno virtual e instala las dependencias la primera vez.

<details>
<summary>Instalación manual (paso a paso)</summary>

```bash
cd webapp
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python app.py
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
├── README.md
└── webapp/
    ├── app.py              # Backend Flask (endpoints, trabajos de calificación)
    ├── grader.py           # Motor de calificación (extracción de texto + LLM)
    ├── run.sh / run.bat    # Lanzadores macOS-Linux / Windows
    ├── requirements.txt
    ├── SETUP_WINDOWS.md    # Guía de instalación en Windows
    ├── rubrics/            # Rúbricas en JSON
    ├── static/             # app.js · style.css
    ├── templates/          # index.html
    ├── cache/              # Entregas descargadas ⚠️ no se sube
    └── venv/               # Entorno virtual ⚠️ no se sube
```

---

## 🪟 Windows

Consulta **[webapp/SETUP_WINDOWS.md](webapp/SETUP_WINDOWS.md)**. En resumen: instala Python 3.10+ marcando *«Add Python to PATH»*, copia la carpeta del proyecto, crea el `.env` a partir de `.env.example` y haz doble clic en `run.bat`.

---

## 🛠️ Problemas comunes

| Síntoma | Causa y solución |
|---|---|
| No aparecen cursos | El usuario no es docente de ningún curso, o el `MOODLE_SITE` es incorrecto |
| «Credenciales inválidas» al entrar | Usa tu usuario de Moodle, no el correo, o el servicio `moodle_mobile_app` está deshabilitado |
| El agente tarda y marca algún error | El proveedor del modelo encola respuestas. La app reintenta y continúa; vuelve a calificar solo los marcados |
| Una entrega sale con nota 0.0 | El archivo es una imagen o un escaneo manuscrito: el agente solo trabaja con texto |
| `Permission denied: ./run.sh` | Ejecuta `chmod +x run.sh` |

---

## 📄 Licencia

Sin licencia definida todavía. Si vas a publicarlo, añade un archivo `LICENSE` (por ejemplo, MIT).

---

## ⚠️ Aviso

Herramienta de **apoyo** a la labor docente. La calificación sugerida por el agente **debe ser revisada** por el docente antes de publicarse: la responsabilidad académica de la nota es siempre humana.
