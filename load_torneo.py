#!/usr/bin/env venv/bin/python3
"""
load_torneo.py
Carga el JSON del torneo en PostgreSQL usando INSERT ... ON CONFLICT para
evitar duplicados. Todas las credenciales se leen desde .env
"""

import json
import os
import sys
from datetime import datetime

import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 5432))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

JSON_FILE = os.getenv("JSON_FILE_TORNEO", "tenis_apertura_2026 (2).json")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_diff(value) -> int:
    """Convierte '+24', '-5', 0, etc. a entero."""
    if value is None:
        return 0
    return int(str(value).replace("+", ""))


def parse_score(score_text: str):
    """Devuelve (sets_local, sets_visitante) o (None, None)."""
    if not score_text or "-" not in score_text:
        return None, None
    parts = score_text.split("-")
    if len(parts) == 2:
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            return None, None
    return None, None


def parse_date(value: str):
    """Convierte 'DD-MM-YYYY' a date, o None."""
    if not value:
        return None
    for fmt in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return None


def parse_time(value: str):
    """Convierte 'HH:MM' a time, o None."""
    if not value:
        return None
    try:
        return datetime.strptime(value, "%H:%M").time()
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def upsert_torneo(cur, data: dict) -> int:
    cur.execute(
        """
        INSERT INTO torneos (source_torneo_id, nombre, fecha_generacion, fuente)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (source_torneo_id) DO UPDATE
            SET nombre           = EXCLUDED.nombre,
                fecha_generacion = EXCLUDED.fecha_generacion,
                fuente           = EXCLUDED.fuente
        RETURNING torneo_id
        """,
        (
            data["idTorneo"],
            data["torneo"],
            parse_date(data.get("fechaGeneracion")),
            data.get("fuente"),
        ),
    )
    return cur.fetchone()[0]


def upsert_categoria(cur, torneo_id: int, cat: dict) -> int:
    # Varios idCategoria pueden repetirse entre categorías del mismo torneo
    # (se distinguen por idNivel). Se usa nombre como clave de conflicto ya que
    # es único dentro del torneo y tiene su propio UNIQUE constraint en el schema.
    cur.execute(
        """
        INSERT INTO categorias (torneo_id, source_categoria_id, source_nivel_id, nombre)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (torneo_id, nombre) DO UPDATE
            SET source_categoria_id = EXCLUDED.source_categoria_id,
                source_nivel_id     = EXCLUDED.source_nivel_id
        RETURNING categoria_id
        """,
        (torneo_id, cat["idCategoria"], cat.get("idNivel"), cat["nombre"]),
    )
    return cur.fetchone()[0]


def upsert_equipo(cur, categoria_id: int, source_equipo_id: str, nombre: str) -> int:
    cur.execute(
        """
        INSERT INTO equipos (categoria_id, source_equipo_id, nombre)
        VALUES (%s, %s, %s)
        ON CONFLICT (categoria_id, source_equipo_id) DO UPDATE
            SET nombre = EXCLUDED.nombre
        RETURNING equipo_id
        """,
        (categoria_id, source_equipo_id, nombre),
    )
    return cur.fetchone()[0]


def upsert_jugador(cur, equipo_id: int, nombre: str, edad):
    edad_val = None
    if edad is not None:
        try:
            edad_val = int(edad)
        except (ValueError, TypeError):
            edad_val = None
    cur.execute(
        """
        INSERT INTO jugadores (equipo_id, nombre, edad)
        VALUES (%s, %s, %s)
        ON CONFLICT (equipo_id, nombre) DO UPDATE
            SET edad = EXCLUDED.edad
        """,
        (equipo_id, nombre, edad_val),
    )


def upsert_tabla_posicion(cur, categoria_id: int, equipo_id: int, row: dict):
    cur.execute(
        """
        INSERT INTO tabla_posiciones
            (categoria_id, equipo_id, posicion, series_jugadas, series_ganadas,
             parciales_favor, diferencia_sets, diferencia_games, puntos)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (categoria_id, equipo_id) DO UPDATE
            SET posicion         = EXCLUDED.posicion,
                series_jugadas   = EXCLUDED.series_jugadas,
                series_ganadas   = EXCLUDED.series_ganadas,
                parciales_favor  = EXCLUDED.parciales_favor,
                diferencia_sets  = EXCLUDED.diferencia_sets,
                diferencia_games = EXCLUDED.diferencia_games,
                puntos           = EXCLUDED.puntos
        """,
        (
            categoria_id,
            equipo_id,
            row["posicion"],
            row.get("sJugadas", 0),
            row.get("sGanadas", 0),
            row.get("parcFavor", 0),
            parse_diff(row.get("difSets", 0)),
            parse_diff(row.get("difGames", 0)),
            row.get("ptos", 0),
        ),
    )


