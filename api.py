"""Helper para la API REST de Moodle (Aula Evirtual UTM). Soporta sesión dinámica."""
import json, os, urllib.parse, urllib.request, threading

_HERE = os.path.dirname(os.path.abspath(__file__))


def _config_path():
    """Ubica config.json: variable MOODLE_CONFIG → junto a api.py → ~/.hermes/moodle/."""
    env = os.environ.get("MOODLE_CONFIG")
    if env and os.path.exists(env):
        return env
    local = os.path.join(_HERE, "config.json")
    if os.path.exists(local):
        return local
    return os.path.expanduser("~/.hermes/moodle/config.json")


def load_env():
    """Carga las credenciales desde un archivo .env si aún no están en el entorno.

    Busca, en orden: .env junto a este archivo (raíz del proyecto), .env dentro de
    webapp/ y ~/.hermes/.env (ubicación estándar de Hermes). No sobreescribe las
    variables que ya vengan definidas en el entorno.
    """
    candidatos = [
        os.path.join(_HERE, ".env"),
        os.path.join(_HERE, "webapp", ".env"),
        os.path.expanduser("~/.hermes/.env"),
    ]
    for ruta in candidatos:
        if not os.path.exists(ruta):
            continue
        for linea in open(ruta, encoding="utf-8", errors="replace"):
            linea = linea.strip()
            if linea.startswith("export "):
                linea = linea[7:].strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            k, v = linea.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_local = threading.local()  # auth por hilo (cada request/thread usa su propia sesión)


def cfg():
    """Lee config.json (opcional). Si no existe devuelve {}."""
    try:
        return json.load(open(_config_path(), encoding="utf-8"))
    except Exception:
        return {}


def site_url():
    """URL del sitio Moodle: variable MOODLE_SITE (.env) o config.json."""
    return (os.environ.get("MOODLE_SITE") or cfg().get("site") or "").rstrip("/")


def set_auth(token, site=None, userid=None):
    """Establece las credenciales de la sesión actual (por hilo)."""
    _local.token = token
    _local.site = site
    _local.userid = userid


def clear_auth():
    _local.token = None
    _local.site = None
    _local.userid = None


def _auth():
    token = getattr(_local, "token", None)
    sitio = getattr(_local, "site", None)
    return token or cfg().get("token"), sitio or site_url()


def current_userid():
    return getattr(_local, "userid", None) or cfg().get("userid")


