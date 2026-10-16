"""Calificador Moodle — backend Flask con login por usuario/contraseña de Moodle."""
import json, os, re, sys, html, threading, uuid, io, unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from flask import Flask, jsonify, request, send_from_directory, send_file, session  # noqa: E402
import grader  # noqa: E402
import api  # noqa: E402
import secretos  # noqa: E402

api.load_env()  # carga las credenciales del .env antes de leer cualquier configuración

app = Flask(__name__, static_folder="static", template_folder="templates")


def _load_secret_key():
    """Clave de firma de sesiones: SECRET_KEY (.env) → archivo secret_key → se genera."""
    from_env = (os.environ.get("SECRET_KEY") or "").strip()
    if from_env:
        return from_env
    path = os.path.join(HERE, "secret_key")
    if os.path.exists(path):
        return open(path).read().strip()
    key = os.urandom(32).hex()
    with open(path, "w") as f:
        f.write(key)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


app.secret_key = _load_secret_key()

RUBRICS_DIR = os.path.join(HERE, "rubrics")
CACHE_DIR = os.path.join(HERE, "cache")

JOBS = {}
JOBS_LOCK = threading.Lock()

# Clave de API del modelo, por docente. Vive SOLO en la memoria del servidor:
# nunca se escribe en disco ni viaja dentro de la cookie de sesión.
LLM_KEYS = {}
LLM_KEYS_LOCK = threading.Lock()


def _llm_key(userid=None):
    """Clave de API del docente conectado (o de otro userid si se indica).

    Se busca primero en memoria y, si no está —por ejemplo tras reiniciar el
    servidor—, en el almacén cifrado de disco; al encontrarla queda cacheada.
    """
    if userid is None:
        userid = session.get("userid")
    with LLM_KEYS_LOCK:
        clave = LLM_KEYS.get(userid)
    if clave:
        return clave
    clave = secretos.obtener(userid)        # se descifra desde secretos.db
    if clave:
        with LLM_KEYS_LOCK:
            LLM_KEYS[userid] = clave
    return clave


def _mask(clave):
    """Muestra solo las puntas de una clave. Nunca se devuelve entera al navegador."""
    if not clave:
        return ""
    if len(clave) <= 12:
        return "•" * len(clave)
    return f"{clave[:7]}…{clave[-4:]}"


# ───────────────────────── autenticación ─────────────────────────

def site_url():
    return api.site_url()


@app.before_request
def _session_auth():
    if not request.path.startswith("/api/") or request.path == "/api/login":
        return
    token = session.get("token")
    if not token:
        return jsonify({"error": "No autenticado"}), 401
    api.set_auth(token, site_url(), session.get("userid"))


@app.teardown_request
def _clear_auth(exc):
    api.clear_auth()


# Códigos de error de Moodle traducidos a un mensaje que entienda el docente.
_ERRORES_LOGIN = {
    "invalidlogin": "Usuario o contraseña incorrectos. Revisa tus datos del Aula Evirtual.",
    "usernotfound": "Ese usuario no existe en el Aula Evirtual.",
    "invalidtoken": "La credencial del servicio expiró. Inténtalo otra vez.",
    "accessexception": "El servicio móvil de Moodle no está disponible en este momento.",
    "webservicesnotenabled": "Este Moodle tiene los servicios web desactivados.",
    "enablewsdescription": "Este Moodle tiene los servicios web desactivados.",
    "servicenotavailable": "El servicio «moodle_mobile_app» está deshabilitado en este Moodle.",
}


