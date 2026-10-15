#!/usr/bin/env bash
# Lanza el Calificador Moodle (macOS / Linux).
# Las credenciales se leen del archivo .env del proyecto (ver .env.example).
cd "$(dirname "$0")"

if [ ! -d venv ]; then
  echo "Creando entorno virtual e instalando dependencias (solo la primera vez)…"
  python3 -m venv venv
  venv/bin/pip install --quiet --upgrade pip
  venv/bin/pip install --quiet -r requirements.txt
fi

if [ ! -f .env ] && [ ! -f ../.env ]; then
  echo "AVISO: no se encontró el archivo .env con las credenciales."
  echo "       Copia .env.example como .env y rellena tus valores."
  echo
fi

exec venv/bin/python app.py
