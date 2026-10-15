# Calificador Moodle — aplicación web

La documentación completa está en el **[README principal](../README.md)**.

Aquí vive el código de la aplicación:

- `app.py` — backend Flask (endpoints, trabajos de calificación, rúbricas)
- `grader.py` — motor de calificación (extracción de texto + consulta al modelo)
- `static/` · `templates/` — interfaz web
- `rubrics/` — rúbricas en JSON
- `run.sh` / `run.bat` — lanzadores para macOS-Linux y Windows

## Arranque rápido

```bash
./run.sh          # macOS / Linux
run.bat           # Windows (doble clic)
```

Las credenciales se leen del archivo `.env` en la **raíz del proyecto**. Cópialo de `.env.example` la primera vez.
