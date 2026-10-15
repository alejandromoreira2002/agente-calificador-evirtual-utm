const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let state = {
  courses: [], rubrics: [], course: null, assignment: null, preview: null,
  selectedRubricId: null, editingRubricId: null,
};

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
  // Un 401 en /api/login significa "credenciales incorrectas", no "sesión expirada":
  // se deja pasar para mostrar el mensaje real que devuelve el servidor.
  if (res.status === 401 && path !== "/api/login") {
    showLogin();
    throw new Error("Sesión expirada");
  }
  if (!res.ok) {
    let msg = res.statusText;
    try { msg = (await res.json()).error || msg; } catch (e) {}
    throw new Error(msg);
  }
  return res.json();
}

function toast(msg, kind = "") {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast " + kind;
  clearTimeout(t._t);
  t._t = setTimeout(() => t.classList.add("hidden"), 4000);
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function fmtDue(ts) {
  if (!ts) return "Sin fecha";
  return new Date(ts * 1000).toLocaleDateString("es-EC", { year: "numeric", month: "short", day: "numeric" });
}

// ─────────────── Inicio ───────────────

async function init() {
  try {
    const me = await api("/api/me");
    enterApp(me);
  } catch (e) {
    showLogin();
  }
}

function showLogin() {
  state.courses = []; state.rubrics = [];
  state.course = null; state.assignment = null; state.preview = null;
  $("#login-screen").classList.remove("hidden");
  $("#course-list").innerHTML = '<p class="muted">Inicia sesión para ver tus cursos.</p>';
  $("#login-error").textContent = "";
  setPasswordVisible(false);   // al volver al login, la contraseña se oculta otra vez
}

// Mostrar / ocultar la contraseña (botón del ojito)
function setPasswordVisible(visible) {
  const input = $("#login-password");
  const btn = $("#toggle-password");
  if (!input || !btn) return;
  input.type = visible ? "text" : "password";
  btn.setAttribute("aria-pressed", String(visible));
  const etiqueta = visible ? "Ocultar contraseña" : "Mostrar contraseña";
  btn.setAttribute("aria-label", etiqueta);
  btn.setAttribute("title", etiqueta);
  btn.querySelector(".icon-eye").classList.toggle("hidden", visible);
  btn.querySelector(".icon-eye-off").classList.toggle("hidden", !visible);
}

async function enterApp(me) {
  $("#login-screen").classList.add("hidden");
  $("#user-label").textContent = me.fullname;
  $("#site-label").textContent = "Aula Evirtual · UTM";
  $("#empty").classList.remove("hidden");
  $("#assignments-view").classList.add("hidden");
  $("#assignment-view").classList.add("hidden");
  try {
    const [courses, rubrics] = await Promise.all([api("/api/courses"), api("/api/rubrics")]);
    state.courses = courses; state.rubrics = rubrics;
    if (rubrics.length) state.selectedRubricId = rubrics[0].id;
    renderCourses();
    updateRubricPicker();
  } catch (e) {
    $("#course-list").innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`;
    toast("Error al cargar: " + e.message, "err");
  }
}

function renderCourses() {
  const el = $("#course-list");
  if (!state.courses.length) { el.innerHTML = '<p class="muted">Sin cursos</p>'; return; }
  el.innerHTML = state.courses.map((c) => `
    <div class="course-item ${state.course?.id === c.id ? 'active' : ''}" data-id="${c.id}">
      ${esc(c.fullname)}
      <span class="short">${esc(c.shortname || "")}</span>
    </div>`).join("");
  $$(".course-item").forEach((n) =>
    n.addEventListener("click", () => selectCourse(+n.dataset.id)));
}

async function selectCourse(cid) {
  state.course = state.courses.find((c) => c.id === cid);
  state.assignment = null; state.preview = null;
  renderCourses();
  $("#empty").classList.add("hidden");
  $("#assignment-view").classList.add("hidden");
  $("#assignments-view").classList.remove("hidden");
  $("#course-name").textContent = state.course.fullname;
  const list = $("#assign-list");
  list.innerHTML = '<p class="muted">Cargando tareas…</p>';
  try {
    const sections = await api(`/api/courses/${cid}/assignments`);
    if (!sections.length) { list.innerHTML = '<p class="muted">Este curso no tiene tareas.</p>'; return; }
    list.innerHTML = sections.map((sec) => `
      <div class="section-box">
        <div class="section-head">${esc(sec.name)} <span class="count">${sec.assignments.length}</span></div>
        <div class="section-assigns">
          ${sec.assignments.map((a) => `
            <div class="assign-item" data-id="${a.id}">
              <div>
                <div class="name">${esc(a.name)}</div>
                <div class="muted small">Nota máx: ${a.grade ?? "—"}</div>
              </div>
              <div class="right">
                ${a.submitted ? `<span class="graded-badge">${a.graded}/${a.submitted} calificados</span>` : ""}
                <span>${fmtDue(a.duedate)}</span>
              </div>
            </div>`).join("")}
        </div>
      </div>`).join("");
    $$(".assign-item").forEach((n) =>
      n.addEventListener("click", () => selectAssignment(+n.dataset.id)));
  } catch (e) {
    list.innerHTML = `<p class="muted">Error: ${esc(e.message)}</p>`;
  }
}

async function selectAssignment(aid) {
  state.assignment = { id: aid }; state.preview = null;
  $("#assignments-view").classList.add("hidden");
  $("#assignment-view").classList.remove("hidden");
  $("#preview-card").classList.add("hidden");
  $("#publish-btn").disabled = true;

  try {
    const [detail, subs] = await Promise.all([
      api(`/api/assignments/${aid}`),
      api(`/api/assignments/${aid}/submissions`),
    ]);
    state.assignment = detail;
    $("#assign-title").textContent = detail.name;
    $("#assign-grade").textContent = "Nota máxima: " + detail.grade;
    $("#assign-due").textContent = "Entrega: " + fmtDue(detail.duedate);
    $("#assign-intro").textContent = detail.intro || "(sin consigna)";
    const atts = detail.attachments || [];
    $("#assign-attachments").innerHTML = atts.length
      ? `📎 <strong>${atts.length} adjunto(s)</strong> de la consigna (se envían a la IA como contexto):` +
        `<div class="files-list">` +
        atts.map((a) => `<a class="file-link" href="/api/assignments/${aid}/attachments/${encodeURIComponent(a.name)}" download>⬇ ${esc(a.name)}</a>`).join("") +
        `</div>`
      : "";

    const sl = $("#students-list");
    if (!subs.length) {
      sl.innerHTML = '<p class="muted">No hay entregas de estudiantes.</p>';
      $("#grade-btn").disabled = true;
    } else {
      sl.innerHTML = `
        <div class="students-head">
          <label><input type="checkbox" id="sel-all-students" checked> <strong>Seleccionar todos</strong></label>
          <span class="muted small" id="sel-count"></span>
        </div>
        <div class="students-list">` +
        subs.map((s) => `
          <label class="student-row">
            <input type="checkbox" class="sel-student" value="${s.userid}" checked>
            <span class="s-name">${esc(s.fullname)}</span>
            <span class="files">${s.files.map(esc).join(", ") || "sin archivos"}</span>
          </label>`).join("") + `</div>`;
      $("#sel-all-students").addEventListener("change", (e) => {
        $$(".sel-student").forEach((cb) => { cb.checked = e.target.checked; });
        updateStudentCount();
      });
      $$(".sel-student").forEach((cb) => cb.addEventListener("change", updateStudentCount));
      updateStudentCount();
    }
    updateRubricPicker();
  } catch (e) {
    toast("Error: " + e.message, "err");
  }
}

// ─────────────── Rúbricas: selector + modal ───────────────

function selectedRubric() {
  return state.rubrics.find((r) => r.id === state.selectedRubricId) || null;
}

function updateRubricPicker() {
  const r = selectedRubric();
  $("#rubric-picker-label").textContent = r ? r.name : "Seleccionar rúbrica";
}

function openRubricModal() {
  $("#rubric-modal").classList.remove("hidden");
  $("#rubric-form").classList.add("hidden");
  $("#rubric-manager").classList.remove("hidden");
  $("#modal-title").textContent = "Gestionar rúbricas";
  renderRubricListModal();
}

function closeRubricModal() {
  $("#rubric-modal").classList.add("hidden");
}

function renderRubricListModal() {
  const el = $("#rubric-list-modal");
  if (!state.rubrics.length) {
    el.innerHTML = '<p class="muted">Aún no hay rúbricas. Crea una nueva o cárgala desde Excel.</p>';
    return;
  }
  el.innerHTML = state.rubrics.map((r) => {
    const active = r.id === state.selectedRubricId;
    return `<div class="rubric-item ${active ? 'active' : ''}">
      <div class="rubric-item-info">
        <div class="rubric-item-name">${esc(r.name)} ${active ? '<span class="pill">en uso</span>' : ''} ${r.levels && r.levels.length ? '<span class="pill lvl">niveles</span>' : ''}</div>
        <div class="muted small">${r.criteria.length} criterios · ${r.criteria.reduce((a, c) => a + (+c.max_points || 0), 0)} pts${r.levels && r.levels.length ? " · " + r.levels.map((l) => esc(l.name)).join(" / ") : ""}</div>
      </div>
      <div class="rubric-item-actions">
        <button class="mini" data-act="use" data-id="${r.id}">Usar</button>
        <button class="mini" data-act="edit" data-id="${r.id}">Editar</button>
        <button class="mini danger" data-act="del" data-id="${r.id}">Eliminar</button>
      </div>
    </div>`;
  }).join("");

  $$(".rubric-item-actions .mini").forEach((b) =>
    b.addEventListener("click", (e) => {
      e.stopPropagation();
      const { act, id } = b.dataset;
      if (act === "use") { state.selectedRubricId = id; updateRubricPicker(); closeRubricModal(); toast("Rúbrica seleccionada"); }
      else if (act === "edit") { editRubric(id); }
      else if (act === "del") { deleteRubric(id); }
    }));
}

function editRubric(id) {
  const r = state.rubrics.find((x) => x.id === id);
  if (!r) return;
  state.editingRubricId = id;
  showRubricForm(r);
}

function showRubricForm(rubric) {
  $("#rubric-manager").classList.add("hidden");
  $("#rubric-form").classList.remove("hidden");
  $("#modal-title").textContent = rubric ? "Editar rúbrica" : "Nueva rúbrica";
  $("#rubric-name").value = rubric?.name || "";
  $("#rubric-desc").value = rubric?.description || "";
  const hasLevels = !!(rubric?.levels && rubric.levels.length);
  renderRubricForm({
    mode: hasLevels ? "levels" : "simple",
    levels: hasLevels ? rubric.levels : [],
    criteria: rubric?.criteria || [],
  });
}

// Lee todo el formulario a un objeto (preserva lo escrito al re-renderizar).
function readForm() {
  const mode = $("#rubric-mode").value;
  const levels = [...$$("#levels-list .level-row")].map((r) => ({
    name: r.querySelector(".lvl-name").value.trim(),
    points_pct: parseFloat(r.querySelector(".lvl-pct").value) || 0,
  }));
  const criteria = [...$$("#criteria-list .criterion-row")].map((r) => {
    const c = {
      name: r.querySelector(".crit-name").value.trim(),
      max_points: parseFloat(r.querySelector(".crit-pts").value) || 0,
    };
    if (mode === "levels") {
      c.descriptors = {};
      r.querySelectorAll(".crit-desc-lvl").forEach((t) => {
        const lname = levels[parseInt(t.dataset.levelIndex, 10)]?.name;
        if (lname) c.descriptors[lname] = t.value;
      });
    } else {
      const d = r.querySelector(".crit-desc");
      c.description = d ? d.value : "";
    }
    return c;
  });
  return { mode, levels, criteria };
}

function renderRubricForm(data) {
  const mode = data.mode || "simple";
  $("#rubric-mode").value = mode;
  $("#levels-block").classList.toggle("hidden", mode !== "levels");

  $("#levels-list").innerHTML = "";
  (data.levels || []).forEach((l) => addLevelRow(l));

  const list = $("#criteria-list");
  list.innerHTML = "";
  const crits = (data.criteria && data.criteria.length) ? data.criteria : [{}];
  crits.forEach((c) => addCriterionRow(c, mode, data.levels || []));
}

function addLevelRow(l = {}) {
  const row = document.createElement("div");
  row.className = "level-row";
  row.innerHTML = `
    <input class="lvl-name" placeholder="Nivel (ej. Excelente)" value="${esc(l.name || "")}">
    <input class="lvl-pct" type="number" min="0" max="100" step="1" placeholder="%" value="${l.points_pct ?? ""}">
    <button class="crit-del" type="button" title="Quitar nivel">✕</button>`;
  row.querySelector(".crit-del").addEventListener("click", () => {
    const d = readForm();
    d.levels.splice([...$$("#levels-list .level-row")].indexOf(row), 1);
    renderRubricForm(d);
  });
  $("#levels-list").appendChild(row);
}

function addCriterionRow(c = {}, mode = "simple", levels = []) {
  const row = document.createElement("div");
  row.className = "criterion-row" + (mode === "levels" ? " with-levels" : "");
  if (mode === "levels") {
    const descs = c.descriptors || {};
    row.innerHTML = `
      <div class="crit-head">
        <input class="crit-name" placeholder="Nombre del criterio" value="${esc(c.name || "")}">
        <input class="crit-pts" type="number" min="0" step="0.1" placeholder="Pts" value="${c.max_points ?? ""}">
        <button class="crit-del" type="button" title="Quitar">✕</button>
      </div>
      <div class="crit-levels">
        ${levels.map((l, i) => `
          <label class="crit-lvl">
            <span>${esc(l.name || "nivel " + (i + 1))} <em class="muted">${l.points_pct ?? 0}%</em></span>
            <textarea class="crit-desc-lvl" data-level-index="${i}" rows="2" placeholder="Descriptor…">${esc(descs[l.name] || "")}</textarea>
          </label>`).join("")}
      </div>`;
  } else {
    row.innerHTML = `
      <input class="crit-name" placeholder="Nombre del criterio" value="${esc(c.name || "")}">
      <input class="crit-desc" placeholder="Descripción (opcional)" value="${esc(c.description || "")}">
      <input class="crit-pts" type="number" min="0" step="0.5" placeholder="Pts" value="${c.max_points ?? ""}">
      <button class="crit-del" type="button" title="Quitar">✕</button>`;
  }
  row.querySelector(".crit-del").addEventListener("click", () => {
    const d = readForm();
    d.criteria.splice([...$$("#criteria-list .criterion-row")].indexOf(row), 1);
    renderRubricForm(d);
  });
  $("#criteria-list").appendChild(row);
}

function collectForm() {
  const name = $("#rubric-name").value.trim();
  if (!name) { toast("Ponle un nombre a la rúbrica", "err"); return null; }
  const d = readForm();
  const criteria = d.criteria.filter((c) => c.name);
  if (!criteria.length) { toast("Añade al menos un criterio", "err"); return null; }
  const out = {
    id: state.editingRubricId || undefined,
    name,
    description: $("#rubric-desc").value.trim(),
    criteria,
  };
  if (d.mode === "levels") {
    const levels = d.levels.filter((l) => l.name);
    if (!levels.length) { toast("Añade al menos un nivel", "err"); return null; }
    out.levels = levels;
  }
  return out;
}

async function saveRubric() {
  const rubric = collectForm();
  if (!rubric) return;
  try {
    const saved = await api("/api/rubrics", { method: "POST", body: JSON.stringify(rubric) });
    state.rubrics = await api("/api/rubrics");
    if (!state.selectedRubricId || !state.rubrics.find((r) => r.id === state.selectedRubricId)) {
      state.selectedRubricId = saved.id;
    }
    state.editingRubricId = null;
    updateRubricPicker();
    openRubricModal(); // vuelve a la lista
    toast("Rúbrica guardada", "ok");
  } catch (e) {
    toast("Error: " + e.message, "err");
  }
}

async function deleteRubric(id) {
  const r = state.rubrics.find((x) => x.id === id);
  if (!confirm(`¿Eliminar la rúbrica "${r?.name}"?`)) return;
  try {
    await api(`/api/rubrics/${id}`, { method: "DELETE" });
    state.rubrics = await api("/api/rubrics");
    if (state.selectedRubricId === id) state.selectedRubricId = state.rubrics[0]?.id || null;
    updateRubricPicker();
    renderRubricListModal();
    toast("Rúbrica eliminada");
  } catch (e) {
    toast("Error: " + e.message, "err");
  }
}

async function uploadExcel(file) {
  if (!file) return;
  const fd = new FormData();
  fd.append("file", file);
  try {
    const res = await fetch("/api/rubrics/parse-excel", { method: "POST", body: fd });
    if (!res.ok) { const j = await res.json().catch(() => ({})); throw new Error(j.error || res.statusText); }
    const parsed = await res.json();
    state.editingRubricId = null;
    showRubricForm(parsed);
    toast("Excel leído. Revisa y guarda.", "ok");
  } catch (e) {
    toast("Error leyendo Excel: " + e.message, "err");
  }
}

function updateStudentCount() {
  const boxes = [...$$(".sel-student")];
  if (!boxes.length) return;
  const n = boxes.filter((cb) => cb.checked).length;
  const el = $("#sel-count");
  if (el) el.textContent = `${n} de ${boxes.length} seleccionado(s)`;
  const btn = $("#grade-btn");
  if (btn) btn.disabled = n === 0;
}

function selectedStudentIds() {
  return [...$$(".sel-student:checked")].map((cb) => +cb.value);
}

// ─────────────── Calificación (agente) ───────────────

async function grade() {
  if (!state.assignment) return;
  const rubric = selectedRubric();
  if (!rubric) { toast("Selecciona o crea una rúbrica primero", "err"); openRubricModal(); return; }
  const userids = selectedStudentIds();
  if (!userids.length) { toast("Selecciona al menos un estudiante", "err"); return; }
  $("#grade-btn").disabled = true;
  $("#grade-btn").innerHTML = '<span class="spinner"></span> Preparando…';
  $("#preview-card").classList.remove("hidden");
  $("#preview-rubric").textContent = rubric.name;
  $("#preview-status").textContent = `Preparando la consigna y ${userids.length} entrega(s)…`;
  $("#preview-table").innerHTML = '<span class="spinner"></span> Trabajando…';
  $("#publish-btn").disabled = true;

  try {
    const { job_id } = await api(`/api/assignments/${state.assignment.id}/preview`, {
      method: "POST", body: JSON.stringify({ rubric_id: rubric.id, userids }),
    });
    pollJob(job_id);
  } catch (e) {
    resetGradeBtn();
    toast("Error: " + e.message, "err");
  }
}

function resetGradeBtn() {
  $("#grade-btn").textContent = "🤖 Calificar con agente";
  updateStudentCount();  // deja el botón activo solo si hay seleccionados
}

async function pollJob(jobId) {
  try {
    const j = await api(`/api/jobs/${jobId}`);
    if (j.status === "running") {
      let msg = `El agente está calificando… ${j.done}/${j.total || "?"} procesadas`;
      if (j.current) msg += ` · ahora: ${j.current}`;
      $("#preview-status").textContent = msg;
      setTimeout(() => pollJob(jobId), 1500);
      return;
    }
    if (j.status === "error") {
      resetGradeBtn();
      $("#preview-status").textContent = "Error: " + (j.error || "desconocido");
      toast("Error de calificación", "err");
      return;
    }
    resetGradeBtn();
    state.preview = j.results;
    renderPreview(j.results);
  } catch (e) {
    resetGradeBtn();
    toast("Error: " + e.message, "err");
  }
}

function renderPreview(results) {
  state.preview = results;
  $("#preview-status").textContent =
    `${results.length} entregas calificadas. Puedes descargar los archivos, editar la nota y la retroalimentación, y elegir a quién publicar.`;
  const aid = state.assignment.id;

  const rowsHtml = results.map((r, i) => {
    const err = r.status === "error";
    const files = (r.files || []).map((f) =>
      `<a class="file-link" href="/api/assignments/${aid}/submissions/${r.userid}/files/${encodeURIComponent(f)}" download>⬇ ${esc(f)}</a>`
    ).join("");
    const crits = (r.criteria || []).map((c) => {
      const max = c.max ?? c.max_points ?? 1;
      const pct = Math.max(0, Math.min(100, (c.score / max) * 100));
      const lvl = c.level ? ` · <span class="lvl-pill">${esc(c.level)}</span>` : "";
      return `<div class="crit">
        <strong>${esc(c.name)}</strong> — ${c.score}/${max}${lvl}
        <div class="bar"><span style="width:${pct}%"></span></div>
        <div class="muted small">${esc(c.comment || "")}</div>
      </div>`;
    }).join("");

    const gradeCell = err
      ? '<span class="grade-badge err">error</span>'
      : `<input type="number" class="edit-grade" data-i="${i}" value="${r.grade}" min="0" max="${r.max_grade}" step="0.1">
         <span class="muted small">/ ${r.max_grade}</span>`;

    return `<tr class="${err ? 'row-err' : ''}">
      <td class="col-chk"><input type="checkbox" class="sel-row" data-i="${i}" ${err ? "disabled" : "checked"}></td>
      <td class="col-student">
        ${esc(r.fullname)}
        <div class="files-list">${files || '<span class="muted small">sin archivos</span>'}</div>
      </td>
      <td class="col-grade">${gradeCell}</td>
      <td class="col-fb">
        <textarea class="edit-fb" data-i="${i}" rows="3" placeholder="Retroalimentación…">${esc(r.feedback || "")}</textarea>
        <button class="criteria-toggle" data-i="${i}">Ver criterios y justificación</button>
        <div class="criteria-detail hidden" id="crit-${i}">
          ${crits}
          <div><strong>Justificación:</strong> ${esc(r.summary || "")}</div>
        </div>
      </td>
    </tr>`;
  }).join("");

  $("#preview-table").innerHTML = `<table class="grades">
    <thead><tr>
      <th class="col-chk"><input type="checkbox" id="sel-all" checked title="Seleccionar todos"></th>
      <th>Estudiante / Archivos</th>
      <th>Nota (editable)</th>
      <th>Retroalimentación (editable)</th>
    </tr></thead>
    <tbody>${rowsHtml}</tbody>
  </table>`;

  $$(".criteria-toggle").forEach((b) =>
    b.addEventListener("click", () => {
      const d = $(`#crit-${b.dataset.i}`);
      d.classList.toggle("hidden");
      b.textContent = d.classList.contains("hidden") ? "Ver criterios y justificación" : "Ocultar detalle";
    }));

  $("#sel-all").addEventListener("change", (e) => {
    $$(".sel-row").forEach((cb) => { if (!cb.disabled) cb.checked = e.target.checked; });
    updatePublishBtn();
  });
  $$(".sel-row").forEach((cb) => cb.addEventListener("change", updatePublishBtn));
  updatePublishBtn();
}