def upsert_partido(
    cur,
    categoria_id: int,
    partido: dict,
    equipo_map: dict,  # nombre -> equipo_id
):
    sets_local, sets_visitante = parse_score(partido.get("score"))
    estado = partido.get("estado", "PENDIENTE")
    # Normalizar estado al ENUM
    valid_estados = {"A CONFIRMAR", "CONFIRMADO", "PENDIENTE", "REPROGRAMADO"}
    if estado not in valid_estados:
        estado = "PENDIENTE"

    local_id = equipo_map.get(partido.get("local"))
    visitante_id = equipo_map.get(partido.get("visitante"))

    cur.execute(
        """
        INSERT INTO partidos
            (categoria_id, source_serie_id, fecha, hora,
             local_nombre, visitante_nombre,
             local_equipo_id, visitante_equipo_id,
             score_text, sets_local, sets_visitante,
             estado, sede)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (categoria_id, source_serie_id) DO UPDATE
            SET fecha               = EXCLUDED.fecha,
                hora                = EXCLUDED.hora,
                local_nombre        = EXCLUDED.local_nombre,
                visitante_nombre    = EXCLUDED.visitante_nombre,
                local_equipo_id     = EXCLUDED.local_equipo_id,
                visitante_equipo_id = EXCLUDED.visitante_equipo_id,
                score_text          = EXCLUDED.score_text,
                sets_local          = EXCLUDED.sets_local,
                sets_visitante      = EXCLUDED.sets_visitante,
                estado              = EXCLUDED.estado,
                sede                = EXCLUDED.sede
        """,
        (
            categoria_id,
            partido["serie"],
            parse_date(partido.get("dia")),
            parse_time(partido.get("hora")),
            partido.get("local", ""),
            partido.get("visitante", ""),
            local_id,
            visitante_id,
            partido.get("score"),
            sets_local,
            sets_visitante,
            estado,
            partido.get("sede"),
        ),
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    json_path = JSON_FILE
    if not os.path.isabs(json_path):
        json_path = os.path.join(os.path.dirname(__file__), json_path)

    print(f"Leyendo: {json_path}")
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )

    try:
        with conn:
            with conn.cursor() as cur:
                # 1. Torneo
                torneo_id = upsert_torneo(cur, data)
                print(f"  Torneo id={torneo_id} → '{data['torneo']}'")

                for cat in data.get("categorias", []):
                    # 2. Categoría
                    categoria_id = upsert_categoria(cur, torneo_id, cat)
                    print(f"  Categoría id={categoria_id} → '{cat['nombre']}'")

                    # 3. Equipos + jugadores
                    equipo_map: dict[str, int] = {}  # nombre -> equipo_id

                    for eq in cat.get("equipos", []):
                        equipo_id = upsert_equipo(
                            cur,
                            categoria_id,
                            str(eq["idEquipo"]),
                            eq["nombre"],
                        )
                        equipo_map[eq["nombre"]] = equipo_id

                        for jugador in eq.get("listaBuenaFe", []):
                            upsert_jugador(
                                cur,
                                equipo_id,
                                jugador["nombre"],
                                jugador.get("edad"),
                            )

                    # También registrar equipos que aparecen solo en tablaPosiciones
                    for row in cat.get("tablaPosiciones", []):
                        eid = str(row["idEquipo"])
                        nombre = row["equipo"]
                        if nombre not in equipo_map:
                            equipo_id = upsert_equipo(cur, categoria_id, eid, nombre)
                            equipo_map[nombre] = equipo_id

                    # 4. Tabla de posiciones
                    for row in cat.get("tablaPosiciones", []):
                        nombre = row["equipo"]
                        equipo_id = equipo_map.get(nombre)
                        if equipo_id is None:
                            print(f"    [WARN] Equipo no encontrado: {nombre}")
                            continue
                        upsert_tabla_posicion(cur, categoria_id, equipo_id, row)

                    # 5. Partidos
                    for partido in cat.get("fixture", []):
                        upsert_partido(cur, categoria_id, partido, equipo_map)

        print("\n✓ Carga completada exitosamente.")
    except Exception as exc:
        conn.rollback()
        print(f"\n✗ Error durante la carga: {exc}", file=sys.stderr)
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    main()
