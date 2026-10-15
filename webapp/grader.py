"""Motor de calificación: extrae texto de las entregas y las evalúa con el LLM."""
import json, os, re, subprocess, sys, tempfile, threading, time

PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PARENT)
import api  # noqa: E402

import requests  # noqa: E402

MAX_CHARS = 30000  # tope de texto de la entrega enviado al LLM


def load_env():
    """Carga las credenciales desde el .env del proyecto (ver api.load_env)."""
    api.load_env()


LLM_TIMEOUT = 75          # segundos de espera máxima por respuesta del modelo
LLM_INTENTOS = 2          # reintentos ante fallo/timeout


def _post_con_limite(url, payload, headers, segundos):
    """POST con límite de tiempo DURO.

    `requests` aplica su timeout a cada lectura de socket, pero si el servidor
    gotea datos poco a poco el contador se reinicia en cada lectura y la petición
    puede quedarse colgada indefinidamente. Aquí ejecutamos la petición en un hilo
    aparte y la abandonamos si excede el límite, para que la calificación continúe.
    """
    caja = {}

    def trabajo():
        try:
            caja["r"] = requests.post(url, json=payload, headers=headers,
                                      timeout=(10, segundos))
        except Exception as e:
            caja["e"] = e

    hilo = threading.Thread(target=trabajo, daemon=True)
    hilo.start()
    hilo.join(segundos + 10)
    if hilo.is_alive():
        raise TimeoutError("el modelo no completó la respuesta en %ss" % segundos)
    if "e" in caja:
        raise caja["e"]
    return caja["r"]


def llm_json(messages, temperature=0.2, max_retries=None):
    load_env()
    base = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    key = os.environ.get("DEEPSEEK_API_KEY", "")
    model = os.environ.get("GRADER_MODEL", "deepseek-v4-flash")
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "response_format": {"type": "json_object"},
        "thinking": {"type": "disabled"},  # DeepSeek V4: sin razonamiento, respuesta directa
        "max_tokens": 4000,                # acota la salida
    }
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    intentos = max_retries or LLM_INTENTOS
    last = None
    for attempt in range(intentos):
        try:
            r = _post_con_limite(base + "/chat/completions", payload, headers, LLM_TIMEOUT)
            if r.status_code in (429, 500, 502, 503):
                last = RuntimeError("HTTP %s" % r.status_code)
                time.sleep(min(2 ** attempt, 8))
                continue
            r.raise_for_status()
            content = (r.json()["choices"][0]["message"].get("content") or "").strip()
            if not content:
                # El modelo gastó los tokens "pensando" y no devolvió contenido
                last = RuntimeError("respuesta vacía del modelo")
                time.sleep(min(2 ** attempt, 8))
                continue
            return _parse_json(content)
        except Exception as e:
            last = e
            time.sleep(min(2 ** attempt, 8))
    raise RuntimeError(f"El agente no respondió tras {intentos} intentos ({last})")


def _parse_json(text):
    """Extrae el primer objeto JSON del texto (tolera fences de markdown)."""
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            return json.loads(m.group(0))
        raise


# ───────────────────────── Extracción de texto ─────────────────────────

def _extract_pdf(path):
    import fitz  # pymupdf
    doc = fitz.open(path)
    parts = []
    for page in doc:
        t = page.get_text()
        if t.strip():
            parts.append(t)
    return "\n".join(parts)


def _extract_docx(path):
    from docx import Document
    d = Document(path)
    return "\n".join(p.text for p in d.paragraphs if p.text.strip())


def _run_extractor(path, outdir):
    """Extrae un archivo comprimido probando los extractores disponibles (multiplataforma)."""
    import shutil
    candidates = [
        ["bsdtar", "-xf", path, "-C", outdir],           # macOS / Linux
        ["tar", "-xf", path, "-C", outdir],              # Windows 10+ (tar.exe == bsdtar)
        ["7z", "x", "-y", f"-o{outdir}", path],          # 7-Zip
        ["7za", "x", "-y", f"-o{outdir}", path],         # 7-Zip (versión ligera)
        ["unar", "-o", outdir, path],                    # The Unarchiver (macOS)
        ["unrar", "x", "-y", path, outdir + os.sep],     # unrar
    ]
    for cmd in candidates:
        if shutil.which(cmd[0]):
            try:
                r = subprocess.run(cmd, capture_output=True)
                if r.returncode == 0:
                    return True
            except Exception:
                continue
    return False


