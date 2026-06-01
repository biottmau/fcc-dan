"""
load_json.py — Carga uno o más JSON scrapeados en PostgreSQL (Supabase).

Formato esperado (faccma_full.json):
  {"torneos": [{torneo, anio, tipo, idTorneo, categoria, standings:[...], series:[...]}, ...]}
  Cada elemento = una categoría de un torneo.

Idempotente: se puede ejecutar varias veces con los mismos datos o datos
actualizados (posiciones y resultados se sobreescriben, no se duplican).

Uso:
  python load_json.py json_files/tanda1.json json_files/tanda2.json
  python load_json.py json_files/*.json
"""

import hashlib
import json
import os
import re
import sys
from datetime import date, datetime

import psycopg2
from dotenv import load_dotenv

load_dotenv()

DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = int(os.getenv("DB_PORT", 5432))
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME     = os.getenv("DB_NAME")

VALID_ESTADOS = {"A CONFIRMAR", "CONFIRMADO", "PENDIENTE", "REPROGRAMADO"}


def _normalizar_nombre(s: str) -> str:
    """Normaliza espaciado alrededor del guion: 'X- Y' -> 'X - Y'."""
    return re.sub(r'([^ ])-', r'\1 -', str(s).strip())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def synth_id(text: str) -> int:
    """ID entero negativo determinístico para registros sin ID de origen."""
    return -(int(hashlib.md5(text.encode()).hexdigest()[:12], 16) % (2 ** 30))


def parse_date(value) -> date | None:
    if not value:
        return None
    s = str(value)[:10]
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value):
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:5], "%H:%M").time()
    except ValueError:
        return None


def parse_diff(value) -> int:
    if value is None:
        return 0
    try:
        return int(str(value).replace("+", ""))
    except (ValueError, TypeError):
        return 0


# ---------------------------------------------------------------------------
# Carga de una entrada (un torneo + una categoría)
# ---------------------------------------------------------------------------

