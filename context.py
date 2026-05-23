# ============================================================
# FACCMA TENIS - Context builder para Gemini
# ============================================================

import json
import re

from database import USE_DB, load_json_data, query

# ------------------------------------------------------------
# SYSTEM PROMPT
# ------------------------------------------------------------
SYSTEM_PROMPT = """Sos el asistente oficial de la Liga Macabea de Tenis FACCMA.
Respondes UNICAMENTE con datos de la base de datos que te proporcionamos en cada consulta.
Si algo no esta en los datos, decis "no tengo esa informacion en la base de datos".
Nunca inventas datos. Respondes en español, de forma concisa y clara.

REGLAMENTO CLAVE:
- Partido ganado: 2 puntos. Partido perdido: 1 punto. WO: -1 punto.
- Desempate: series ganadas > parciales favor > dif sets > dif games > dobles 1 ganados > resultado entre ambos.
- Cada serie: 1 single + 2 dobles (o 3 dobles en +48 y categorias femeninas).
- Cada parcial: 2 sets. Igualdad: super tie-break a 10 puntos.
- Inscripciones: hasta la 4ta fecha. Jugadores prestados: max 2 partidos sin clasificar.
- WO en 2 partidos seguidos o 3 en el torneo: descalificacion del equipo.
- Contacto FACCMA: tenis.padel@faccma.org | Coordinador: Prof. Daniel Vallina.

Categorias Caballeros (orden): 1ra, Intermedia, 2da, 3ra, +48A, +48B.
Categorias Damas (orden): 1ra, Intermedia, 2da, 3ra A, 3ra B, 3ra C1, 3ra C2.
"""

# ------------------------------------------------------------
# DB SCHEMA - descripcion para que Gemini genere SQL correcto
# ------------------------------------------------------------
DB_SCHEMA = """
Base de datos PostgreSQL - FACCMA Tenis.

TABLAS:

torneos(torneo_id PK, source_torneo_id, nombre VARCHAR, fecha_generacion DATE, fuente TEXT)
  Ejemplo: nombre = 'Tenis Apertura 2026'

categorias(categoria_id PK, torneo_id FK->torneos, source_categoria_id, source_nivel_id, nombre VARCHAR)
  Ejemplo: nombre = 'Caballeros Libre - Tercera', 'Damas Libre - Primera', 'Caballeros +48 - A'

equipos(equipo_id PK, categoria_id FK->categorias, source_equipo_id, nombre VARCHAR)
  Ejemplo: nombre = 'HACOAJ-P', 'CISSAB-K', 'MI REFUGIO-A'

jugadores(jugador_id PK, equipo_id FK->equipos, nombre VARCHAR, edad SMALLINT)
  IMPORTANTE: nombre en formato 'APELLIDO, NOMBRE'
  Ejemplo: 'HOLCMAN, DANIEL', 'RUDY, DANIELA', 'GOLA, DANIEL'
  Para buscar por nombre usar ILIKE con % en ambos lados.

tabla_posiciones(tabla_posicion_id PK, categoria_id FK, equipo_id FK,
  posicion SMALLINT, series_jugadas SMALLINT, series_ganadas SMALLINT,
  parciales_favor SMALLINT, diferencia_sets INT, diferencia_games INT, puntos SMALLINT)

partidos(partido_id PK, categoria_id FK, source_serie_id,
  fecha DATE, hora TIME,
  local_nombre VARCHAR, visitante_nombre VARCHAR,
  local_equipo_id FK->equipos, visitante_equipo_id FK->equipos,
  score_text VARCHAR, sets_local SMALLINT, sets_visitante SMALLINT,
  estado VARCHAR CHECK IN ('A CONFIRMAR','CONFIRMADO','PENDIENTE','REPROGRAMADO'),
  sede VARCHAR)
  - PENDIENTE / REPROGRAMADO = proximos partidos a jugar
  - CONFIRMADO / 'A CONFIRMAR' = partidos ya jugados (resultados)
  - sets_local / sets_visitante = parciales ganados por cada equipo

partidos_individuales(id PK, id_serie INTEGER,
  torneo TEXT, anio INTEGER, categoria TEXT, zona TEXT,
  equipo_local TEXT, equipo_visitante TEXT,
  tipo TEXT,            -- 'Single 1', 'Doble 1', 'Doble 2', 'Doble 3'
  jugador_local TEXT,   -- nombre(s) ABREVIADO: 'APELLIDO, N.' o 'AP1, N. / AP2, N.' en dobles
  jugador_visitante TEXT,
  score TEXT,           -- ej: '6-3, 7-5'
  ganador TEXT,         -- 'L' = local ganó, 'V' = visitante ganó
  estado TEXT)          -- 'Finalizado', 'WO', etc.
  !! CRITICO: jugador_local y jugador_visitante usan APELLIDO + INICIAL (ej: 'HOLCMAN, D.' NO 'HOLCMAN, DANIEL')
  !! Para buscar por apellido SIEMPRE usar solo el apellido: WHERE jugador_local ILIKE '%HOLCMAN%' OR jugador_visitante ILIKE '%HOLCMAN%'
  Para saber si ganó: si ganador='L' y está en jugador_local → ganó. Si ganador='V' y está en jugador_visitante → ganó.

RELACIONES CLAVE:
  jugador -> equipo -> categoria -> torneo
  partido -> categoria -> torneo
  tabla_posiciones -> equipo + categoria
  partidos_individuales.id_serie -> partidos.source_serie_id (referencia, no FK estricta)
"""

