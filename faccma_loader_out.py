# ============================================================
# FACCMA TENIS - Data Loader
# Carga el JSON unificado a MySQL
# Uso: python faccma_loader.py --file faccma_unified.json
# ============================================================

import json
import pymysql
import argparse
import os
from datetime import datetime

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "user":     os.getenv("DB_USER", "faccma"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "faccma_tenis"),
    "charset":  "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

def parse_date(s):
    if not s: return None
    for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%Y-%m-%dT%H:%M:%S.%fZ'):
        try:
            return datetime.strptime(s[:len(fmt)], fmt).date()
        except:
            continue
    return None

def parse_time(s):
    if not s: return None
    try:
        return datetime.strptime(s[:5], '%H:%M').time()
    except:
        return None

def get_or_create(cur, table, match_col, match_val, insert_data):
    cur.execute(f"SELECT id FROM {table} WHERE {match_col} = %s", (match_val,))
    row = cur.fetchone()
    if row:
        return row['id']
    cols = ', '.join(insert_data.keys())
    placeholders = ', '.join(['%s'] * len(insert_data))
    cur.execute(f"INSERT INTO {table} ({cols}) VALUES ({placeholders})", list(insert_data.values()))
    return cur.lastrowid

def load(filepath):
    with open(filepath) as f:
        data = json.load(f)

    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()
    stats = {'torneos': 0, 'categorias': 0, 'equipos': 0, 'jugadores': 0, 'series': 0, 'partidos': 0}

    try:
        for t in data['torneos']:
            # 1. Torneo
            cur.execute("""
                INSERT INTO torneos (nombre, tipo, anio, id_torneo_src, activo, fecha_scraped)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE fecha_scraped = VALUES(fecha_scraped)
            """, (t['torneo'], t['tipo'], t['anio'], t.get('idTorneo'),
                  t['anio'] == 2026, t.get('fecha_scraped', None)))
            cur.execute("SELECT id FROM torneos WHERE nombre=%s AND anio=%s AND tipo=%s",
                        (t['torneo'], t['anio'], t['tipo']))
            id_torneo = cur.fetchone()['id']
            stats['torneos'] += 1

            # 2. Categoria
            cur.execute("""
                INSERT INTO categorias (id_torneo, nombre, genero, zona)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE genero = VALUES(genero)
            """, (id_torneo, t['categoria'], t['genero'], t.get('zona', 'UNICO')))
            cur.execute("SELECT id FROM categorias WHERE id_torneo=%s AND nombre=%s",
                        (id_torneo, t['categoria']))
            id_cat = cur.fetchone()['id']
            stats['categorias'] += 1

            # 3. Equipos y jugadores
            equipo_ids = {}
            for eq in t.get('equipos', []):
                nombre_eq = eq['nombre']
                # Institucion
                sigla = nombre_eq.split('-')[0] if '-' in nombre_eq else nombre_eq
                id_inst = get_or_create(cur, 'instituciones', 'nombre', sigla,
                                        {'nombre': sigla, 'sigla': sigla})
                # Equipo
                cur.execute("""
                    INSERT INTO equipos (id_institucion, id_torneo, id_categoria, nombre, id_equipo_src)
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE nombre = VALUES(nombre)
                """, (id_inst, id_torneo, id_cat, nombre_eq, eq.get('idEquipo')))
                cur.execute("SELECT id FROM equipos WHERE id_categoria=%s AND nombre=%s",
                            (id_cat, nombre_eq))
                id_eq = cur.fetchone()['id']
                equipo_ids[nombre_eq] = id_eq
                stats['equipos'] += 1

                # Jugadores
                for orden, jug in enumerate(eq.get('jugadores', []), 1):
                    id_jug = get_or_create(cur, 'jugadores', 'nombre', jug['nombre'],
                                           {'nombre': jug['nombre'], 'edad': jug.get('edad'),
                                            'id_institucion': id_inst})
                    cur.execute("""
                        INSERT IGNORE INTO lista_buena_fe (id_equipo, id_jugador, orden)
                        VALUES (%s, %s, %s)
                    """, (id_eq, id_jug, orden))
                    stats['jugadores'] += 1

            # 4. Standings
            for s in t.get('standings', []):
                nombre_eq = s['equipo']
                if nombre_eq not in equipo_ids:
                    sigla = nombre_eq.split('-')[0] if '-' in nombre_eq else nombre_eq
                    id_inst = get_or_create(cur, 'instituciones', 'nombre', sigla,
                                            {'nombre': sigla, 'sigla': sigla})
                    cur.execute("""
                        INSERT IGNORE INTO equipos (id_institucion, id_torneo, id_categoria, nombre)
                        VALUES (%s, %s, %s, %s)
                    """, (id_inst, id_torneo, id_cat, nombre_eq))
                    cur.execute("SELECT id FROM equipos WHERE id_categoria=%s AND nombre=%s",
                                (id_cat, nombre_eq))
                    equipo_ids[nombre_eq] = cur.fetchone()['id']

                id_eq = equipo_ids[nombre_eq]
                cur.execute("""
                    INSERT INTO standings
                        (id_categoria, id_equipo, posicion, puntos, series_jugadas,
                         series_ganadas, series_perdidas, parciales_favor, dif_sets, dif_games)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON DUPLICATE KEY UPDATE
                        posicion=VALUES(posicion), puntos=VALUES(puntos),
                        series_jugadas=VALUES(series_jugadas)
                """, (id_cat, id_eq, s.get('pos'), s.get('pts'), s.get('pj'),
                      s.get('pg'), s.get('pp'), s.get('sg'),
                      s.get('dif_sets',''), s.get('dif_games','')))

            # 5. Series y partidos
            for sr in t.get('series', []):
                local = sr['local']
                visit = sr['visitante']

                for nombre_eq in [local, visit]:
                    if nombre_eq not in equipo_ids:
                        sigla = nombre_eq.split('-')[0] if '-' in nombre_eq else nombre_eq
                        id_inst = get_or_create(cur, 'instituciones', 'nombre', sigla,
                                                {'nombre': sigla, 'sigla': sigla})
                        cur.execute("""
                            INSERT IGNORE INTO equipos (id_institucion, id_torneo, id_categoria, nombre)
                            VALUES (%s,%s,%s,%s)
                        """, (id_inst, id_torneo, id_cat, nombre_eq))
                        cur.execute("SELECT id FROM equipos WHERE id_categoria=%s AND nombre=%s",
                                    (id_cat, nombre_eq))
                        row = cur.fetchone()
                        if row:
                            equipo_ids[nombre_eq] = row['id']

                id_local = equipo_ids.get(local)
                id_visit = equipo_ids.get(visit)
                if not id_local or not id_visit:
                    continue

                cur.execute("""
                    INSERT IGNORE INTO series
                        (id_serie_src, id_categoria, id_equipo_local, id_equipo_visit,
                         fecha, hora, sede, score_local, score_visitante, estado)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, (sr.get('idSerie'), id_cat, id_local, id_visit,
                      parse_date(sr.get('fecha')), parse_time(sr.get('hora')),
                      sr.get('sede',''), sr.get('score_local',0),
                      sr.get('score_visitante',0), sr.get('estado','PENDIENTE')))

                id_serie = cur.lastrowid
                stats['series'] += 1

                for p in sr.get('partidos', []):
                    cur.execute("""
                        INSERT INTO partidos (id_serie, tipo, local, visitante, score, ganador, estado)
                        VALUES (%s,%s,%s,%s,%s,%s,%s)
                    """, (id_serie, p.get('tipo'), p.get('local'), p.get('visitante'),
                          p.get('score'), p.get('ganador'), p.get('estado')))
                    stats['partidos'] += 1

        conn.commit()
        print("CARGA EXITOSA:")
        for k, v in stats.items():
            print(f"  {k}: {v}")

    except Exception as e:
        conn.rollback()
        print(f"ERROR: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--file', default='faccma_unified.json')
    args = parser.parse_args()
    load(args.file)

