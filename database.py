# ============================================================
# FACCMA TENIS - Database & JSON loader
# ============================================================

import json
import os

import pymysql

# ------------------------------------------------------------
# MODO: USE_DB=false → lee el JSON sin MySQL
#        USE_DB=true  → usa MySQL (produccion)
# ------------------------------------------------------------
USE_DB = os.getenv("USE_DB", "false").lower() == "true"
JSON_FILE = os.getenv("JSON_FILE", "faccma_full.json")

print(f"[CONFIG] USE_DB={USE_DB} | JSON_FILE={JSON_FILE}")

# ------------------------------------------------------------
# CONFIG DB (usar variables de entorno en AWS)
# ------------------------------------------------------------
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "user": os.getenv("DB_USER", "faccma"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "faccma_tenis"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

# Cache del JSON en memoria (solo modo demo)
_json_data = None


def load_json_data():
    """Carga y cachea el archivo JSON en memoria."""
    global _json_data
    if _json_data is None:
        if not os.path.exists(JSON_FILE):
            raise FileNotFoundError(f"[ERROR] No se encuentra el archivo: {JSON_FILE}")
        with open(JSON_FILE, encoding="utf-8") as f:
            _json_data = json.load(f)
        torneos = _json_data.get("torneos", [])
        print(f"[INFO] JSON cargado: {JSON_FILE} → {len(torneos)} torneos")
        for t in torneos[:5]:
            print(
                f"  → {t.get('torneo')} | {t.get('categoria')} | standings={len(t.get('standings', []))} series={len(t.get('series', []))}"
            )
    return _json_data


def get_db():
    """Retorna una conexion a MySQL (solo se usa si USE_DB=true)."""
    return pymysql.connect(**DB_CONFIG)


def query(sql, params=None):
    """Ejecuta una consulta SQL y retorna todos los resultados."""
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()