function updatePublishBtn() {
  const n = $$(".sel-row:checked").length;
  const btn = $("#publish-btn");
  btn.disabled = n === 0;
  btn.textContent = `📤 Publicar (${n}) en Moodle`;
}

// ─────────────── Publicar ───────────────

async function publish() {
  if (!state.preview || !state.assignment) return;
  const aid = state.assignment.id;

  // Recoger solo los estudiantes seleccionados, con nota y feedback EDITADOS.
  const grades = [];
  for (const cb of $$(".sel-row:checked")) {
    const i = +cb.dataset.i;
    const r = state.preview[i];
    if (!r || r.status === "error") continue;
    const gradeInput = document.querySelector(`.edit-grade[data-i="${i}"]`);
    const fbInput = document.querySelector(`.edit-fb[data-i="${i}"]`);
    let grade = parseFloat(gradeInput.value);
    if (isNaN(grade)) { toast(`Nota inválida para ${r.fullname}`, "err"); return; }
    grade = Math.max(0, Math.min(grade, r.max_grade));
    grades.push({ userid: r.userid, grade, feedback: (fbInput.value || "").trim() });
  }
  if (!grades.length) { toast("Selecciona al menos un estudiante", "err"); return; }

  if (!confirm(`¿Publicar ${grades.length} calificacion(es) en Moodle? Esta acción escribe notas reales.`)) return;

  const btn = $("#publish-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Publicando…';
  try {
    const { results } = await api(`/api/assignments/${aid}/publish`, {
      method: "POST", body: JSON.stringify({ grades }),
    });
    const ok = results.filter((r) => r.ok).length;
    const fail = results.filter((r) => !r.ok).length;
    toast(`Publicado: ${ok} ok, ${fail} con error.`, fail ? "err" : "ok");
    if (fail) {
      const errs = results.filter((r) => !r.ok).map((r) => r.error).join("; ");
      $("#preview-status").textContent = "Algunas notas no se publicaron: " + errs;
    }
  } catch (e) {
    toast("Error al publicar: " + e.message, "err");
  } finally {
    updatePublishBtn();
  }
}

// ─────────────── wire-up ───────────────

$("#back-btn").addEventListener("click", () => selectCourse(state.course.id));
$("#grade-btn").addEventListener("click", grade);
$("#publish-btn").addEventListener("click", publish);

$("#rubric-picker-btn").addEventListener("click", openRubricModal);
$("#modal-close").addEventListener("click", closeRubricModal);
$("#rubric-modal").addEventListener("click", (e) => { if (e.target.id === "rubric-modal") closeRubricModal(); });

$("#new-rubric-btn").addEventListener("click", () => { state.editingRubricId = null; showRubricForm(); });
$("#add-criterion-btn").addEventListener("click", () => {
  const d = readForm(); d.criteria.push({}); renderRubricForm(d);
});
$("#add-level-btn").addEventListener("click", () => {
  const d = readForm(); d.levels.push({ name: "", points_pct: 0 }); renderRubricForm(d);
});
$("#rubric-mode").addEventListener("change", () => {
  const d = readForm(); d.mode = $("#rubric-mode").value; renderRubricForm(d);
});
$("#save-rubric-btn").addEventListener("click", saveRubric);
$("#cancel-rubric-btn").addEventListener("click", openRubricModal);

$("#upload-excel-btn").addEventListener("click", () => $("#excel-input").click());
$("#excel-input").addEventListener("change", (e) => {
  uploadExcel(e.target.files[0]);
  e.target.value = "";
});

$("#toggle-password").addEventListener("click", () => {
  setPasswordVisible($("#login-password").type === "password");
  $("#login-password").focus();
});

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const username = $("#login-username").value.trim();
  const password = $("#login-password").value;
  if (!username || !password) { $("#login-error").textContent = "Ingresa usuario y contraseña"; return; }
  $("#login-error").textContent = "";
  const btn = $("#login-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Entrando…';
  try {
    const me = await api("/api/login", { method: "POST", body: JSON.stringify({ username, password }) });
    $("#login-password").value = "";
    enterApp(me);
  } catch (err) {
    $("#login-error").textContent = err.message;
  } finally {
    btn.disabled = false;
    btn.textContent = "Iniciar sesión";
  }
});

$("#logout-btn").addEventListener("click", async () => {
  try { await api("/api/logout", { method: "POST" }); } catch (e) {}
  showLogin();
});

init();
