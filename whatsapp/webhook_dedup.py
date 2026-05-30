"""Idempotencia de webhooks — evita procesar el mismo MessageSid dos veces."""

import logging
import sqlite3

logger = logging.getLogger("faccma_wa")
DB_PATH = "faccma_wa.db"


def _conectar(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def inicializar_tabla(db_path: str = DB_PATH) -> None:
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wa_webhook_dedup (
            message_sid TEXT PRIMARY KEY,
            created_at  TEXT DEFAULT (datetime('now'))
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_wa_dedup_ts ON wa_webhook_dedup(created_at)")
    cur.execute("DELETE FROM wa_webhook_dedup WHERE datetime(created_at) < datetime('now', '-7 days')")
    n = cur.rowcount
    conn.commit()
    conn.close()
    if n:
        logger.info(f"webhook_dedup: eliminadas {n} entradas antiguas")


def reservar_mensaje(message_sid: str, db_path: str = DB_PATH) -> bool:
    sid = (message_sid or "").strip()
    if not sid:
        return True
    conn = _conectar(db_path)
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO wa_webhook_dedup (message_sid) VALUES (?)", (sid,))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        logger.info(f"Webhook duplicado ignorado: {sid[:12]}…")
        return False
    finally:
        conn.close()