def _mensaje_login(texto):
    """Traduce los códigos o mensajes de error de Moodle a algo claro para el docente."""
    t = (texto or "").strip()
    clave = t.lower().replace(" ", "").replace("_", "")
    if clave in _ERRORES_LOGIN:
        return _ERRORES_LOGIN[clave]
    bajo = t.lower()
    # Moodle a veces devuelve el mensaje ya traducido en lugar del código de error.
    if "usernotfound" in clave or "usuario no encontrado" in bajo:
        return _ERRORES_LOGIN["usernotfound"]
    if "inválid" in bajo or "invalid" in bajo:
        return _ERRORES_LOGIN["invalidlogin"]
    if "servicio" in bajo and ("deshabilitad" in bajo or "no disponible" in bajo):
        return _ERRORES_LOGIN["servicenotavailable"]
    return t or "No se pudo iniciar sesión. Inténtalo de nuevo."


# Solo docentes: el usuario debe tener la forma nombre.apellido@utm.edu.ec.
# Cualquier otro formato (por ejemplo el número de cédula con el que suelen
# ingresar los estudiantes) se rechaza antes de consultar a Moodle.
PATRON_DOCENTE = re.compile(r"^[a-z][a-z0-9]*(\.[a-z][a-z0-9]*)+@utm\.edu\.ec$", re.IGNORECASE)

MENSAJE_SOLO_DOCENTES = (
    "Acceso restringido a docentes: el usuario debe ser tu correo institucional "
    "con el formato nombre.apellido@utm.edu.ec."
)


@app.route("/api/login", methods=["POST"])
def login():
    body = request.get_json(silent=True) or {}
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not username or not password:
        return jsonify({"error": "Usuario y contraseña son obligatorios"}), 400
    if not PATRON_DOCENTE.match(username):
        return jsonify({"error": MENSAJE_SOLO_DOCENTES}), 403
    try:
        token = api.login(username, password, site_url())
        info = api.get_site_info(token, site_url())
        if isinstance(info, dict) and "exception" in info:
            raise RuntimeError(info.get("message", "Error validando la sesión"))
        session["token"] = token
        session["userid"] = info.get("userid")
        session["fullname"] = info.get("fullname")
        session["username"] = info.get("username")
        return jsonify({
            "fullname": info.get("fullname"),
            "username": info.get("username"),
            "userid": info.get("userid"),
        })
    except Exception as e:
        return jsonify({"error": _mensaje_login(str(e))}), 401


@app.route("/api/logout", methods=["POST"])
def logout():
    with LLM_KEYS_LOCK:
        # Solo se olvida la copia en memoria; la guardada cifrada se conserva
        LLM_KEYS.pop(session.get("userid"), None)
    session.clear()
    return jsonify({"ok": True})


# ─────────────── clave de API del modelo (por docente) ───────────────

@app.route("/api/apikey", methods=["GET"])
def apikey_status():
    uid = session.get("userid")
    clave = _llm_key()
    return jsonify({
        "configured": bool(clave),
        "hint": _mask(clave),
        "remembered": secretos.hay(uid),     # ¿está guardada en disco?
    })


@app.route("/api/apikey", methods=["POST"])
def apikey_save():
    clave = ((request.get_json(silent=True) or {}).get("api_key") or "").strip()
    if not clave:
        return jsonify({"error": "Escribe tu clave de API"}), 400
    if not clave.startswith("sk-") or len(clave) < 20:
        return jsonify({"error": "Esa no parece una clave válida: deben empezar por «sk-»"}), 400

    # Se comprueba contra el proveedor antes de darla por buena.
    verificada, detalle = grader.probar_clave(clave)

    with LLM_KEYS_LOCK:
        LLM_KEYS[session["userid"]] = clave
    # Y se guarda cifrada para que sobreviva a los reinicios del servidor.
    guardada, error_guardado = False, ""
    try:
        secretos.guardar(session["userid"], session.get("fullname", ""), clave)
        guardada = True
    except Exception as e:
        error_guardado = str(e)

    avisos = []
    if not verificada:
        avisos.append(f"El proveedor no la aceptó: {detalle}")
    if not guardada:
        avisos.append(f"No se pudo guardar en disco: {error_guardado}")

    return jsonify({
        "ok": True,
        "hint": _mask(clave),
        "verified": verificada,
        "remembered": guardada,
        "warning": " · ".join(avisos),
    })


