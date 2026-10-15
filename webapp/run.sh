#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
#  Calificador Moodle — lanzador para Linux y macOS
#  Las credenciales se leen del archivo .env (ver .env.example)
# ─────────────────────────────────────────────────────────────
set -u
cd "$(dirname "$0")" || exit 1

MIN_MAYOR=3
MIN_MENOR=10

# ── 1) ¿Hay Python y es la versión suficiente? ──
if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: no se encontró 'python3'."
  echo "  Debian/Ubuntu : sudo apt install python3 python3-venv"
  echo "  Fedora/RHEL   : sudo dnf install python3"
  echo "  Arch/Manjaro  : sudo pacman -S python"
  echo "  macOS         : brew install python   (o descárgalo de python.org)"
  exit 1
fi

VERSION=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])')
SUFICIENTE=$(python3 -c "import sys; print(1 if sys.version_info >= ($MIN_MAYOR, $MIN_MENOR) else 0)")
if [ "$SUFICIENTE" != "1" ]; then
  echo "ERROR: se necesita Python $MIN_MAYOR.$MIN_MENOR o superior (tienes $VERSION)."
  exit 1
fi
echo "Python $VERSION detectado."

# ── 2) Entorno virtual y dependencias ──
if [ ! -d venv ]; then
  echo "Creando el entorno virtual (solo la primera vez)…"
  if ! python3 -m venv venv 2>/tmp/calificador_venv_error.txt; then
    echo "ERROR: no se pudo crear el entorno virtual."
    echo "En Debian/Ubuntu suele faltar el paquete:  sudo apt install python3-venv"
    echo "--- detalle ---"
    cat /tmp/calificador_venv_error.txt 2>/dev/null
    exit 1
  fi
  venv/bin/pip install --quiet --upgrade pip
  echo "Instalando dependencias…"
  if ! venv/bin/pip install --quiet -r requirements.txt; then
    echo "ERROR: falló la instalación de dependencias."
    exit 1
  fi
fi

# ── 3) ¿Están las credenciales? ──
if [ ! -f .env ] && [ ! -f ../.env ]; then
  echo
  echo "AVISO: no se encontró el archivo .env con las credenciales."
  echo "       Cópialo de la plantilla y rellena tus valores:"
  echo "         cp ../.env.example ../.env"
  echo
fi

# ── 4) Arrancar ──
IP=$( (ipconfig getifaddr en0 2>/dev/null) || (hostname -I 2>/dev/null | awk '{print $1}') || true)
echo "Iniciando el Calificador Moodle…"
[ -n "${IP:-}" ] && echo "  (en la red local: http://$IP:5050/)"
exec venv/bin/python app.py
