# ============================================================
# FACCMA TENIS - Context builder para Gemini
# ============================================================

import json

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
# CONTEXT BUILDER - construye el contexto para Gemini
# Modo DB: consulta MySQL
# Modo demo: lee el JSON en memoria
# ------------------------------------------------------------
def build_context_from_json() -> str:
    """Construye el contexto leyendo datos desde el JSON en memoria."""
    data = load_json_data()
    torneos = data.get("torneos", [])
    print(f"[DEBUG] build_context_from_json: {len(torneos)} torneos disponibles")
    for t in torneos[:5]:
        print(
            f"  → {t.get('torneo')} | {t.get('categoria')} | standings={len(t.get('standings', []))} series={len(t.get('series', []))}"
        )

    standings_list = []
    proximos_list = []
    resultados_list = []
    jugadores_list = []
    partidos_list = []

    for t in torneos:
        torneo_nombre = t.get("torneo", "")
        categoria = t.get("categoria", "")
        anio = t.get("anio", "")
        tipo = t.get("tipo", "")

        # Standings
        for s in t.get("standings", []):
            standings_list.append(
                {
                    "torneo": torneo_nombre,
                    "anio": anio,
                    "tipo": tipo,
                    "categoria": categoria,
                    "pos": s.get("pos"),
                    "equipo": s.get("equipo"),
                    "pts": s.get("pts"),
                    "pj": s.get("pj"),
                    "pg": s.get("pg"),
                    "pp": s.get("pp"),
                    "sg": s.get("sg"),
                    "dif_sets": s.get("dif_sets"),
                    "dif_games": s.get("dif_games"),
                }
            )

        # Equipos y jugadores
        for eq in t.get("equipos", []):
            equipo_nombre = eq.get("nombre", "")
            for j in eq.get("jugadores", []):
                jugadores_list.append(
                    {
                        "torneo": torneo_nombre,
                        "anio": anio,
                        "categoria": categoria,
                        "equipo": equipo_nombre,
                        "jugador": j.get("nombre", ""),
                        "edad": j.get("edad", ""),
                    }
                )

        # Series → proximos, resultados y partidos individuales
        for sr in t.get("series", []):
            estado = sr.get("estado", "PENDIENTE")
            fecha = sr.get("fecha", "")
            equipo_local = sr.get("local", "")
            equipo_visitante = sr.get("visitante", "")
            entrada = {
                "torneo": torneo_nombre,
                "anio": anio,
                "categoria": categoria,
                "fecha": fecha,
                "hora": sr.get("hora"),
                "local": equipo_local,
                "visitante": equipo_visitante,
                "score_local": sr.get("score_local", 0),
                "score_visitante": sr.get("score_visitante", 0),
                "estado": estado,
                "sede": sr.get("sede", ""),
            }
            if estado in ("PENDIENTE", "REPROGRAMADO"):
                proximos_list.append(entrada)
            elif estado in ("CONFIRMADO", "A CONFIRMAR"):
                resultados_list.append(entrada)

            # Partidos individuales (singles y dobles)
            for p in sr.get("partidos", []):
                if p.get("local") or p.get("visitante"):
                    partidos_list.append(
                        {
                            "torneo": torneo_nombre,
                            "anio": anio,
                            "categoria": categoria,
                            "fecha": fecha,
                            "equipo_local": equipo_local,
                            "equipo_visitante": equipo_visitante,
                            "tipo": p.get("tipo", ""),
                            "jugador_local": p.get("local", ""),
                            "jugador_visitante": p.get("visitante", ""),
                            "score": p.get("score", ""),
                            "ganador": "local" if p.get("ganador") == "L" else "visitante" if p.get("ganador") == "V" else p.get("ganador", ""),
                            "estado": p.get("estado", ""),
                        }
                    )

    print(
        f"[DEBUG] standings: {len(standings_list)} | proximos: {len(proximos_list)} | resultados: {len(resultados_list)} | jugadores: {len(jugadores_list)} | partidos: {len(partidos_list)}"
    )

    ctx = []
    ctx.append("=== TABLA DE POSICIONES ===")
    ctx.append(json.dumps(standings_list, ensure_ascii=False, default=str))
    ctx.append("=== PROXIMOS PARTIDOS ===")
    ctx.append(json.dumps(proximos_list, ensure_ascii=False, default=str))
    ctx.append("=== RESULTADOS DE SERIES ===")
    ctx.append(json.dumps(resultados_list, ensure_ascii=False, default=str))
    ctx.append("=== JUGADORES POR EQUIPO ===")
    ctx.append(json.dumps(jugadores_list, ensure_ascii=False, default=str))
    ctx.append("=== PARTIDOS INDIVIDUALES (singles y dobles con nombres de jugadores) ===")
    ctx.append(json.dumps(partidos_list, ensure_ascii=False, default=str))
    return "\n".join(ctx)


def build_context(user_question: str) -> str:
    """Construye el contexto segun el modo activo (DB o JSON)."""
    if not USE_DB:
        return build_context_from_json()

    ctx = []

    # Standings todos los torneos activos
    rows = query("SELECT * FROM v_standings LIMIT 300")
    ctx.append("=== TABLA DE POSICIONES ===")
    ctx.append(json.dumps(rows, ensure_ascii=False, default=str))

    # Proximos partidos
    rows = query("SELECT * FROM v_proximos LIMIT 100")
    ctx.append("=== PROXIMOS PARTIDOS ===")
    ctx.append(json.dumps(rows, ensure_ascii=False, default=str))

    # Ultimos resultados
    rows = query("SELECT * FROM v_resultados LIMIT 100")
    ctx.append("=== RESULTADOS RECIENTES ===")
    ctx.append(json.dumps(rows, ensure_ascii=False, default=str))

    return "\n".join(ctx)


def build_prompt(system: str, history: list, user_message: str) -> str:
    """Construye el prompt completo incluyendo historial de conversacion."""
    parts = [system, ""]
    for msg in history:
        role = "Usuario" if msg.get("role") == "user" else "Asistente"
        parts.append(f"{role}: {msg.get('content', '')}")
    parts.append(f"Usuario: {user_message}")
    parts.append("Asistente:")
    return "\n".join(parts)
