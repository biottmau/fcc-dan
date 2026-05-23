#!/usr/bin/env python3
"""
Carga (o recarga) la tabla partidos_individuales desde el JSON.
Ejecutar cada vez que se actualice faccma_full.json.

Uso:
    python scripts/load_partidos_individuales.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dotenv import load_dotenv

load_dotenv(dotenv_path=".env")

import psycopg2
import psycopg2.extras

DB_CONFIG = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "dbname": os.getenv("DB_NAME", "postgres"),
    "port": int(os.getenv("DB_PORT", "6543")),
    "sslmode": os.getenv("DB_SSLMODE", "require"),
}

JSON_FILE = os.getenv("JSON_FILE", "faccma_full.json")


def main():
    print(f"Conectando a PostgreSQL...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # Crear tabla si no existe
    cur.execute("""
        CREATE TABLE IF NOT EXISTS partidos_individuales (
            id SERIAL PRIMARY KEY,
            id_serie INTEGER,
            torneo TEXT,
            anio INTEGER,
            categoria TEXT,
            zona TEXT,
            equipo_local TEXT,
            equipo_visitante TEXT,
            tipo TEXT,
            jugador_local TEXT,
            jugador_visitante TEXT,
            score TEXT,
            ganador TEXT,
            estado TEXT
        );
    """)
    conn.commit()

    print(f"Leyendo {JSON_FILE}...")
    with open(JSON_FILE, encoding="utf-8") as f:
        data = json.load(f)

    rows = []
    for torneo in data.get("torneos", []):
        for serie in torneo.get("series", []):
            for partido in serie.get("partidos", []):
                if not (partido.get("local") or partido.get("visitante")):
                    continue
                rows.append((
                    serie.get("idSerie"),
                    torneo.get("torneo"),
                    torneo.get("anio"),
                    torneo.get("categoria"),
                    torneo.get("zona"),
                    serie.get("local"),
                    serie.get("visitante"),
                    partido.get("partido") or partido.get("tipo"),
                    partido.get("local"),
                    partido.get("visitante"),
                    partido.get("score"),
                    partido.get("ganador"),
                    partido.get("estado"),
                ))

    cur.execute("DELETE FROM partidos_individuales")
    psycopg2.extras.execute_values(cur, """
        INSERT INTO partidos_individuales
        (id_serie, torneo, anio, categoria, zona, equipo_local, equipo_visitante,
         tipo, jugador_local, jugador_visitante, score, ganador, estado)
        VALUES %s
    """, rows)
    conn.commit()
    print(f"✓ {len(rows)} partidos individuales cargados en la base de datos.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