def _extract_archive(path, ext):
    outdir = tempfile.mkdtemp(prefix="moodle_extract_")
    try:
        if ext == ".zip":
            import zipfile
            with zipfile.ZipFile(path) as z:
                z.extractall(outdir)
        else:  # .rar y otros formatos
            _run_extractor(path, outdir)
        chunks = []
        for root, _dirs, files in os.walk(outdir):
            for fn in files:
                fp = os.path.join(root, fn)
                try:
                    chunks.append(f"[ARCHIVO: {fn}]\n" + extract_text(fp, fn))
                except Exception:
                    chunks.append(f"[ARCHIVO: {fn}] (no se pudo leer)")
        return "\n\n".join(chunks)
    finally:
        import shutil
        shutil.rmtree(outdir, ignore_errors=True)


_TEXT_EXTS = {".txt", ".py", ".md", ".html", ".htm", ".css", ".js", ".json",
              ".xml", ".csv", ".ipynb", ".c", ".cpp", ".java", ".r", ".sql"}


def extract_text(path, filename):
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return _extract_pdf(path)
    if ext == ".docx":
        return _extract_docx(path)
    if ext in (".rar", ".zip"):
        return _extract_archive(path, ext)
    if ext in _TEXT_EXTS:
        return open(path, encoding="utf-8", errors="replace").read()
    return ""


# ───────────────────────── Calificación ─────────────────────────

