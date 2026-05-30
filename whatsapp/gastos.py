"""Control de gasto por usuario — tokens Gemini, rate limiting, alertas diarias."""

import logging
import sqlite3
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("faccma_wa")

DB_PATH = "faccma_wa.db"

# Precios Gemini 2.5 Flash (non-thinking, aproximados)
PRECIO_INPUT        = 0.15  / 1_000_000   # $ por token de entrada
PRECIO_OUTPUT       = 0.60  / 1_000_000   # $ por token de salida
LIMITE_USUARIO_USD  = 2.0                  # Límite de gasto diario por usuario
LIMITE_ALERTA_USD   = 5.0                  # Umbral para alertar al admin
RATE_LIMIT_MENSAJES = 20                   # Mensajes máximos por ventana
RATE_LIMIT_HORAS    = 1                    # Duración de la ventana (horas)


def _conectar(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


def inicializar_tablas(db_path: str = DB_PATH) -> None:
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wa_gastos_diarios (
            telefono      TEXT,
            fecha         TEXT,
            input_tokens  INTEGER DEFAULT 0,
            output_tokens INTEGER DEFAULT 0,
            costo_usd     REAL    DEFAULT 0.0,
            PRIMARY KEY (telefono, fecha)
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wa_log_consultas (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            telefono      TEXT,
            timestamp     TEXT DEFAULT (datetime('now')),
            input_tokens  INTEGER,
            output_tokens INTEGER,
            costo_usd     REAL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS wa_alertas (
            tipo    TEXT,
            fecha   TEXT,
            enviada INTEGER DEFAULT 0,
            PRIMARY KEY (tipo, fecha)
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_wa_log_tel ON wa_log_consultas(telefono)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_wa_log_ts  ON wa_log_consultas(timestamp)")
    conn.commit()
    conn.close()


def _hoy() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def calcular_costo(input_tokens: int, output_tokens: int) -> float:
    return round(input_tokens * PRECIO_INPUT + output_tokens * PRECIO_OUTPUT, 6)


def registrar_uso(telefono: str, input_tokens: int, output_tokens: int, db_path: str = DB_PATH) -> None:
    costo = calcular_costo(input_tokens, output_tokens)
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wa_gastos_diarios (telefono, fecha, input_tokens, output_tokens, costo_usd)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(telefono, fecha) DO UPDATE SET
            input_tokens  = input_tokens  + excluded.input_tokens,
            output_tokens = output_tokens + excluded.output_tokens,
            costo_usd     = costo_usd     + excluded.costo_usd
    """, (telefono, _hoy(), input_tokens, output_tokens, costo))
    cur.execute("""
        INSERT INTO wa_log_consultas (telefono, input_tokens, output_tokens, costo_usd)
        VALUES (?, ?, ?, ?)
    """, (telefono, input_tokens, output_tokens, costo))
    conn.commit()
    conn.close()


def limite_excedido(telefono: str, db_path: str = DB_PATH) -> bool:
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute(
        "SELECT costo_usd FROM wa_gastos_diarios WHERE telefono=? AND fecha=?",
        (telefono, _hoy()),
    )
    fila = cur.fetchone()
    conn.close()
    return (float(fila["costo_usd"]) if fila else 0.0) >= LIMITE_USUARIO_USD


def gasto_total_hoy(db_path: str = DB_PATH) -> float:
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute("SELECT COALESCE(SUM(costo_usd), 0) FROM wa_gastos_diarios WHERE fecha=?", (_hoy(),))
    total = float(cur.fetchone()[0])
    conn.close()
    return round(total, 4)


def alerta_enviada_hoy(db_path: str = DB_PATH) -> bool:
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute("SELECT enviada FROM wa_alertas WHERE tipo='gasto_diario' AND fecha=?", (_hoy(),))
    fila = cur.fetchone()
    conn.close()
    return bool(fila and fila["enviada"])


def marcar_alerta_enviada(db_path: str = DB_PATH) -> None:
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO wa_alertas (tipo, fecha, enviada) VALUES ('gasto_diario', ?, 1)
        ON CONFLICT(tipo, fecha) DO UPDATE SET enviada=1
    """, (_hoy(),))
    conn.commit()
    conn.close()


def obtener_estadisticas(dias: int = 1, db_path: str = DB_PATH) -> list[dict]:
    hoy_utc = datetime.now(timezone.utc).date()
    desde = (hoy_utc - timedelta(days=dias - 1)).isoformat()
    hasta = _hoy()
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute("""
        SELECT
            g.telefono,
            SUM(g.input_tokens)  AS input_tokens,
            SUM(g.output_tokens) AS output_tokens,
            ROUND(SUM(g.costo_usd), 4) AS costo_usd,
            (SELECT COUNT(*) FROM wa_log_consultas l
             WHERE l.telefono = g.telefono
               AND DATE(l.timestamp) BETWEEN ? AND ?) AS consultas,
            (SELECT MAX(l.timestamp) FROM wa_log_consultas l
             WHERE l.telefono = g.telefono) AS ultima_actividad
        FROM wa_gastos_diarios g
        WHERE g.fecha BETWEEN ? AND ?
        GROUP BY g.telefono
        ORDER BY costo_usd DESC
    """, (desde, hasta, desde, hasta))
    filas = cur.fetchall()
    conn.close()
    return [dict(f) for f in filas]


def formatear_estadisticas(stats: list[dict], dias: int = 1) -> str:
    periodo = "HOY" if dias == 1 else f"ÚLTIMOS {dias} DÍAS"
    lineas = [
        f"📊 FACCMA BOT — {periodo} ({_hoy()})",
        "",
        f"{'TELÉFONO':<16} {'MSGS':>5} {'COSTO USD':>10}  ÚLTIMA ACTIVIDAD",
        "─" * 54,
    ]
    total_msgs = 0
    total_costo = 0.0
    for s in stats:
        tel    = (s["telefono"] or "")[-12:]
        msgs   = int(s["consultas"] or 0)
        costo  = float(s["costo_usd"] or 0.0)
        ultima = (s["ultima_actividad"] or "")[:16]
        total_msgs  += msgs
        total_costo += costo
        lineas.append(f"+..{tel:<14} {msgs:>5} ${costo:>9.4f}  {ultima}")
    lineas += ["─" * 54, f"{'TOTAL':<16} {total_msgs:>5} ${total_costo:>9.4f}"]
    return "\n".join(lineas)


def rate_limit_excedido(telefono: str, db_path: str = DB_PATH) -> bool:
    conn = _conectar(db_path)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT COUNT(*) FROM wa_log_consultas
        WHERE telefono = ?
          AND timestamp >= datetime('now', ? || ' hours')
        """,
        (telefono, f"-{RATE_LIMIT_HORAS}"),
    )
    cantidad = int(cur.fetchone()[0])
    conn.close()
    return cantidad >= RATE_LIMIT_MENSAJES