def _flatten(prefix, obj, out):
    """Aplana dicts/listas anidados a claves estilo moodle: plugindata[x][y]."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}[{k}]", v, out)
    elif isinstance(obj, (list, tuple)):
        for i, item in enumerate(obj):
            _flatten(f"{prefix}[{i}]", item, out)
    else:
        out.append((prefix, str(obj)))


def raw_call(token, site, function, **params):
    base = site.rstrip("/") + "/webservice/rest/server.php"
    post = [
        ("wstoken", token),
        ("wsfunction", function),
        ("moodlewsrestformat", "json"),
    ]
    for k, v in params.items():
        if isinstance(v, (dict, list, tuple)):
            _flatten(k, v, post)
        elif v is not None:
            post.append((k, str(v)))
    body = urllib.parse.urlencode(post).encode()
    req = urllib.request.Request(base, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


def call(function, **params):
    token, site = _auth()
    return raw_call(token, site, function, **params)


def login(username, password, site=None):
    """Obtiene un token de Moodle a partir de usuario/contraseña (servicio móvil)."""
    site = (site or site_url()).rstrip("/")
    data = urllib.parse.urlencode({
        "username": username,
        "password": password,
        "service": "moodle_mobile_app",
    }).encode()
    req = urllib.request.Request(
        site + "/login/token.php", data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        resp = json.loads(r.read().decode())
    if "token" in resp:
        return resp["token"]
    raise RuntimeError(resp.get("error") or resp.get("message") or "Credenciales inválidas")


def get_site_info(token, site=None):
    return raw_call(token, site or site_url(), "core_webservice_get_site_info")


def get_assignments(courseid):
    d = call("mod_assign_get_assignments", courseids=[courseid])
    if isinstance(d, dict) and "exception" in d:
        return d
    for c in d.get("courses", []):
        if c.get("id") == courseid:
            return c.get("assignments", [])
    return []


def get_submissions(assignid):
    d = call("mod_assign_get_submissions", assignmentids=[assignid])
    if isinstance(d, dict) and "exception" in d:
        return d
    return d.get("assignments", [{}])[0].get("submissions", [])


def get_enrolled(courseid):
    return call("core_enrol_get_enrolled_users", courseid=courseid)


def get_courses(userid=None):
    if userid is None:
        userid = current_userid()
    return call("core_enrol_get_users_courses", userid=userid)


def submission_files(sub):
    """Extrae la lista de archivos (dicts con name/url/mime) de una entrega."""
    files = []
    for p in sub.get("plugins", []):
        if p.get("type") == "file":
            for fa in p.get("fileareas", []):
                if fa.get("area") == "submission_files":
                    for f in fa.get("files", []):
                        files.append({
                            "name": f.get("filename"),
                            "url": f.get("fileurl"),
                            "mime": f.get("mimetype"),
                        })
    return files


def save_grade(assignid, userid, grade, feedback):
    """Registra una nota + retroalimentación en Moodle. Devuelve la respuesta cruda."""
    plugindata = {
        "assignfeedbackcomments_editor": {
            "text": feedback,
            "format": 2,  # 2 = texto plano (respeta saltos de línea)
        }
    }
    return call(
        "mod_assign_save_grade",
        assignmentid=assignid,
        userid=userid,
        grade=grade,
        attemptnumber=-1,
        addattempt=0,
        workflowstate="",  # obligatorio en Moodle 4.5; '' = sin flujo de corrección
        applytoall=1,
        plugindata=plugindata,
    )


def get_grades(assignid):
    """Notas ya registradas en Moodle para una tarea: {userid: {grade, grader, timemodified}}.

    Una sola llamada para toda la tarea.
    """
    d = call("mod_assign_get_grades", assignmentids=[assignid])
    if isinstance(d, dict) and "exception" in d:
        return {}
    out = {}
    for asg in d.get("assignments", []):
        if asg.get("assignmentid") != assignid:
            continue
        for g in asg.get("grades", []):
            try:
                out[g["userid"]] = {
                    "grade": float(g.get("grade") or 0),
                    "grader": g.get("grader"),
                    "timemodified": g.get("timemodified"),
                }
            except (TypeError, ValueError, KeyError):
                continue
    return out


def grade_detail(assignid, userid):
    """Detalle de la calificación registrada: nota, quién y cuándo, y el comentario."""
    d = call("mod_assign_get_submission_status", assignid=assignid, userid=userid)
    if isinstance(d, dict) and "exception" in d:
        return None
    fb = d.get("feedback") or {}
    if not fb:
        return None
    grade = fb.get("grade") or {}
    comentario = ""
    for p in fb.get("plugins", []):
        if p.get("type") == "comments":
            for ef in p.get("editorfields") or []:
                if ef.get("name") == "comments":
                    comentario = ef.get("text") or ""
    try:
        nota = float(grade.get("grade") or 0)
    except (TypeError, ValueError):
        nota = 0.0
    return {
        "grade": nota,
        "gradefordisplay": fb.get("gradefordisplay") or "",
        "grader": grade.get("grader"),
        "graded_date": fb.get("gradeddate") or grade.get("timemodified"),
        "feedback": comentario,
    }


def download(url, dest):
    """Descarga un archivo de Moodle usando el token de la sesión actual."""
    token, _site = _auth()
    sep = "&" if "?" in url else "?"
    full = url + sep + "token=" + token
    req = urllib.request.Request(full, headers={"User-Agent": "Hermes-Moodle/1.0"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = r.read()
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    with open(dest, "wb") as f:
        f.write(data)
    return dest