def _fmt_nota(v):
    """Número con coma decimal y sin ceros sobrantes: 2.75 → «2,75», 3.0 → «3»."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return "—"
    texto = ("%.2f" % f).rstrip("0").rstrip(".")
    return (texto or "0").replace(".", ",")


def detalle_criterios(criteria, grade, max_grade):
    """Detalle por criterio (nota obtenida y por qué) para la retroalimentación.

    Se compone en Python, no por el modelo: así el número que ve el estudiante
    es siempre el mismo que el que se registra en Moodle.
    """
    if not criteria:
        return ""
    lineas = ["Detalle por criterio:"]
    for c in criteria:
        nombre = (c.get("name") or "Criterio").strip()
        puntos = _fmt_nota(c.get("score"))
        tope = _fmt_nota(c.get("max"))
        nivel = (c.get("level") or "").strip()
        encabezado = (f"• {nombre} — {nivel} ({puntos}/{tope})" if nivel
                      else f"• {nombre} — {puntos}/{tope}")
        comentario = (c.get("comment") or "").strip()
        lineas.append(f"{encabezado}: {comentario}" if comentario else encabezado)
    lineas.append(f"Nota final: {_fmt_nota(grade)} / {_fmt_nota(max_grade)}")
    return "\n".join(lineas)


def grade_one(consigna, rubric, max_grade, text, student_name=""):
    """Devuelve dict con criterios puntuados, nota escalada, justificación y feedback.

    Dos modos:
      - Simple: cada criterio se puntúa 0..max_points.
      - Por niveles: cada criterio elige uno de los niveles (con su % de puntos).
    """
    levels = rubric.get("levels") or []
    total_max = sum(c["max_points"] for c in rubric["criteria"])

    if len(text) > MAX_CHARS:
        shown = text[:MAX_CHARS] + "\n\n[NOTA: entrega truncada por longitud]"
    else:
        shown = text

    if levels:
        # ── Modo POR NIVELES ──
        lines = []
        for c in rubric["criteria"]:
            lines.append(f"- {c['name']} (máx {c['max_points']}):")
            descs = c.get("descriptors") or {}
            for l in levels:
                lines.append(f"    • {l['name']} ({l['points_pct']:g}%): {descs.get(l['name'], '')}")
        rubric_desc = "\n".join(lines)
        level_names = ", ".join(f'"{l["name"]}"' for l in levels)

        system = (
            "Eres un asistente de calificación académica. Evalúas entregas de estudiantes "
            "con objetividad y criterio técnico, usando una rúbrica POR NIVELES. "
            "Para cada criterio debes elegir EXACTAMENTE UNO de los niveles disponibles, "
            "según cuál describa mejor el desempeño observado. Respondes SIEMPRE con un único "
            "objeto JSON válido, sin texto adicional, con esta estructura:\n"
            '{"criteria":[{"name":"...","level":"<nivel elegido>","comment":"breve justificación"}],'
            '"summary":"justificación general de la nota",'
            '"feedback":"retroalimentación para el estudiante (2-4 frases)"}\n'
            f"El campo level debe ser exactamente uno de: {level_names}."
        )
        user = (
            f"CONSIGNA DE LA TAREA:\n{consigna}\n\n"
            f"RÚBRICA \"{rubric['name']}\" (por niveles):\n{rubric_desc}\n\n"
            f"ESTUDIANTE: {student_name or 'anónimo'}\n\n"
            f"CONTENIDO DE LA ENTREGA:\n{shown}\n\n"
            "Evalúa la entrega y devuelve el JSON con el nivel elegido en cada criterio."
        )
        data = llm_json([{"role": "system", "content": system},
                         {"role": "user", "content": user}])

        lvl_map = {l["name"].strip().lower(): l for l in levels}
        rub_by_name = {c["name"].strip().lower(): c for c in rubric["criteria"]}
        earned = 0.0
        criteria = []
        for i, c in enumerate(data.get("criteria", [])):
            cname = (c.get("name") or "").strip()
            rc = rub_by_name.get(cname.lower())
            if rc is None and i < len(rubric["criteria"]):
                rc = rubric["criteria"][i]  # fallback posicional
            mp = float(rc["max_points"]) if rc else 0.0
            chosen = (c.get("level") or "").strip()
            lv = lvl_map.get(chosen.lower())
            pct = float(lv["points_pct"]) if lv else 0.0
            score = round(mp * pct / 100.0, 2)
            earned += score
            criteria.append({
                "name": cname or (rc["name"] if rc else ""),
                "level": lv["name"] if lv else chosen,
                "score": score,
                "max": mp,
                "comment": c.get("comment", ""),
            })
    else:
        # ── Modo SIMPLE ──
        criteria_desc = "\n".join(
            f"- {c['name']} (0-{c['max_points']}): {c.get('description', '')}"
            for c in rubric["criteria"]
        )
        system = (
            "Eres un asistente de calificación académica. Evalúas entregas de estudiantes "
            "con objetividad y criterio técnico. Respondes SIEMPRE con un único objeto JSON válido, "
            "sin texto adicional, con exactamente esta estructura:\n"
            '{"criteria":[{"name":"...","score":0,"comment":"breve justificación"}],'
            '"summary":"justificación general de la nota",'
            '"feedback":"retroalimentación para el estudiante (2-4 frases)"}\n'
            "El campo score de cada criterio es un número entre 0 y su máximo. "
            "No calcules la nota final; solo puntúa cada criterio."
        )
        user = (
            f"CONSIGNA DE LA TAREA:\n{consigna}\n\n"
            f"RÚBRICA \"{rubric['name']}\":\n{criteria_desc}\n"
            f"(Total de puntos de la rúbrica: {total_max})\n\n"
            f"ESTUDIANTE: {student_name or 'anónimo'}\n\n"
            f"CONTENIDO DE LA ENTREGA:\n{shown}\n\n"
            "Evalúa la entrega contra la consigna y la rúbrica y devuelve el JSON."
        )
        data = llm_json([{"role": "system", "content": system},
                         {"role": "user", "content": user}])

        criteria = data.get("criteria", [])
        rub_max = {c["name"].strip().lower(): c["max_points"] for c in rubric["criteria"]}
        earned = 0.0
        for i, c in enumerate(criteria):
            mx = rub_max.get((c.get("name") or "").strip().lower())
            if mx is None and i < len(rubric["criteria"]):
                mx = rubric["criteria"][i]["max_points"]  # fallback posicional
            c["max"] = mx if mx is not None else 1
            try:
                score = max(0.0, min(float(c.get("score", 0)), float(mx or 0)))
            except (TypeError, ValueError):
                score = 0.0
            c["score"] = round(score, 2)
            earned += score

    if total_max > 0:
        grade = round((earned / total_max) * max_grade, 2)
    else:
        grade = 0.0
    grade = max(0.0, min(grade, float(max_grade)))

    # La retroalimentación que verá el estudiante incluye el desglose: qué obtuvo
    # en cada criterio y el porqué. El docente puede editarla antes de publicar.
    feedback = (data.get("feedback") or "").strip()
    detalle = detalle_criterios(criteria, grade, max_grade)
    if detalle:
        feedback = f"{feedback}\n\n{detalle}".strip()

    return {
        "criteria": criteria,
        "earned": round(earned, 2),
        "rubric_max": total_max,
        "grade": grade,
        "max_grade": max_grade,
        "summary": data.get("summary", ""),
        "feedback": feedback,
    }


def build_consigna(aid, intro, attachments):
    """Consigna completa = descripción de la tarea + texto de sus archivos adjuntos (guías)."""
    parts = [(intro or "").strip()]
    for att in attachments or []:
        name = att.get("name") or "adjunto"
        url = att.get("url")
        if not url:
            continue
        try:
            dest = os.path.join(PARENT, "webapp", "cache", "consigna", str(aid), name)
            api.download(url, dest)
            txt = extract_text(dest, name).strip()
            parts.append(f"[ADJUNTO DE LA TAREA: {name}]\n{txt}" if txt
                         else f"[ADJUNTO: {name}] (sin texto legible)")
        except Exception as e:
            parts.append(f"[ADJUNTO: {name}] (no se pudo leer: {e})")
    return "\n\n".join(p for p in parts if p.strip())


def grade_submissions(assignid, consigna, rubric, max_grade, progress_cb=None, only_userids=None):
    """Descarga y califica las entregas de una tarea (solo las de `only_userids` si se indica)."""
    subs = api.get_submissions(assignid)
    if isinstance(subs, dict):
        raise RuntimeError(str(subs))

    enrolled = {u["id"]: u.get("fullname", u.get("username"))
                for u in api.get_enrolled(_course_of(assignid))}
    teacher_id = api.current_userid()

    only = set(only_userids) if only_userids else None
    targets = []
    for s in subs:
        uid = s.get("userid")
        if uid == teacher_id:
            continue
        if only is not None and uid not in only:
            continue
        targets.append(s)

    total = len(targets)
    if progress_cb:
        progress_cb(0, total, None)   # informa el total de inmediato

    results = []
    pendientes = []          # los que fallaron, para reintentarlos al final
    workdir = os.path.join(PARENT, "webapp", "cache", str(assignid))
    done = 0
    for s in targets:
        uid = s.get("userid")
        name = enrolled.get(uid, f"userid {uid}")
        if progress_cb:
            progress_cb(done, total, name)   # quién se está calificando ahora
        files = api.submission_files(s)
        texts = []
        filenames = []
        for f in files:
            try:
                dest = os.path.join(workdir, f"{uid}", f["name"])
                api.download(f["url"], dest)
                texts.append(extract_text(dest, f["name"]))
                filenames.append(f["name"])
            except Exception as e:
                texts.append(f"[no se pudo leer {f['name']}: {e}]")
                filenames.append(f["name"] + " (error)")

        full = "\n\n".join(t for t in texts if t.strip())
        if not full.strip():
            full = "(sin contenido legible)"
        try:
            g = grade_one(consigna, rubric, max_grade, full, name)
            status = "ok"
        except Exception as e:
            g = {"grade": None, "summary": f"Error de calificación: {e}",
                 "feedback": "", "criteria": []}
            status = "error"
        item = {
            "userid": uid,
            "fullname": name,
            "files": filenames,
            "status": status,
            **g,
        }
        results.append(item)
        if status == "error":
            pendientes.append((item, name, full))
        done += 1
        if progress_cb:
            progress_cb(done, total, None)
        time.sleep(1.5)   # pausa breve: evita saturar el servicio del modelo

    # Segunda pasada: los cuelgues del proveedor suelen ser transitorios.
    for item, name, full in pendientes:
        if progress_cb:
            progress_cb(done, total, "reintentando: " + name)
        time.sleep(3)
        try:
            g = grade_one(consigna, rubric, max_grade, full, name)
            item.update(g)
            item["status"] = "ok"
        except Exception as e:
            item["summary"] = f"Error de calificación (tras reintento): {e}"
        if progress_cb:
            progress_cb(done, total, None)
    return results


def _course_of(assignid):
    """Encuentra el curso al que pertenece una tarea (para listar matriculados)."""
    courses = api.get_courses()  # usa el usuario de la sesión actual
    if isinstance(courses, dict):
        return 0
    for c in courses:
        assigns = api.get_assignments(c["id"])
        if isinstance(assigns, dict):
            continue
        if any(a["id"] == assignid for a in assigns):
            return c["id"]
    return 0