def load_entry(cur, entry: dict, stats: dict):
    torneo_nombre = entry["torneo"]
    anio          = entry.get("anio")
    tipo          = entry.get("tipo", "")
    cat_nombre    = _normalizar_nombre(entry["categoria"])

    # ── 1. Torneo ──────────────────────────────────────────────────────────
    # Usar idTorneo del JSON si existe; sino generar uno determinístico negativo
    id_torneo_src = entry.get("idTorneo") or synth_id(f"{torneo_nombre}{anio}{tipo}")
    fecha_scraped = parse_date(entry.get("fecha_scraped")) or date.today()

    cur.execute(
        """
        INSERT INTO torneos (source_torneo_id, nombre, fecha_generacion, fuente)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (source_torneo_id) DO UPDATE
            SET nombre           = EXCLUDED.nombre,
                fecha_generacion = EXCLUDED.fecha_generacion
        RETURNING torneo_id
        """,
        (id_torneo_src, torneo_nombre, fecha_scraped, "scraper"),
    )
    torneo_id = cur.fetchone()[0]
    stats["torneos_vistos"].add(torneo_id)

    # ── 2. Categoría ───────────────────────────────────────────────────────
    # Conflict en (torneo_id, nombre) — ya existe UNIQUE constraint en el schema
    cur.execute(
        """
        INSERT INTO categorias (torneo_id, source_categoria_id, source_nivel_id, nombre)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (torneo_id, nombre) DO NOTHING
        RETURNING categoria_id
        """,
        (torneo_id, 0, None, cat_nombre),
    )
    row = cur.fetchone()
    if row:
        categoria_id = row[0]
        stats["categorias"] += 1
    else:
        cur.execute(
            "SELECT categoria_id FROM categorias WHERE torneo_id = %s AND nombre = %s",
            (torneo_id, cat_nombre),
        )
        categoria_id = cur.fetchone()[0]

    # ── 3. Equipos (desde standings) ────────────────────────────────────────
    # Conflict en (categoria_id, nombre) — existe UNIQUE en el schema
    equipo_map: dict[str, int] = {}
    for row in entry.get("standings", []):
        nombre  = row["equipo"]
        src_eid = nombre[:30]   # nombre como ID de origen cuando no hay uno real
        cur.execute(
            """
            INSERT INTO equipos (categoria_id, source_equipo_id, nombre)
            VALUES (%s, %s, %s)
            ON CONFLICT (categoria_id, nombre) DO NOTHING
            RETURNING equipo_id
            """,
            (categoria_id, src_eid, nombre),
        )
        res = cur.fetchone()
        if res:
            equipo_map[nombre] = res[0]
            stats["equipos"] += 1
        else:
            cur.execute(
                "SELECT equipo_id FROM equipos WHERE categoria_id = %s AND nombre = %s",
                (categoria_id, nombre),
            )
            equipo_map[nombre] = cur.fetchone()[0]

    # ── 4. Tabla de posiciones ──────────────────────────────────────────────
    # DELETE + INSERT porque el UNIQUE (categoria_id, posicion) daría conflicto
    # si los equipos cambian de puesto entre dos cargas del mismo torneo.
    if entry.get("standings"):
        cur.execute(
            "DELETE FROM tabla_posiciones WHERE categoria_id = %s",
            (categoria_id,),
        )
        for row in entry.get("standings", []):
            equipo_id = equipo_map.get(row["equipo"])
            if equipo_id is None:
                print(f"    [WARN] equipo no encontrado: {row['equipo']}")
                continue
            cur.execute(
                """
                INSERT INTO tabla_posiciones
                    (categoria_id, equipo_id, posicion, series_jugadas, series_ganadas,
                     parciales_favor, diferencia_sets, diferencia_games, puntos)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    categoria_id, equipo_id,
                    row["pos"],
                    row.get("pj", 0),
                    row.get("pg", 0),
                    row.get("sg", 0),
                    parse_diff(row.get("dif_sets")),
                    parse_diff(row.get("dif_games")),
                    row.get("pts", 0),
                ),
            )
            stats["standings"] += 1

    # ── 5. Partidos ─────────────────────────────────────────────────────────
    # Upsert por (categoria_id, source_serie_id)
    for serie in entry.get("series", []):
        local  = serie.get("local", "")
        visita = serie.get("visitante", "")
        estado = serie.get("estado", "PENDIENTE")
        if estado not in VALID_ESTADOS:
            estado = "PENDIENTE"

        id_serie = serie.get("idSerie")
        if id_serie is None:
            # ID sintético basado en categoría + fecha + equipos
            id_serie = synth_id(
                f"{categoria_id}{serie.get('fecha')}{local}{visita}"
            )

        score_local  = serie.get("score_local")  or 0
        score_visita = serie.get("score_visitante") or 0
        if estado in ("CONFIRMADO", "A CONFIRMAR") and (score_local or score_visita):
            score_text = f"{score_local}-{score_visita}"
            sets_l, sets_v = score_local, score_visita
        else:
            score_text = None
            sets_l = sets_v = None

        cur.execute(
            """
            INSERT INTO partidos
                (categoria_id, source_serie_id, fecha, hora,
                 local_nombre, visitante_nombre,
                 local_equipo_id, visitante_equipo_id,
                 score_text, sets_local, sets_visitante, estado, sede)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (categoria_id, source_serie_id) DO UPDATE
                SET fecha               = EXCLUDED.fecha,
                    hora                = EXCLUDED.hora,
                    score_text          = EXCLUDED.score_text,
                    sets_local          = EXCLUDED.sets_local,
                    sets_visitante      = EXCLUDED.sets_visitante,
                    estado              = EXCLUDED.estado,
                    sede                = EXCLUDED.sede,
                    local_equipo_id     = EXCLUDED.local_equipo_id,
                    visitante_equipo_id = EXCLUDED.visitante_equipo_id
            """,
            (
                categoria_id, id_serie,
                parse_date(serie.get("fecha")),
                parse_time(serie.get("hora")),
                local, visita,
                equipo_map.get(local),
                equipo_map.get(visita),
                score_text, sets_l, sets_v,
                estado, serie.get("sede"),
            ),
        )
        stats["partidos"] += 1

        # ── 6. Partidos individuales (singles/dobles dentro de la serie) ────
        partidos_ind = serie.get("partidos", [])
        if partidos_ind and estado in ("CONFIRMADO", "A CONFIRMAR"):
            # Reemplazar los individuales de esta serie para evitar duplicados
            cur.execute(
                "DELETE FROM partidos_individuales WHERE id_serie = %s",
                (id_serie,),
            )
            for pi in partidos_ind:
                cur.execute(
                    """
                    INSERT INTO partidos_individuales
                        (id_serie, torneo, anio, categoria, zona,
                         equipo_local, equipo_visitante,
                         tipo, jugador_local, jugador_visitante,
                         score, ganador, estado)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        id_serie, torneo_nombre, anio, cat_nombre, "UNICO",
                        local, visita,
                        pi.get("tipo", ""),
                        pi.get("local", ""),
                        pi.get("visitante", ""),
                        pi.get("score", ""),
                        pi.get("ganador", ""),
                        pi.get("estado", "Finalizado"),
                    ),
                )
            stats["partidos_ind"] += len(partidos_ind)


# ---------------------------------------------------------------------------
# Carga de un archivo
# ---------------------------------------------------------------------------

def load_file(cur, filepath: str, stats: dict):
    print(f"  {os.path.basename(filepath)} ... ", end="", flush=True)
    with open(filepath, encoding="utf-8") as f:
        data = json.load(f)

    torneos = data.get("torneos", [])
    print(f"{len(torneos)} entradas")

    for entry in torneos:
        load_entry(cur, entry, stats)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if len(sys.argv) < 2:
        print("Uso: python load_json.py archivo1.json [archivo2.json ...]")
        sys.exit(1)

    files = sys.argv[1:]
    missing = [f for f in files if not os.path.exists(f)]
    if missing:
        for f in missing:
            print(f"✗ Archivo no encontrado: {f}", file=sys.stderr)
        sys.exit(1)

    stats = {
        "torneos_vistos": set(),
        "categorias":     0,
        "equipos":        0,
        "standings":      0,
        "partidos":       0,
        "partidos_ind":   0,
    }

    conn = psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        user=DB_USER, password=DB_PASSWORD,
        dbname=DB_NAME,
    )
    try:
        with conn:
            with conn.cursor() as cur:
                for filepath in files:
                    load_file(cur, filepath, stats)

        print(f"\n✓ Carga completada.")
        print(f"  Torneos únicos   : {len(stats['torneos_vistos'])}")
        print(f"  Categorías       : {stats['categorias']}")
        print(f"  Equipos nuevos   : {stats['equipos']}")
        print(f"  Filas standings  : {stats['standings']}")
        print(f"  Series           : {stats['partidos']}")
        print(f"  Partidos indiv.  : {stats['partidos_ind']}")

    except Exception as exc:
        conn.rollback()
        print(f"\n✗ Error durante la carga: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