@app.route("/api/apikey", methods=["DELETE"])
def apikey_delete():
    uid = session.get("userid")
    with LLM_KEYS_LOCK:
        LLM_KEYS.pop(uid, None)
    secretos.borrar(uid)                     # y también la copia guardada
    return jsonify({"ok": True})


# ───────────────────────── utilidades ─────────────────────────

def strip_html(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def load_rubrics():
    out = []
    for fn in sorted(os.listdir(RUBRICS_DIR)):
        if fn.endswith(".json"):
            with open(os.path.join(RUBRICS_DIR, fn), encoding="utf-8") as f:
                out.append(json.load(f))
    return out


def assignment_detail(aid):
    courses = api.get_courses(session.get("userid"))
    if isinstance(courses, dict):
        return None
    for c in courses:
        assigns = api.get_assignments(c["id"])
        if isinstance(assigns, dict):
            continue
        for a in assigns:
            if a["id"] == aid:
                atts = []
                for key in ("introattachments", "introfiles"):
                    for f in a.get(key) or []:
                        if f.get("fileurl"):
                            atts.append({"name": f.get("filename"), "url": f.get("fileurl")})
                return {
                    "id": a["id"],
                    "name": a["name"],
                    "courseid": c["id"],
                    "coursename": c.get("fullname"),
                    "intro": strip_html(a.get("intro")),
                    "grade": a.get("grade"),
                    "duedate": a.get("duedate"),
                    "attachments": atts,
                }
    return None


# ───────────────────────── API ─────────────────────────

@app.route("/api/me")
def me():
    if not session.get("token"):
        return jsonify({"error": "No autenticado"}), 401
    return jsonify({
        "fullname": session.get("fullname"),
        "username": session.get("username"),
        "site": site_url(),
        "userid": session.get("userid"),
    })


@app.route("/api/courses")
def courses():
    d = api.get_courses(session.get("userid"))
    if isinstance(d, dict):
        return jsonify({"error": str(d)}), 502
    return jsonify([{"id": x["id"], "fullname": x.get("fullname"),
                     "shortname": x.get("shortname")} for x in d])


@app.route("/api/courses/<int:cid>/assignments")
def assignments(cid):
    d = api.get_assignments(cid)
    if isinstance(d, dict):
        return jsonify({"error": str(d)}), 502

    # Conteo de entregas y calificados por tarea (una sola llamada).
    counts = {}
    try:
        resp = api.call("mod_assign_get_submissions", assignmentids=[a["id"] for a in d])
        teacher = session.get("userid")
        for asg in resp.get("assignments", []):
            subs = [x for x in asg.get("submissions", []) if x.get("userid") != teacher]
            graded = sum(1 for x in subs if x.get("gradingstatus") == "graded")
            counts[asg.get("assignmentid")] = {"submitted": len(subs), "graded": graded}
    except Exception:
        counts = {}

    def brief(a):
        c = counts.get(a["id"], {})
        return {"id": a["id"], "name": a["name"],
                "grade": a.get("grade"), "duedate": a.get("duedate"),
                "submitted": c.get("submitted", 0), "graded": c.get("graded", 0)}

    contents = api.call("core_course_get_contents", courseid=cid)
    if not isinstance(contents, list):
        return jsonify([{"name": "Tareas", "assignments": [brief(a) for a in d]}])

    cmid_to_section = {}
    for s in contents:
        for m in s.get("modules", []):
            if m.get("modname") == "assign":
                cmid_to_section[m.get("id")] = (s.get("name") or "General").strip()

    grouped = {}
    unplaced = []
    for a in d:
        sec = cmid_to_section.get(a.get("cmid"))
        if sec:
            grouped.setdefault(sec, []).append(brief(a))
        else:
            unplaced.append(brief(a))

    order = []
    for s in contents:
        name = (s.get("name") or "General").strip()
        if name in grouped and name not in order:
            order.append(name)

    sections = [{"name": n, "assignments": grouped[n]} for n in order]
    for n, items in grouped.items():
        if n not in order:
            sections.append({"name": n, "assignments": items})
    if unplaced:
        sections.append({"name": "Otras actividades", "assignments": unplaced})
    return jsonify(sections)


@app.route("/api/assignments/<int:aid>")
def assign_detail(aid):
    d = assignment_detail(aid)
    if not d:
        return jsonify({"error": "tarea no encontrada"}), 404
    return jsonify(d)


@app.route("/api/assignments/<int:aid>/submissions")
def submissions(aid):
    detail = assignment_detail(aid)
    if not detail:
        return jsonify({"error": "tarea no encontrada"}), 404
    subs = api.get_submissions(aid)
    if isinstance(subs, dict):
        return jsonify({"error": str(subs)}), 502
    enrolled = {u["id"]: u.get("fullname", u.get("username"))
                for u in api.get_enrolled(detail["courseid"])}
    # Notas ya registradas en Moodle (una sola llamada para toda la tarea).
    registradas = api.get_grades(aid)
    teacher_id = session.get("userid")
    out = []
    for s in subs:
        uid = s.get("userid")
        if uid == teacher_id:
            continue
        g = registradas.get(uid) or {}
        out.append({
            "userid": uid,
            "fullname": enrolled.get(uid, f"userid {uid}"),
            "status": s.get("status"),
            "files": [f["name"] for f in api.submission_files(s)],
            "graded": bool(g),
            "grade": g.get("grade"),
            "max_grade": detail.get("grade"),
            "graded_by": enrolled.get(g.get("grader"), ""),
            "graded_by_me": g.get("grader") == teacher_id,
            "graded_date": g.get("timemodified"),
        })
    return jsonify(out)


@app.route("/api/assignments/<int:aid>/submissions/<int:userid>/grade")
def submission_grade(aid, userid):
    """Detalle de la calificación ya registrada en Moodle para un estudiante."""
    d = api.grade_detail(aid, userid)
    if not d:
        return jsonify({"error": "Sin calificación registrada en Moodle"}), 404
    d["feedback"] = strip_html(d.get("feedback") or "")
    d["gradefordisplay"] = strip_html(d.get("gradefordisplay") or "")
    d["graded_by_me"] = d.get("grader") == session.get("userid")
    return jsonify(d)


@app.route("/api/assignments/<int:aid>/submissions/<int:userid>/files/<path:filename>")
def download_submission_file(aid, userid, filename):
    """Descarga (o sirve desde caché) un archivo que subió el estudiante."""
    filename = os.path.basename(filename)
    subs = api.get_submissions(aid)
    if isinstance(subs, dict):
        return jsonify({"error": str(subs)}), 502
    url = None
    for s in subs:
        if s.get("userid") == userid:
            for f in api.submission_files(s):
                if f["name"] == filename:
                    url = f["url"]
                    break
    if not url:
        return jsonify({"error": "Archivo no encontrado"}), 404
    dest = os.path.join(CACHE_DIR, str(aid), str(userid), filename)
    if not os.path.exists(dest):
        api.download(url, dest)
    return send_file(dest, as_attachment=True, download_name=filename)


@app.route("/api/assignments/<int:aid>/attachments/<path:filename>")
def download_attachment(aid, filename):
    """Descarga (o sirve desde caché) un archivo adjunto de la consigna (guía de la tarea)."""
    filename = os.path.basename(filename)
    detail = assignment_detail(aid)
    if not detail:
        return jsonify({"error": "tarea no encontrada"}), 404
    url = next((a["url"] for a in detail.get("attachments", []) if a["name"] == filename), None)
    if not url:
        return jsonify({"error": "Adjunto no encontrado"}), 404
    dest = os.path.join(CACHE_DIR, "consigna", str(aid), filename)
    if not os.path.exists(dest):
        api.download(url, dest)
    return send_file(dest, as_attachment=True, download_name=filename)


@app.route("/api/rubrics")
def rubrics():
    return jsonify(load_rubrics())


def slugify(name):
    n = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode()
    n = re.sub(r"[^a-zA-Z0-9]+", "_", n.strip().lower()).strip("_")
    return n or uuid.uuid4().hex[:8]


def _write_rubric(rubric):
    rid = re.sub(r"[^a-zA-Z0-9_-]", "", rubric["id"]) or uuid.uuid4().hex[:8]
    rubric["id"] = rid
    with open(os.path.join(RUBRICS_DIR, rid + ".json"), "w", encoding="utf-8") as f:
        json.dump(rubric, f, ensure_ascii=False, indent=2)
    return rubric


@app.route("/api/rubrics", methods=["POST"])
def save_rubric():
    body = request.get_json(silent=True) or {}
    name = (body.get("name") or "").strip()
    if not name:
        return jsonify({"error": "El nombre es obligatorio"}), 400

    levels = []
    for l in body.get("levels") or []:
        lname = (l.get("name") or "").strip()
        if not lname:
            continue
        try:
            pct = float(l.get("points_pct", 0))
        except (TypeError, ValueError):
            pct = 0
        levels.append({"name": lname, "points_pct": pct})

    criteria = []
    for c in body.get("criteria") or []:
        cname = (c.get("name") or "").strip()
        if not cname:
            continue
        try:
            mp = float(c.get("max_points", 0))
        except (TypeError, ValueError):
            mp = 0
        item = {"name": cname, "max_points": mp}
        if levels:
            descs = c.get("descriptors") or {}
            item["descriptors"] = {l["name"]: (descs.get(l["name"]) or "").strip() for l in levels}
        else:
            item["description"] = (c.get("description") or "").strip()
        criteria.append(item)
    if not criteria:
        return jsonify({"error": "Debe tener al menos un criterio"}), 400

    rid = body.get("id") or slugify(name)
    rubric = {"id": rid, "name": name, "description": (body.get("description") or "").strip()}
    if levels:
        rubric["levels"] = levels
    rubric["criteria"] = criteria
    return jsonify(_write_rubric(rubric))


@app.route("/api/rubrics/<rid>", methods=["DELETE"])
def delete_rubric(rid):
    rid = re.sub(r"[^a-zA-Z0-9_-]", "", rid)
    path = os.path.join(RUBRICS_DIR, rid + ".json")
    if os.path.exists(path):
        os.remove(path)
        return jsonify({"ok": True})
    return jsonify({"error": "Rúbrica no encontrada"}), 404


def _norm(s):
    return unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()


def _parse_level_header(h):
    """'Excelente (100%)' -> ('Excelente', 100.0). Si no hay %, devuelve None."""
    h = str(h or "").strip()
    m = re.search(r"(\d+(?:[.,]\d+)?)\s*%", h)
    pct = float(m.group(1).replace(",", ".")) if m else None
    name = re.sub(r"[\(\)]?\s*\d+(?:[.,]\d+)?\s*%\s*[\)]?", "", h).strip() or h
    return name, pct


@app.route("/api/rubrics/parse-excel", methods=["POST"])
def parse_excel():
    f = request.files.get("file")
    if not f:
        return jsonify({"error": "Archivo requerido"}), 400
    filename = f.filename or "rubrica"
    data = f.read()

    name_col = {"criterio", "criterion", "nombre", "name", "aspecto", "indicador", "criterios", "rubrica",
                "seccion", "seccion del informe", "categoria", "dimension", "elemento"}
    desc_col = {"descripcion", "descripción", "description", "detalle", "explicacion", "explicación", "observaciones"}
    pts_col = {"puntos", "puntaje", "pts", "ptos", "nota", "nota maxima", "nota máxima", "max_points", "maximo", "máximo", "valor", "peso", "puntaje maximo"}

    rows = []
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".csv":
        import csv as _csv
        text = data.decode("utf-8-sig", errors="replace")
        rows = [r for r in _csv.reader(io.StringIO(text))]
    else:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        ws = wb.active
        rows = [[("" if c is None else c) for c in r] for r in ws.iter_rows(values_only=True)]

    # 1) localizar la fila de encabezados
    header_idx = None
    for i, row in enumerate(rows):
        norms = {_norm(c) for c in row if str(c or "").strip()}
        n_pct = sum(1 for c in row if re.search(r"\d\s*%", str(c or "")))
        if (norms & pts_col) or (norms & name_col) or n_pct >= 2:
            header_idx = i
            break
    if header_idx is None:
        return jsonify({"error": "No se reconoció una fila de encabezados. La primera fila debe tener los "
                                 "títulos de columna (ej. 'Criterio', 'Pts', 'Excelente (100%)')."}), 400

    header = rows[header_idx]
    cols = {}
    for j, cellname in enumerate(header):
        n = _norm(cellname)
        if n in pts_col and "pts" not in cols:
            cols["pts"] = j
        elif n in desc_col and "desc" not in cols:
            cols["desc"] = j
        elif n in name_col and "name" not in cols:
            cols["name"] = j
    if "name" not in cols:  # primer encabezado no vacío = columna de criterios
        for j, cellname in enumerate(header):
            if str(cellname or "").strip():
                cols["name"] = j
                break

    def get(row, j):
        if j is None or j >= len(row):
            return ""
        v = row[j]
        return ("" if v is None else str(v)).strip()

    # columnas de nivel = las demás con encabezado
    level_cols = [j for j, cellname in enumerate(header)
                  if str(cellname or "").strip() and j not in cols.values()]

    base = os.path.splitext(os.path.basename(filename))[0]

    # ── Formato MATRIZ: criterios × niveles (Excelente / Satisfactorio / Insuficiente) ──
    if len(level_cols) >= 2 and "desc" not in cols:
        levels = []
        for j in level_cols:
            lname, pct = _parse_level_header(header[j])
            levels.append({"name": lname, "points_pct": pct, "col": j})
        if all(l["points_pct"] is None for l in levels):
            n = len(levels)
            for k, l in enumerate(levels):
                l["points_pct"] = round(100 * (n - 1 - k) / (n - 1), 2) if n > 1 else 100
        else:
            for l in levels:
                if l["points_pct"] is None:
                    l["points_pct"] = 0

        criteria = []
        for row in rows[header_idx + 1:]:
            if not row or all(not str(c or "").strip() for c in row):
                continue
            cname = get(row, cols["name"])
            if not cname or _norm(cname) == "total":
                continue
            pts = get(row, cols.get("pts"))
            try:
                mp = float(pts.replace(",", ".")) if pts else 0
            except ValueError:
                mp = 0
            criteria.append({
                "name": cname,
                "max_points": mp,
                "descriptors": {l["name"]: get(row, l["col"]) for l in levels},
            })
        if not criteria:
            return jsonify({"error": "No se encontraron filas de criterios"}), 400
        if not any(c["max_points"] for c in criteria):
            # Sin columna de puntos: peso igual para cada criterio
            for c in criteria:
                c["max_points"] = 1
        clean = [{"name": l["name"], "points_pct": l["points_pct"]} for l in levels]
        return jsonify({"name": base, "description": "", "levels": clean, "criteria": criteria})

    # ── Formato SIMPLE: criterio / descripción / puntos ──
    if "name" not in cols and "pts" not in cols:
        return jsonify({"error": "No se reconocieron columnas. Esperaba 'Criterio', 'Descripción', 'Puntos' "
                                 "o una matriz de criterios por niveles."}), 400
    criteria = []
    for row in rows[header_idx + 1:]:
        if not row or all(not str(c or "").strip() for c in row):
            continue
        cname = get(row, cols.get("name"))
        if not cname or _norm(cname) == "total":
            continue
        pts = get(row, cols.get("pts"))
        try:
            mp = float(pts.replace(",", ".")) if pts else 0
        except ValueError:
            mp = 0
        criteria.append({"name": cname,
                         "description": get(row, cols.get("desc")),
                         "max_points": mp})
    if not criteria:
        return jsonify({"error": "No se encontraron filas de criterios"}), 400
    if not any(c["max_points"] for c in criteria):
        # Sin columna de puntos: peso igual para cada criterio
        for c in criteria:
            c["max_points"] = 1
    return jsonify({"name": base, "description": "", "criteria": criteria})


@app.route("/api/assignments/<int:aid>/preview", methods=["POST"])
def preview(aid):
    body = request.get_json(silent=True) or {}
    rubric_id = body.get("rubric_id")
    rubric = next((r for r in load_rubrics() if r["id"] == rubric_id), None)
    if not rubric:
        return jsonify({"error": "rúbrica no encontrada"}), 400
    detail = assignment_detail(aid)
    if not detail:
        return jsonify({"error": "tarea no encontrada"}), 404

    # Cada docente usa su propia clave de API: el consumo se factura a su cuenta.
    clave = _llm_key()
    if not clave:
        return jsonify({
            "error": "Configura tu clave de API de DeepSeek antes de calificar.",
            "need_api_key": True,
        }), 400

    # Capturar credenciales para el hilo de calificación (no hereda el thread-local).
    token = session["token"]
    site = site_url()
    userid = session.get("userid")
    only = [int(u) for u in (body.get("userids") or [])] or None  # None = todos

    job_id = uuid.uuid4().hex
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "done": 0, "total": 0, "current": None,
                        "results": [], "assignid": aid, "rubric": rubric["name"]}

    def run():
        api.set_auth(token, site, userid)
        def cb(done, total, current=None):
            with JOBS_LOCK:
                JOBS[job_id]["done"] = done
                JOBS[job_id]["total"] = total
                if current is not None:
                    JOBS[job_id]["current"] = current
        try:
            # Consigna enriquecida: descripción de la tarea + archivos adjuntos (guías).
            consigna = grader.build_consigna(aid, detail["intro"], detail.get("attachments"))
            results = grader.grade_submissions(
                aid, consigna, rubric, float(detail["grade"]),
                progress_cb=cb, only_userids=only, api_key=clave)
            with JOBS_LOCK:
                JOBS[job_id]["results"] = results
                JOBS[job_id]["status"] = "done"
        except Exception as e:
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = str(e)

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/jobs/<job_id>")
def job(job_id):
    with JOBS_LOCK:
        j = JOBS.get(job_id)
        if not j:
            return jsonify({"error": "job no encontrado"}), 404
        return jsonify(j)


@app.route("/api/assignments/<int:aid>/publish", methods=["POST"])
def publish(aid):
    body = request.get_json(silent=True) or {}
    grades = body.get("grades", [])
    results = []
    for g in grades:
        uid = g.get("userid")
        grade = g.get("grade")
        feedback = (g.get("feedback") or "").strip()
        try:
            r = api.save_grade(aid, uid, grade, feedback)
            if isinstance(r, dict) and "exception" in r:
                results.append({"userid": uid, "ok": False, "error": r.get("message", str(r))})
            else:
                results.append({"userid": uid, "ok": True})
        except Exception as e:
            results.append({"userid": uid, "ok": False, "error": str(e)})
    return jsonify({"results": results})


@app.route("/")
def index():
    return send_from_directory(app.template_folder, "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    host = os.environ.get("HOST", "0.0.0.0")  # 0.0.0.0 = accesible en toda la red local
    app.run(host=host, port=port, debug=False, threaded=True)