# ------------------------------------------------------------
# SEGURIDAD: validacion SQL antes de ejecutar
# ------------------------------------------------------------
_FORBIDDEN = re.compile(
    r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|TRUNCATE|CREATE|GRANT|REVOKE|COPY|VACUUM|EXEC|CALL)\b",
    re.IGNORECASE,
)


def validate_and_run(sql: str) -> list:
    """Valida que el SQL sea un SELECT seguro y lo ejecuta."""
    sql = sql.strip().rstrip(";")
    if not re.match(r"^\s*SELECT\b", sql, re.IGNORECASE):
        raise ValueError("Solo se permiten consultas SELECT")
    if _FORBIDDEN.search(sql):
        raise ValueError("La consulta contiene operaciones no permitidas")
    if not re.search(r"\bLIMIT\b", sql, re.IGNORECASE):
        sql += " LIMIT 100"
    # psycopg2 interpreta % como format specifier — escapar para que llegue literal a PostgreSQL
    sql = sql.replace("%", "%%")
    return query(sql)


# ------------------------------------------------------------
# MODO JSON (fallback cuando USE_DB=false)
# ------------------------------------------------------------
def build_context_from_json() -> str:
    """Construye el contexto leyendo datos desde el JSON en memoria (modo demo)."""
    data = load_json_data()
    torneos = data.get("torneos", [])

    standings_list, proximos_list, resultados_list, jugadores_list, partidos_list = [], [], [], [], []

    for t in torneos:
        torneo_nombre = t.get("torneo", "")
        categoria = t.get("categoria", "")
        anio = t.get("anio", "")
        tipo = t.get("tipo", "")

        for s in t.get("standings", []):
            standings_list.append({
                "torneo": torneo_nombre, "anio": anio, "tipo": tipo,
                "categoria": categoria, "pos": s.get("pos"), "equipo": s.get("equipo"),
                "pts": s.get("pts"), "pj": s.get("pj"), "pg": s.get("pg"),
                "pp": s.get("pp"), "sg": s.get("sg"),
                "dif_sets": s.get("dif_sets"), "dif_games": s.get("dif_games"),
            })

        for eq in t.get("equipos", []):
            equipo_nombre = eq.get("nombre", "")
            for j in eq.get("jugadores", []):
                jugadores_list.append({
                    "torneo": torneo_nombre, "anio": anio, "categoria": categoria,
                    "equipo": equipo_nombre, "jugador": j.get("nombre", ""), "edad": j.get("edad", ""),
                })

        for sr in t.get("series", []):
            estado = sr.get("estado", "PENDIENTE")
            fecha = sr.get("fecha", "")
            local = sr.get("local", "")
            visitante = sr.get("visitante", "")
            entrada = {
                "torneo": torneo_nombre, "anio": anio, "categoria": categoria,
                "fecha": fecha, "hora": sr.get("hora"),
                "local": local, "visitante": visitante,
                "score_local": sr.get("score_local", 0),
                "score_visitante": sr.get("score_visitante", 0),
                "estado": estado, "sede": sr.get("sede", ""),
            }
            if estado in ("PENDIENTE", "REPROGRAMADO"):
                proximos_list.append(entrada)
            elif estado in ("CONFIRMADO", "A CONFIRMAR"):
                resultados_list.append(entrada)

            for p in sr.get("partidos", []):
                if p.get("local") or p.get("visitante"):
                    partidos_list.append({
                        "torneo": torneo_nombre, "anio": anio, "categoria": categoria,
                        "fecha": fecha, "equipo_local": local, "equipo_visitante": visitante,
                        "tipo": p.get("tipo", ""),
                        "jugador_local": p.get("local", ""),
                        "jugador_visitante": p.get("visitante", ""),
                        "score": p.get("score", ""),
                        "ganador": "local" if p.get("ganador") == "L" else "visitante" if p.get("ganador") == "V" else p.get("ganador", ""),
                        "estado": p.get("estado", ""),
                    })

    ctx = [
        "=== TABLA DE POSICIONES ===", json.dumps(standings_list, ensure_ascii=False, default=str),
        "=== PROXIMOS PARTIDOS ===", json.dumps(proximos_list, ensure_ascii=False, default=str),
        "=== RESULTADOS DE SERIES ===", json.dumps(resultados_list, ensure_ascii=False, default=str),
        "=== JUGADORES POR EQUIPO ===", json.dumps(jugadores_list, ensure_ascii=False, default=str),
        "=== PARTIDOS INDIVIDUALES ===", json.dumps(partidos_list, ensure_ascii=False, default=str),
    ]
    return "\n".join(ctx)


def build_prompt(system: str, history: list, user_message: str) -> str:
    """Construye el prompt para modo JSON (sin function calling)."""
    parts = [system, ""]
    for msg in history:
        role = "Usuario" if msg.get("role") == "user" else "Asistente"
        parts.append(f"{role}: {msg.get('content', '')}")
    parts.append(f"Usuario: {user_message}")
    parts.append("Asistente:")
    return "\n".join(parts)

