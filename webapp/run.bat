@echo off
REM ============================================================
REM  Calificador Moodle - Lanzador para Windows
REM  Uso: doble clic en este archivo (run.bat)
REM  Las credenciales se leen del archivo .env (ver .env.example)
REM ============================================================
cd /d "%~dp0"

if not exist "..\.env" (
  if not exist ".env" (
    echo.
    echo  AVISO: no se encontro el archivo .env con las credenciales.
    echo         Copia .env.example como .env y rellena tus valores.
    echo.
  )
)

if not exist venv (
  echo.
  echo  Primera ejecucion: creando entorno virtual e instalando dependencias...
  echo  Esto puede tardar 1-2 minutos.
  echo.
  python -m venv venv
  if errorlevel 1 (
    echo.
    echo  ERROR: no se encontro Python. Instala Python 3.10+ desde https://www.python.org/downloads/
    echo  y marca la casilla "Add Python to PATH" al instalar.
    pause
    exit /b 1
  )
  venv\Scripts\python.exe -m pip install --upgrade pip
  venv\Scripts\pip.exe install -r requirements.txt
)

echo.
echo  ============================================================
echo   Calificador Moodle iniciado
echo   Abre en tu navegador:  http://localhost:5050/
echo   Para detenerlo, cierra esta ventana o presiona Ctrl+C
echo  ============================================================
echo.
venv\Scripts\python.exe app.py
pause
