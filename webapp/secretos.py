"""Almacén cifrado de las claves de API de cada docente.

Las claves se guardan **cifradas** en una base de datos SQLite (AES-128-CBC +
HMAC-SHA256, a través de Fernet). La clave maestra que las descifra vive **fuera**
de esa base de datos: en el `.env` del proyecto, con permisos 600.

Qué protege
    Si alguien obtiene el archivo de la base de datos —un respaldo, una copia,
    un `git add` despistado— no puede leer nada sin la clave maestra.

Qué NO protege
    El robo del equipo completo, donde van la base de datos *y* el `.env`.

Si la clave maestra se pierde o se cambia, las claves guardadas dejan de poder
descifrarse: la aplicación pedirá introducirlas otra vez (no se corrompe nada).
"""
import os
import sqlite3
import threading
import time

from cryptography.fernet import Fernet, InvalidToken

HERE = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(HERE)
ENV = os.path.join(RAIZ, ".env")
RUTA_BD = os.path.join(HERE, "secretos.db")

VARIABLE = "SECRETOS_KEY"

_lock = threading.Lock()
_fernet = None
_tabla_lista = False

_ESQUEMA = """
CREATE TABLE IF NOT EXISTS claves_api (
    userid      INTEGER PRIMARY KEY,
    nombre      TEXT,
    cifrado     BLOB    NOT NULL,
    actualizado INTEGER
)
"""


def _clave_maestra():
    """Devuelve el cifrador. La clave se lee del .env y se crea si no existe."""
    global _fernet
    if _fernet is not None:
        return _fernet

    clave = (os.environ.get(VARIABLE) or "").strip()
    if not clave and os.path.exists(ENV):
        for linea in open(ENV, encoding="utf-8", errors="replace"):
            if linea.strip().startswith(VARIABLE + "="):
                clave = linea.split("=", 1)[1].strip().strip('"').strip("'")
                break

    if not clave:
        # Primera ejecución: se genera una y se guarda junto al resto de credenciales
        clave = Fernet.generate_key().decode()
        nuevo = not os.path.exists(ENV)
        with open(ENV, "a", encoding="utf-8") as f:
            if not nuevo:
                f.write("\n")
            f.write(
                "# Clave maestra para descifrar las claves de API guardadas en secretos.db.\n"
                "# Si se pierde, las claves guardadas dejan de poder leerse (habrá que\n"
                "# volver a introducirlas), pero nada se corrompe.\n"
                f"{VARIABLE}={clave}\n"
            )
        os.chmod(ENV, 0o600)

    os.environ.setdefault(VARIABLE, clave)
    _fernet = Fernet(clave.encode())
    return _fernet


def _conexion():
    global _tabla_lista
    con = sqlite3.connect(RUTA_BD)
    if not _tabla_lista:
        con.execute(_ESQUEMA)
        con.commit()
        try:
            os.chmod(RUTA_BD, 0o600)   # solo el usuario del servidor puede leerla
        except OSError:
            pass
        _tabla_lista = True
    return con


def guardar(userid, nombre, clave):
    """Cifra la clave de un docente y la guarda (o la actualiza)."""
    if not userid or not clave:
        raise ValueError("faltan datos para guardar la clave")
    token = _clave_maestra().encrypt(clave.encode("utf-8"))
    with _lock:
        con = _conexion()
        try:
            con.execute(
                "INSERT INTO claves_api (userid, nombre, cifrado, actualizado) VALUES (?,?,?,?) "
                "ON CONFLICT(userid) DO UPDATE SET nombre=excluded.nombre, "
                "cifrado=excluded.cifrado, actualizado=excluded.actualizado",
                (int(userid), nombre or "", token, int(time.time())),
            )
            con.commit()
        finally:
            con.close()


def obtener(userid):
    """Devuelve la clave descifrada de un docente, o None si no hay o no se puede leer."""
    if not userid:
        return None
    with _lock:
        con = _conexion()
        try:
            fila = con.execute(
                "SELECT cifrado FROM claves_api WHERE userid=?", (int(userid),)
            ).fetchone()
        finally:
            con.close()
    if not fila:
        return None
    try:
        return _clave_maestra().decrypt(fila[0]).decode("utf-8")
    except InvalidToken:
        return None      # la clave maestra cambió: la guardada ya no sirve


def borrar(userid):
    """Elimina la clave guardada de un docente."""
    if not userid:
        return
    with _lock:
        con = _conexion()
        try:
            con.execute("DELETE FROM claves_api WHERE userid=?", (int(userid),))
            con.commit()
        finally:
            con.close()


def hay(userid):
    """¿Tiene este docente una clave guardada?"""
    if not userid:
        return False
    with _lock:
        con = _conexion()
        try:
            return con.execute(
                "SELECT 1 FROM claves_api WHERE userid=?", (int(userid),)
            ).fetchone() is not None
        finally:
            con.close()


def guardados():
    """Cuántas claves hay guardadas (para diagnóstico; nunca devuelve su contenido)."""
    with _lock:
        con = _conexion()
        try:
            return con.execute("SELECT COUNT(*) FROM claves_api").fetchone()[0]
        finally:
            con.close()
