# 📚 Documentación técnica — Calificador Moodle (Aula Evirtual UTM)

Este documento explica **qué es el sistema, cómo funciona por dentro y por qué está construido así**. Está pensado para que cualquier persona con conocimientos técnicos pueda entenderlo a fondo partiendo de cero.

---

## Índice

1. [Qué es y qué problema resuelve](#1-qué-es-y-qué-problema-resuelve)
2. [Arquitectura general](#2-arquitectura-general)
3. [Flujo completo de una calificación](#3-flujo-completo-de-una-calificación)
4. [Componentes en detalle](#4-componentes-en-detalle)
5. [API interna (endpoints)](#5-api-interna-endpoints)
6. [Integración con Moodle](#6-integración-con-moodle)
7. [Integración con el modelo de IA](#7-integración-con-el-modelo-de-ia)
8. [Modelo de datos](#8-modelo-de-datos)
9. [Decisiones de diseño y problemas resueltos](#9-decisiones-de-diseño-y-problemas-resueltos)
10. [Seguridad y privacidad](#10-seguridad-y-privacidad)
11. [Estructura de archivos](#11-estructura-de-archivos)
12. [Despliegue y configuración](#12-despliegue-y-configuración)
13. [Limitaciones conocidas](#13-limitaciones-conocidas)
14. [Glosario](#14-glosario)

---

## 1. Qué es y qué problema resuelve

Es una **aplicación web local** que califica automáticamente tareas de Moodle usando un modelo de lenguaje (LLM), **sin instalar nada en el servidor de Moodle** y **sin exportar los datos a Excel**.

### El contexto que la origina

Un docente corrige decenas de entregas por tarea. El procedimiento habitual es abrir cada archivo, leerlo, compararlo mentalmente con la rúbrica, escribir la nota y el comentario, y repetirlo estudiante por estudiante. Es lento, cansado y tiende a volverse inconsistente hacia el final de la lista.

La solución obvia sería un plugin de Moodle, pero eso requiere **acceso de administrador**, que el docente normalmente no tiene. La segunda opción típica (descargar todo y calificar en Excel) rompe el flujo: hay que volver a Moodle a subir cada nota a mano.

### La propuesta del sistema

| Principio | Cómo se implementa |
|---|---|
| **No depender del administrador** | Se usa la **API REST nativa de Moodle** con el servicio `moodle_mobile_app`, que ya viene activado para la app móvil oficial |
| **Todo ocurre dentro de Moodle** | Las notas se escriben con `mod_assign_save_grade`; no hay archivos intermedios ni Excel |
| **El docente nunca pierde el control** | El agente **propone**; se previsualiza, se edita y recién entonces se publica, y solo para los estudiantes elegidos |
| **La IA no decide sola** | El modelo solo puntúa criterios. La conversión a nota final, el escalado y los topes los hace el código, de forma determinista |

> **Filosofía de diseño central:** el LLM es un *clasificador de criterios*, no un calculador de notas. Se le pide puntuar cada criterio de la rúbrica y se le prohíbe explícitamente calcular la nota final. Todo el cálculo numérico vive en Python, auditable y reproducible.

---

## 2. Arquitectura general

El sistema es un **monolito de tres capas** que corre en el equipo del docente (o en un servidor de la red local) y se comunica con dos servicios externos.

```
┌──────────────────────────────────────────────────────────────────────┐
│                        NAVEGADOR DEL DOCENTE                         │
│                                                                      │
│   index.html  +  style.css  +  app.js                                │
│   ─ login          ─ listado de cursos/tareas/secciones              │
│   ─ selector de rúbricas + modal CRUD + importar Excel               │
│   ─ checkboxes de estudiantes    ─ tabla de previsualización         │
│   ─ barra de progreso (polling cada 1,5 s)                           │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ HTTP + cookie de sesión firmada
                                │ (JSON)
┌───────────────────────────────▼──────────────────────────────────────┐
│                    SERVIDOR FLASK  (app.py)                          │
│                                                                      │
│   · Sesión: usuario/contraseña → token de Moodle (nunca toca disco)  │
│   · Endpoints REST internos  (/api/...)                              │
│   · Trabajos de calificación en hilos de fondo + dict JOBS           │
│   · Lectura/escritura de rúbricas (rubrics/*.json)                   │
└───────┬───────────────────────────────────────┬──────────────────────┘
        │                                       │
        │ importa                               │ importa
┌───────▼──────────────────┐         ┌──────────▼───────────────────────┐
│   api.py                 │         │   grader.py                      │
│   Cliente de Moodle      │         │   Motor de calificación          │
│                          │         │                                  │
│ · login/token.php        │         │ · Extrae texto (PDF/DOCX/ZIP/RAR)│
│ · /webservice/rest/...   │         │ · Arma la consigna completa      │
│ · auth por hilo          │         │ · Construye el prompt            │
│ · descarga de archivos   │         │ · Llama al LLM con límite duro   │
│ · save_grade             │         │ · Convierte criterios → nota     │
└───────┬──────────────────┘         └──────────┬───────────────────────┘
        │                                       │
        │ HTTPS                                 │ HTTPS
┌───────▼──────────────────┐         ┌──────────▼───────────────────────┐
│  MOODLE INSTITUCIONAL    │         │  API DEL MODELO (DeepSeek /      │
│                          │         │  cualquier endpoint OpenAI-like) │
│ · cursos y tareas        │         │                                  │
│ · entregas de estudiantes│         │ · recibe: consigna + rúbrica +   │
│ · escritura de notas     │         │   nombre + texto de la entrega   │
└──────────────────────────┘         └──────────────────────────────────┘
```

### Por qué esta forma y no otra

- **Sin base de datos.** El estado es efímero: los trabajos de calificación viven en memoria (`JOBS`) y las rúbricas en archivos JSON. Esto hace el sistema copiable a cualquier PC con solo arrastrar la carpeta.
- **Sin build ni dependencias de frontend.** HTML/CSS/JS planos: no hay `npm`, ni bundler, ni transpilador. Se abre y funciona.
- **El token de Moodle nunca se persiste.** Se obtiene al iniciar sesión y viaja dentro de la cookie de sesión firmada por Flask. Al cerrar sesión, desaparece.

---

## 3. Flujo completo de una calificación

### 3.1 Secuencia general

```
DOCENTE                NAVEGADOR            FLASK                 MOODLE            LLM
   │                       │                   │                     │                │
   │  usuario+contraseña   │                   │                     │                │
   ├──────────────────────►│  POST /api/login  │                     │                │
   │                       ├──────────────────►│  login/token.php    │                │
   │                       │                   ├────────────────────►│                │
   │                       │                   │◄──── token ─────────┤                │
   │                       │                   │  get_site_info      │                │
   │                       │                   ├────────────────────►│                │
   │                       │                   │◄── nombre, userid ──┤                │
   │                       │◄── cookie firmada ┤                     │                │
   │                       │                   │                     │                │
   │  elige curso          │  GET /api/courses │                     │                │
   │                       ├──────────────────►├────────────────────►│                │
   │  elige tarea          │  .../assignments  │  (+ submitidos y calificados)        │
   │                       ├──────────────────►├────────────────────►│                │
   │  marca estudiantes    │  .../submissions  │                     │                │
   │  elige rúbrica        │                   │                     │                │
   │                       │                   │                     │                │
   │  "Calificar"          │ POST .../preview  │                     │                │
   ├──────────────────────►├──────────────────►│                     │                │
   │                       │◄── job_id ────────┤  ┌─ hilo de fondo ─┐ │                │
   │                       │                   │  │ descarga adjuntos│ │                │
   │                       │                   │  ├─────────────────►│                │
   │                       │                   │  │ por estudiante:  │                │
   │                       │                   │  │  descarga entrega│                │
   │                       │                   │  ├─────────────────►│                │
   │                       │                   │  │  extrae texto    │                │
   │                       │                   │  │  prompt ─────────┼───────────────►│
   │                       │                   │  │◄───── JSON criterios ─────────────┤
   │                       │                   │  │  calcula la nota │                │
   │                       │  GET /api/jobs/X  │◄─┘ (progreso)      │                │
   │  ve "3/9 · ahora: …"  │◄──────────────────┤                     │                │
   │                       │                   │                     │                │
   │  revisa y edita       │                   │                     │                │
   │  "Publicar"           │ POST .../publish  │                     │                │
   ├──────────────────────►├──────────────────►│  save_grade × N     │                │
   │                       │                   ├────────────────────►│                │
   │  ve resultado por     │◄──────────────────┤◄──── ok / error ────┤                │
   │  estudiante           │                   │                     │                │
```

### 3.2 El trabajo de fondo, paso a paso

El endpoint `/preview` **no califica**: crea un trabajo y devuelve un `job_id` en milisegundos. La calificación ocurre en un hilo aparte para que la interfaz no se bloquee (una tarea de 10 estudiantes tarda ~70 s).

Dentro del hilo:

1. **Se fija la autenticación del hilo.** El token no se hereda del hilo de la petición, se pasa explícitamente (`api.set_auth`).
2. **Se construye la consigna.** Descripción de la tarea **+ el texto extraído de los adjuntos del docente** (guías, enunciados). Así el agente conoce el contexto completo, no solo la descripción breve.
3. **Se obtienen las entregas** (`mod_assign_get_submissions`) y los nombres reales (`core_enrol_get_enrolled_users`).
4. **Se filtra** al docente mismo y, si el usuario marcó checkboxes, a los estudiantes elegidos.
5. **Se informa el total inmediatamente** (`progress_cb(0, total, None)`) — sin esto, la interfaz mostraba `0/?` y parecía colgada.
6. **Por cada estudiante:**
   - se descarga cada archivo de la entrega a `webapp/cache/<tarea>/<userid>/`;
   - se extrae su texto;
   - si no hay nada legible, se envía el literal `(sin contenido legible)`;
   - se llama al modelo;
   - se registra el resultado y se avisa del progreso.
7. **Segunda pasada.** Los estudiantes que fallaron (típicamente por un cuelgue transitorio del proveedor) se reintentan al final.
8. **Se marca el trabajo como terminado** y los resultados quedan disponibles.

El navegador consulta `/api/jobs/<id>` cada 1,5 s y pinta el avance en vivo: `El agente está calificando… 6/9 procesadas · ahora: NOMBRE APELLIDO`.

---

## 4. Componentes en detalle

### 4.1 `api.py` — capa de acceso a Moodle (287 líneas)

Toda la comunicación con Moodle pasa por aquí. No sabe nada de IA ni de interfaz.

**Autenticación por hilo.** El sistema atiende a varios usuarios a la vez, y cada uno tiene su propio token. En lugar de variables globales se usa `threading.local()`:

```python
set_auth(token, site, userid)   # fija la credencial del hilo actual
clear_auth()                    # la limpia (se llama al terminar cada petición)
_auth()                         # devuelve (token, site) del hilo, con respaldo en config
```

Esto es lo que permite que **varios docentes usen la misma instancia** sin pisarse las credenciales.

**Configuración tolerante a fallos.** `cfg()` devuelve `{}` si no existe `config.json`, y `site_url()` resuelve la URL del sitio en este orden: variable `MOODLE_SITE` (del `.env`) → `config.json`. Así el sistema funciona con cualquiera de las dos configuraciones, o con ambas.

**Llamadas a Moodle.** `raw_call()` arma un POST `x-www-form-urlencoded` contra `/webservice/rest/server.php` y **aplana estructuras anidadas** al formato que espera Moodle (`plugindata[x][y]`), lo que permite enviar diccionarios y listas sin construirlos a mano.

**Descarga de archivos.** `download()` añade el token a la URL del archivo y lo baja con un User-Agent propio.

### 4.2 `grader.py` — motor de calificación (485 líneas)

Es el corazón del sistema. Se divide en tres responsabilidades:

#### a) Extracción de texto (`extract_text`)

Convierte cualquier entrega en texto plano. Elige la estrategia por extensión:

| Formato | Método |
|---|---|
| `.pdf` | PyMuPDF (`fitz`) |
| `.docx` | python-docx (párrafos y tablas) |
| `.zip` | Se descomprime y se extrae texto de cada archivo interno |
| `.rar` | Cadena de extractores: `bsdtar` → `tar` → `7z` → `unar` → `unrar` |
| Código y texto (`.py`, `.java`, `.md`, `.txt`, …) | Lectura directa |
| Imágenes y escaneos | **No soportado**: no hay OCR, el agente avisa |

#### b) Construcción del prompt (`grade_one`)

Hay **dos modos**, según la rúbrica tenga niveles o no:

| | Modo simple | Modo por niveles |
|---|---|---|
| Rúbrica | cada criterio tiene `max_points` | cada criterio tiene `descriptors` por nivel |
| Se le pide al modelo | un `score` numérico por criterio | **elegir un nivel** por criterio |
| Se le prohíbe | — | — |
| Cálculo del puntaje | directo | `max_points × % del nivel elegido / 100` |

En ambos casos el modelo responde **un único objeto JSON** con `criteria`, `summary` y `feedback`. En Python se hace:

1. **Mapeo tolerante de nombres de criterio** (por nombre normalizado y, si falla, por posición) para que una respuesta con nombres ligeramente distintos no rompa la calificación.
2. **Saneado de puntajes**: se recortan al rango `[0, max]` y se convierten a número.
3. **Escalado final**:

```
nota = (puntos obtenidos / puntos totales de la rúbrica) × nota máxima de la tarea
nota = min(max(nota, 0), nota_máxima)     # topes
```

4. **Composición de la retroalimentación** (`detalle_criterios`): al comentario general que redacta el modelo se le añade, **en Python**, el desglose de cada criterio con su nivel, su puntaje y el porqué:

```
Detalle por criterio:
• 1. Introducción — Excelente (0,3/0,3): Delimita el ámbito con precisión…
• 2. Aplicaciones — Satisfactorio (0,4/0,8): Solo presenta dos ejemplos…
Nota final: 2,75 / 3
```

El desglose se compone en código y **no** se le pide al modelo, para que el número que ve el estudiante sea exactamente el mismo que el que se registra en Moodle. Ese texto llega precargado al área editable de la previsualización, así que el docente puede ajustarlo o recortarlo antes de publicar.

#### c) Orquestación por lotes (`grade_submissions`)

Recorre los estudiantes, llama a `grade_one`, acumula resultados, notifica el progreso y **aísla los fallos**: si un estudiante falla, se marca con `status: "error"` y el bucle continúa. Después reintenta los fallidos.

#### d) Robustez del acceso al modelo (lo más delicado)

Aquí se concentran los problemas reales encontrados en producción:

- **`_post_con_limite()`** — ejecuta la petición HTTP en un hilo y **la abandona si excede el límite** (75 s por defecto). Es necesario porque el `timeout` de la librería `requests` se aplica a *cada lectura de socket*, no al total: si el proveedor envía datos a cuentagotas, el contador se reinicia en cada lectura y la petición puede quedarse colgada indefinidamente.
- **Reintentos** con espera progresiva, y **detección de respuesta vacía** (el modelo a veces gasta los tokens "razonando" y devuelve `content` vacío).
- **`max_tokens`** acotado para evitar respuestas desbordadas.

### 4.3 `app.py` — servidor web (725 líneas)

Es la capa de orquestación: expone la API interna, gestiona sesiones y coordina los trabajos.

**Sesión.** Flask firma una cookie con `SECRET_KEY` que contiene el token, el `userid` y el nombre. No hay base de datos de usuarios: **cada docente entra con su cuenta real de Moodle**.

**Trabajos concurrentes.** Los resultados de calificación se guardan en un diccionario global protegido por un candado:

```python
JOBS = {}                       # job_id → estado
JOBS_LOCK = threading.Lock()    # evita condiciones de carrera
```

Estructura de un trabajo:

```json
{
  "status": "running | done | error",
  "done": 3,
  "total": 9,
  "current": "GARY GABRIEL FAUBLA CARRILLO",
  "results": [ ... ],
  "assignid": 115167,
  "rubric": "Rubrica Tarea 1",
  "error": null
}
```

**Agrupación por secciones.** Para que las tareas aparezcan dentro de sus unidades (Unidad 1, Unidad 2…) se cruzan dos llamadas: `core_course_get_contents` (que da la estructura del curso y el `id` de cada módulo) y `mod_assign_get_assignments` (que da las tareas con su `cmid`). El mapeo `cmid → sección` permite reconstruir la estructura real del aula.

**Badge de avance.** Una sola llamada a `mod_assign_get_submissions` para **todas** las tareas del curso devuelve el campo `gradingstatus` de cada entrega, del que se derivan los contadores `calificados / entregas` que se muestran en cada tarjeta. Es deliberadamente una sola llamada para no castigar al servidor de Moodle con N peticiones.

**Parser de Excel.** Convierte una hoja de cálculo en una rúbrica. Detecta automáticamente el formato (simple o por niveles) y la fila de encabezados, ignorando acentos y mayúsculas en los nombres de columna. Si no encuentra encabezados, devuelve un error explícito en lugar de generar una rúbrica basura.

### 4.4 Frontend (`app.js` 787 · `style.css` 324 · `index.html` 173)

JavaScript vanilla, sin frameworks. Patrón general:

- `api(ruta, opciones)` — envoltorio de `fetch` que añade la cookie, interpreta el JSON y **detecta el 401 para devolver al login**.
- `state` — objeto único con el estado de la interfaz (cursos, curso actual, tareas, rúbrica elegida).
- Render por plantillas de cadena + `esc()` para escapar HTML (los nombres de estudiantes vienen de Moodle y se insertan de forma segura).
- **Polling** del trabajo con `setTimeout` recursivo (no `setInterval`, para evitar peticiones solapadas).

> Nota técnica: `$$(...)` es `document.querySelectorAll`, que devuelve un **NodeList**, no un array. Un NodeList soporta `forEach` y `for...of`, pero **no** tiene `.map()` ni `.filter()`. Por eso se convierte con `[...$$(...)]` antes de usar métodos de array. (Este fue un error real que rompía la selección de estudiantes.)

### 4.5 Rúbricas

Viven como JSON en `webapp/rubrics/`. Estructura:

```json
{
  "id": "rubrica_tarea_1",
  "name": "Rubrica Tarea 1",
  "description": "",
  "levels": [
    { "name": "Excelente",     "points_pct": 100.0 },
    { "name": "Satisfactorio", "points_pct": 50.0  },
    { "name": "Insuficiente",  "points_pct": 0.0   }
  ],
  "criteria": [
    {
      "name": "1. Introducción",
      "max_points": 0.3,
      "descriptors": {
        "Excelente": "Delimita el ámbito con precisión…",
        "Satisfactorio": "Presenta el ámbito…",
        "Insuficiente": "No delimita el ámbito…"
      }
    }
  ]
}
```

- Si `levels` está vacío o ausente → **modo simple**.
- Si falta `points_pct` en los niveles → se reparten automáticamente (100 / 50 / 0 para tres niveles).
- Si falta `max_points` en los criterios → todos pesan igual.

---

## 5. API interna (endpoints)

Toda la API interna vive bajo `/api/` y exige sesión válida (excepto el login).

| Método | Ruta | Para qué sirve |
|---|---|---|
| `POST` | `/api/login` | Valida usuario/contraseña contra Moodle y crea la sesión |
| `POST` | `/api/logout` | Cierra la sesión (y descarta la clave de API) |
| `GET` | `/api/apikey` | Estado de la clave del docente (configurada o no + pista enmascarada) |
| `POST` | `/api/apikey` | Guarda y **verifica** la clave contra el proveedor |
| `DELETE` | `/api/apikey` | Elimina la clave de la sesión |
| `GET` | `/api/me` | Datos del docente conectado |
| `GET` | `/api/courses` | Cursos donde es docente |
| `GET` | `/api/courses/<cid>/assignments` | Tareas **agrupadas por sección**, con contadores |
| `GET` | `/api/assignments/<aid>` | Detalle de la tarea (nota máxima, consigna, adjuntos) |
| `GET` | `/api/assignments/<aid>/submissions` | Entregas: estudiante, archivos |
| `GET` | `/api/assignments/<aid>/submissions/<uid>/files/<nombre>` | Descarga una entrega (de caché si ya está) |
| `GET` | `/api/assignments/<aid>/attachments/<nombre>` | Descarga un adjunto de la consigna |
| `GET` | `/api/rubrics` | Lista las rúbricas |
| `POST` | `/api/rubrics` | Crea o actualiza una rúbrica |
| `DELETE` | `/api/rubrics/<rid>` | Borra una rúbrica |
| `POST` | `/api/rubrics/parse-excel` | Convierte un Excel/CSV en rúbrica |
| `POST` | `/api/assignments/<aid>/preview` | **Lanza la calificación** y devuelve `job_id` |
| `GET` | `/api/jobs/<job_id>` | Estado y resultados del trabajo |
| `POST` | `/api/assignments/<aid>/publish` | Escribe notas y comentarios en Moodle |

---

## 6. Integración con Moodle

### 6.1 Cómo se obtiene el acceso

Sin administrador, el camino es el **servicio web móvil**:

```
POST https://<moodle>/login/token.php
     username=<usuario>&password=<contraseña>&service=moodle_mobile_app
  → { "token": "...", "privatetoken": "..." }
```

Ese token autoriza las llamadas REST con los **permisos del propio docente**: puede ver las tareas de sus cursos y calificar, pero no puede tocar nada ajeno a su rol. Es exactamente el mismo mecanismo que usa la app oficial de Moodle.

### 6.2 Funciones de Moodle utilizadas

| Función | Uso |
|---|---|
| `core_webservice_get_site_info` | Validar el token y obtener `userid` y nombre |
| `core_enrol_get_users_courses` | Cursos del docente |
| `core_course_get_contents` | Estructura del curso (secciones y módulos) |
| `core_enrol_get_enrolled_users` | Nombres reales de los estudiantes |
| `mod_assign_get_assignments` | Tareas de un curso (nota máxima, fechas, consigna, adjuntos) |
| `mod_assign_get_submissions` | Entregas + `gradingstatus` (calificado o no) |
| `mod_assign_save_grade` | **Escribe la nota y el comentario** |

### 6.3 El detalle crítico: `mod_assign_save_grade`

En Moodle 4.5 esta función exige **siete** parámetros. Si falta uno, la respuesta es un escueto `invalidparameter` que no dice cuál:

```python
mod_assign_save_grade(
    assignmentid = <id de la tarea>,
    userid       = <id del estudiante>,
    grade        = <nota>,
    attemptnumber= -1,        # el intento más reciente
    addattempt   = 0,         # no crear un intento nuevo
    workflowstate= "",        # ← OBLIGATORIO en Moodle 4.5; "" = sin flujo de revisión
    applytoall   = 1,
    plugindata   = { "assignfeedbackcomments_editor": { "text": <comentario>, "format": 2 } }
)
```

`format: 2` = texto plano, para que los saltos de línea del comentario se respeten en Moodle.

### 6.4 Manejo de errores

Moodle **nunca devuelve códigos HTTP de error**: devuelve `200 OK` con un objeto `{"exception": ..., "errorcode": ..., "message": ...}`. Todo el código comprueba explícitamente la presencia de `exception` antes de dar una respuesta por buena. Es una fuente clásica de fallos silenciosos si se ignora.

---

## 7. Integración con el modelo de IA

### 7.1 Qué se envía exactamente

El prompt tiene dos partes:

**Mensaje de sistema** — define el rol ("asistente de calificación académica"), exige objetividad, fija el esquema JSON de respuesta y, en rúbricas por niveles, la lista exacta de niveles permitidos.

**Mensaje de usuario:**

```
CONSIGNA DE LA TAREA:
<descripción de la tarea>
[ADJUNTO DE LA TAREA: guia.pdf]
<texto extraído de la guía>

RÚBRICA "Rubrica Tarea 1" (por niveles):
- 1. Introducción (máx 0.3):
    • Excelente (100%): Delimita el ámbito con precisión…
    • Satisfactorio (50%): Presenta el ámbito…
    • Insuficiente (0%): No delimita el ámbito…

ESTUDIANTE: NOMBRE COMPLETO DEL ESTUDIANTE

CONTENIDO DE LA ENTREGA:
<texto de la entrega, hasta 30 000 caracteres>

Evalúa la entrega y devuelve el JSON con el nivel elegido en cada criterio.
```

### 7.2 Configuración de la petición

| Parámetro | Valor | Motivo |
|---|---|---|
| `model` | `deepseek-v4-flash` (configurable con `GRADER_MODEL`) | Equilibrio velocidad/coste; hay modelos más potentes si se necesita |
| `temperature` | `0.2` | Baja variabilidad entre correcciones |
| `response_format` | `{"type": "json_object"}` | Fuerza JSON válido (el proveedor exige la palabra "json" en el prompt) |
| `thinking` | `{"type": "disabled"}` | Desactiva el razonamiento previo: respuestas directas y rápidas |
| `max_tokens` | `4000` | Acota la salida |

> **Nota:** el proveedor a veces ignora `thinking: disabled` y gasta los tokens en `reasoning_content`, devolviendo `content` vacío. El código lo detecta y reintenta.

### 7.3 De quién es la clave de API

La clave con la que se llama al modelo **no es del servidor, es de cada docente**. Así el consumo se factura a la cuenta de quien califica, y el dueño de la instancia no paga las correcciones de los demás.

El recorrido de la clave:

```
docente escribe la clave en el modal «🔑 Mi API key»
        │  POST /api/apikey
        ▼
grader.probar_clave()   → una llamada mínima al proveedor la verifica
        │
        ├──► LLM_KEYS[userid]          caché EN MEMORIA (uso inmediato)
        │
        └──► secretos.guardar()        copia CIFRADA en webapp/secretos.db
                  │  Fernet (AES-128-CBC + HMAC-SHA256)
                  │  clave maestra = SECRETOS_KEY del .env  (fuera de la BD)
                  ▼
             ╔════════════════════════════════════╗
             ║ userid │ nombre │ cifrado (BLOB)   ║
             ║ 144757 │ TEDDY  │ gAAAAAB… (ilegible)║
             ╚════════════════════════════════════╝

al calificar:  grade_submissions(..., api_key=clave)  →  Authorization: Bearer …
al reiniciar el servidor: la memoria se vacía y la clave se vuelve a
                          descifrar desde secretos.db de forma transparente
```

**Dos motivos para persistirla:** las claves de DeepSeek **solo se pueden ver una vez** al generarlas (si se pierde, hay que crear otra), y volver a escribirla tras cada reinicio del servidor es una molestia evitable.

Decisiones de esta parte:

| Decisión | Motivo |
|---|---|
| Se guarda **cifrada**, nunca en claro | Un archivo de base de datos filtrado o incluido por error en un respaldo es el escenario realista; sin la clave maestra no sirve de nada |
| La **clave maestra vive fuera** de la base de datos (en el `.env`) | Guardarla dentro anularía el cifrado: quien tuviera el archivo tendría también la llave |
| La memoria sigue siendo la vía rápida | Se descifra una sola vez por sesión, no en cada llamada al modelo |
| **Nunca** viaja en la cookie de sesión | La cookie de Flask está firmada pero **no cifrada**: es legible por el navegador |
| El navegador solo recibe una **pista enmascarada** (`sk-2cb1…3761`) | Permite confirmar cuál está puesta sin exponerla |
| Se **verifica** contra el proveedor al guardarla | Evita descubrir que estaba mal escrita a mitad de una corrección |
| Cerrar sesión borra **solo la copia en memoria** | La guardada se conserva para no obligar a reescribirla; «Eliminar» sí borra las dos |
| Sin clave **no se califica** | La aplicación devuelve `400` con `need_api_key: true` y la interfaz abre el modal sola |

**Qué protege y qué no:**

| Escenario | ¿Protegido? |
|---|---|
| Alguien copia `secretos.db` (respaldo, USB, `git add` despistado) | ✅ ilegible sin la clave maestra |
| Alguien lee el proceso mientras califica | ❌ la clave está en memoria, como en cualquier servicio |
| Alguien se lleva el equipo completo (BD **y** `.env`) | ❌ el cifrado no ayuda: están las dos piezas |
| Se pierde el `.env` con `SECRETOS_KEY` | ⚠️ no se puede descifrar (no se corrompe nada): habrá que volver a escribirla |

> La clave **nunca** se lee del `.env`: no existe una clave «del servidor». Calificar exige siempre la clave del docente conectado y, si falta, la aplicación responde `400` con `need_api_key: true` y abre el modal sola.

### 7.4 Coste

Cada entrega supone **una llamada** al modelo con, aproximadamente, la consigna (variable) + la rúbrica + el texto de la entrega (hasta 30 000 caracteres, unos 8 000 tokens). Con `deepseek-v4-flash`, corregir un curso de 30 estudiantes cuesta céntimos.

---

## 8. Modelo de datos

### 8.1 Resultado de calificación de un estudiante

```json
{
  "userid": 1112,
  "fullname": "GARY GABRIEL FAUBLA CARRILLO",
  "files": ["Tarea #1 Informe de aplicaciones.pdf"],
  "status": "ok",
  "criteria": [
    { "name": "1. Introducción", "level": "Excelente", "score": 0.3, "max": 0.3, "comment": "…" }
  ],
  "earned": 2.95,
  "rubric_max": 3.0,
  "grade": 2.95,
  "max_grade": 3.0,
  "summary": "justificación general de la nota",
  "feedback": "texto general del agente + bloque «Detalle por criterio» (esto es lo que se publica)"
}
```

### 8.2 Caché de archivos en disco

```
webapp/cache/
├── <assignmentid>/<userid>/<archivo de la entrega>   ← entregas descargadas
└── consigna/<assignmentid>/<adjunto de la tarea>      ← guías del docente
```

La caché evita volver a descargar un archivo ya visto. **Contiene datos personales de estudiantes y nunca se versiona** (está en `.gitignore`).

---

## 9. Decisiones de diseño y problemas resueltos

Esta sección documenta los problemas reales encontrados durante el desarrollo. Es la parte más útil para quien mantenga el sistema.

| # | Problema | Causa | Solución |
|---|---|---|---|
| 1 | `invalidparameter` al publicar notas | Moodle 4.5 exige el parámetro `workflowstate` en `mod_assign_save_grade` | Añadirlo con valor `""` |
| 2 | El importador de Excel devolvía rúbricas vacías | Se comparaba un índice entero contra claves de texto (`j in columnas`) | Comprobar el tipo antes de comparar |
| 3 | Tablas sin encabezados generaban rúbricas basura | No se validaba la estructura | Detectar la fila de encabezados y devolver un error claro |
| 4 | **La calificación se quedaba congelada indefinidamente** | Si el proveedor gotea la respuesta, el timeout de `requests` se reinicia en cada lectura y nunca vence | **Límite de tiempo duro**: ejecutar la petición en un hilo y abandonarla a los 75 s |
| 5 | Algunos estudiantes quedaban en error | Respuestas vacías (`content: ""` con `reasoning_content`) o cuelgues transitorios | Detectar la respuesta vacía + reintentos + **segunda pasada** al final |
| 6 | La barra mostraba `0/?` y parecía colgada | El total solo se informaba tras el primer estudiante | Notificar el total **antes** de empezar, y mostrar además qué estudiante se está procesando |
| 7 | Errores de JavaScript al seleccionar estudiantes | `$$()` devuelve un NodeList, que no tiene `.map()` ni `.filter()` | Convertir a array con `[...$$(...)]` |
| 8 | Varios docentes se pisaban las credenciales | Estado global compartido | Autenticación **por hilo** (`threading.local`) |
| 9 | El token quedaba guardado en disco | Se leía de `config.json` | Eliminarlo: el token vive en la cookie de sesión |
| 10 | Nombres de criterio distintos en la respuesta del modelo | El LLM no siempre repite el texto exacto | Mapeo por nombre normalizado y respaldo **posicional** |

### Decisiones deliberadas

- **El LLM no calcula la nota final.** Solo puntúa criterios; la aritmética es de Python. Resultado: reproducible y auditable.
- **Los archivos van a caché, no a memoria.** Permite reparar y revisar una corrección sin volver a descargar.
- **Una sola llamada para los contadores de todas las tareas de un curso**, en lugar de una por tarea.
- **Sin base de datos.** Copiar la carpeta es toda la migración.
- **La retroalimentación pasa siempre por el docente.** El agente redacta el comentario general y añade el desglose por criterio; ese texto llega a un área editable y **solo se escribe en Moodle si el docente lo aprueba** para cada estudiante.

---

## 10. Seguridad y privacidad

### Qué sale del equipo

| Destino | Qué se envía |
|---|---|
| **API del modelo** | Nombre completo del estudiante + texto de su entrega (≤ 30 000 caracteres) + consigna + rúbrica |
| **Moodle** | Nota y comentario, solo al publicar |

**No** se envían al modelo: calificaciones previas, correos, identificadores internos, contraseñas ni el token de Moodle.

Si se prefiere anonimizar, basta con no incluir el nombre en el prompt de `grade_one()` (el cambio es de una línea), aunque el autor optó por mantenerlo: ayuda al modelo a interpretar entregas con nombres propios mal escritos por OCR.

### Qué nunca se versiona

`.env` · `secret_key` · `submissions/` · `webapp/cache/` · `report_*.md` — credenciales y **entregas reales de estudiantes**.

### Quién puede entrar

La aplicación está reservada a **docentes**. Antes de consultar a Moodle se valida el formato del usuario:

```
^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+@utm\.edu\.ec$     (sin distinguir mayúsculas)
```

Es decir, solo se acepta el patrón institucional **`nombre.apellido@utm.edu.ec`** (con la posibilidad de más segmentos, como `maria.josefa.ramirez@`, o de un número final para nombres duplicados, como `juan.perez2@`).

Cualquier otro formato —el número de cédula con el que suelen ingresar los estudiantes, correos sin punto, otros dominios o variantes del dominio— **se rechaza con un `403` antes de contactar a Moodle**, así que no consume intentos de autenticación ni revela si la cuenta existe.

| Usuario | Resultado |
|---|---|
| `teddy.moreira@utm.edu.ec` | ✅ pasa a validación contra Moodle |
| `maria.josefa.ramirez@utm.edu.ec` | ✅ |
| `juan.perez2@utm.edu.ec` | ✅ |
| `1234567@utm.edu.ec` | ❌ 403 |
| `estudiante@utm.edu.ec` | ❌ 403 |
| `juan.perez@gmail.com` | ❌ 403 |
| `juan.perez@utm.edu.ec.otro.com` | ❌ 403 |

El control vive en `PATRON_DOCENTE` (`app.py`) y es **la única puerta de entrada**: la interfaz solo lo anuncia, no lo decide.

### Qué se guarda y qué no

| Secreto | ¿Se guarda? | Cómo |
|---|---|---|
| Clave de API del modelo | ✅ Sí, para no volver a escribirla (las de DeepSeek solo se ven una vez) | **Cifrada** (Fernet) en `webapp/secretos.db`, permisos `600` |
| Contraseña del Aula Evirtual | ❌ Nunca | Solo se usa en memoria, para pedir el token |
| Token de Moodle | ⚠️ Solo en la cookie de sesión | Firmada, `HttpOnly` y de vida corta |
| Clave maestra (`SECRETOS_KEY`) | ✅ En el `.env` | **Fuera** de la base de datos: es lo que hace útil el cifrado |

**Por qué la clave de API se cifra y no se hashea.** `bcrypt` —y cualquier hash— es de un solo sentido: sirve para *verificar* un secreto, no para *reutilizarlo*. La clave de API tiene que **reenviarse tal cual** al proveedor en cada llamada (`Authorization: Bearer …`), así que guardar su hash la volvería inutilizable: habría que teclearla en cada calificación y la persistencia no aportaría nada. Para un secreto que hay que reutilizar solo caben dos opciones honestas: **no guardarlo** (lo que se hace con la contraseña de Moodle) o **guardarlo cifrado** con cifrado reversible (lo que se hace con la clave de API).

Se eligió persistir la clave de API —y no la contraseña de Moodle— porque el daño de cada una es muy distinto: perder una clave de DeepSeek se resuelve generando otra, mientras que la contraseña institucional da acceso a todo el aula y suele reutilizarse en otros servicios.

> **Compromiso aceptado y a sabiendas:** la cookie de sesión de Flask va **firmada pero no cifrada**, así que contiene el token de Moodle en claro (visible en las herramientas de desarrollo del navegador). Se acepta porque es un token de sesión revocable y de vida corta, y porque la cookie es `HttpOnly` (el JavaScript de la página no puede leerla). Por ese mismo motivo **ningún otro secreto** —ni la clave de API ni la contraseña— pasa por ahí.

### Superficie de exposición

Por defecto la app escucha en `0.0.0.0` para permitir el acceso desde el aula. **No tiene HTTPS ni límite de intentos de login**: está pensada para una red local de confianza. Para exponerla a internet harían falta, como mínimo, un proxy inverso con TLS y autenticación adicional.

---

## 11. Estructura de archivos

```
.
├── api.py                       287 líneas  · Cliente de la API REST de Moodle
├── config.json                              · URL del sitio (alternativa a MOODLE_SITE)
├── .env                                     · Credenciales ⚠️ NO se versiona
├── .env.example                             · Plantilla de credenciales
├── .gitignore                               · Excluye credenciales y datos de estudiantes
├── .gitattributes                           · Finales de línea entre sistemas operativos
├── LICENSE                                  · MIT
├── README.md                                · Guía de instalación y uso
├── DOCUMENTACION.md                         · Este documento
└── webapp/
    ├── app.py                   764 líneas  · Backend Flask: endpoints, trabajos, rúbricas
    ├── grader.py                485 líneas  · Motor: extracción de texto + LLM + notas
    ├── secretos.py              165 líneas  · Almacén cifrado de las claves de API
    ├── secretos.db                          · Claves cifradas ⚠️ NO se versiona
    ├── run.sh                               · Lanzador Linux/macOS
    ├── run.bat                              · Lanzador Windows
    ├── requirements.txt                     · flask · requests · pymupdf · python-docx · openpyxl · cryptography
    ├── SETUP_WINDOWS.md                     · Guía detallada para Windows
    ├── README.md                            · Nota sobre esta carpeta
    ├── rubrics/                             · Rúbricas en JSON
    ├── static/app.js            886 líneas  · Lógica de la interfaz
    ├── static/style.css         339 líneas  · Estilos
    ├── templates/index.html     231 líneas  · Estructura de la interfaz
    ├── cache/                               · Entregas descargadas ⚠️ NO se versiona
    └── venv/                                · Entorno virtual ⚠️ NO se versiona
```

**Dependencias** (`requirements.txt`):

| Paquete | Para qué |
|---|---|
| `flask` | Servidor web y sesiones firmadas |
| `requests` | Llamadas a la API del modelo |
| `pymupdf` | Extracción de texto de PDF |
| `python-docx` | Extracción de texto de Word |
| `openpyxl` | Lectura de rúbricas en Excel |

Todo lo demás es **biblioteca estándar de Python** (`urllib`, `threading`, `json`, `subprocess`…) y JavaScript sin frameworks.

---

## 12. Despliegue y configuración

### Puesta en marcha

```bash
cp .env.example .env    # rellenar MOODLE_SITE y SECRET_KEY
cd webapp && ./run.sh   # Linux/macOS   (Windows: run.bat)
# al entrar en la web, cada docente configura ahí su clave de API
```

El lanzador verifica la versión de Python, crea el entorno virtual la primera vez, avisa si falta el `.env` y muestra la dirección de red local.

### Variables de entorno

| Variable | Por defecto | Función |
|---|---|---|
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | Permite usar cualquier proveedor compatible con la API de OpenAI |
| `GRADER_MODEL` | `deepseek-v4-flash` | Modelo que califica |
| `MOODLE_SITE` | — | URL del Moodle (sustituye a `config.json`) |
| `SECRET_KEY` | — | Firma de las cookies de sesión |
| `SECRETOS_KEY` | se genera sola | Clave maestra que descifra las claves de API guardadas. **No la borres**: sin ella, las claves guardadas dejan de poder leerse |
| `HOST` | `0.0.0.0` | `127.0.0.1` para restringir a la máquina local |
| `PORT` | `5050` | Puerto del servidor |

### Requisitos del Moodle de destino

1. Servicios web activados.
2. El servicio `moodle_mobile_app` habilitado.
3. Que el usuario sea **docente** del curso (no hace falta administrador).

---

## 13. Limitaciones conocidas

| Limitación | Detalle |
|---|---|
| **Sin OCR** | Entregas escaneadas a mano o fotografías no se pueden calificar: el sistema trabaja con texto. Requeriría añadir Tesseract |
| **Sin comprobación de originalidad** | No detecta plagio ni uso de IA por parte del estudiante |
| **Estado en memoria** | Reiniciar el servidor descarta los trabajos en curso; las rúbricas y la caché sí persisten en disco |
| **Servidor de desarrollo** | Se usa el servidor integrado de Flask. Para uso intensivo conviene un servidor WSGI (gunicorn, waitress) |
| **Sin HTTPS ni límite de intentos** | Adecuado para red local de confianza, no para exponerlo a internet |
| **Un solo modelo por despliegue** | El modelo se fija por variable de entorno, no se elige por tarea desde la interfaz |
| **Rúbricas de un solo nivel de anidación** | Criterios con niveles, sin subcriterios |
| **Dependencia del proveedor del modelo** | Si el proveedor encola o limita peticiones, algunas calificaciones fallan y hay que reintentarlas (el sistema lo hace solo, pero alarga el proceso) |

---

## 14. Glosario

| Término | Significado |
|---|---|
| **Consigna** | Enunciado de la tarea: descripción + adjuntos que subió el docente |
| **Entrega / submission** | Archivo(s) que subió un estudiante para una tarea |
| **Rúbrica** | Conjunto de criterios con sus pesos y descriptores de desempeño |
| **Nivel** | Grado de desempeño en una rúbrica por niveles (Excelente, Satisfactorio…) |
| **Escalado** | Conversión del puntaje de la rúbrica a la nota máxima de la tarea |
| **Trabajo / job** | Ejecución de calificación de una tarea, con su progreso y resultados |
| **Token de Moodle** | Credencial que autoriza las llamadas REST en nombre del docente |
| **Web service** | Interfaz de Moodle para que sistemas externos consulten y escriban datos |
| **Previsualización** | Tabla de notas propuestas que el docente revisa **antes** de publicar |
| **Publicar** | Escribir definitivamente la nota y el comentario en Moodle |

---

*Documento técnico del Calificador Moodle — Aula Evirtual UTM.*
