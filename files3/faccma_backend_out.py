# ============================================================
# FACCMA TENIS - Backend API
# FastAPI + MySQL + Claude API
# Deploy: AWS EC2 / Elastic Beanstalk
# ============================================================

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import pymysql
import os
import json
from typing import Optional

app = FastAPI(title="FACCMA Tenis API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En produccion: restringir al dominio
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------------------------------------------------
# CONFIG (usar variables de entorno en AWS)
# ------------------------------------------------------------
DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "user":     os.getenv("DB_USER", "faccma"),
    "password": os.getenv("DB_PASSWORD", ""),
    "database": os.getenv("DB_NAME", "faccma_tenis"),
    "charset":  "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor
}

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# ------------------------------------------------------------
# DB HELPER
# ------------------------------------------------------------
def get_db():
    return pymysql.connect(**DB_CONFIG)

def query(sql, params=None):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
            return cur.fetchall()
    finally:
        conn.close()

# ------------------------------------------------------------
# CONTEXT BUILDER - construye el contexto para Claude
# segun la pregunta del usuario
# ------------------------------------------------------------
def build_context(user_question: str) -> str:
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
# ENDPOINTS
# ------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    history: list = []

class ChatResponse(BaseModel):
    reply: str

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        context = build_context(req.message)
        system = SYSTEM_PROMPT + "\n\nDATOS ACTUALES DE LA BASE:\n" + context

        messages = req.history + [{"role": "user", "content": req.message}]

        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            system=system,
            messages=messages
        )
        return ChatResponse(reply=response.content[0].text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/standings/{id_categoria}")
def get_standings(id_categoria: int):
    rows = query(
        "SELECT * FROM v_standings WHERE categoria = (SELECT nombre FROM categorias WHERE id = %s)",
        (id_categoria,)
    )
    return rows

@app.get("/proximos")
def get_proximos(categoria: Optional[str] = None):
    if categoria:
        rows = query("SELECT * FROM v_proximos WHERE categoria = %s LIMIT 50", (categoria,))
    else:
        rows = query("SELECT * FROM v_proximos LIMIT 50")
    return rows

@app.get("/resultados")
def get_resultados(categoria: Optional[str] = None, equipo: Optional[str] = None):
    if equipo:
        rows = query(
            "SELECT * FROM v_resultados WHERE local = %s OR visitante = %s LIMIT 50",
            (equipo, equipo)
        )
    elif categoria:
        rows = query("SELECT * FROM v_resultados WHERE categoria = %s LIMIT 50", (categoria,))
    else:
        rows = query("SELECT * FROM v_resultados LIMIT 50")
    return rows

@app.get("/categorias")
def get_categorias():
    rows = query("""
        SELECT t.anio, t.tipo, t.nombre as torneo, c.nombre as categoria, c.genero
        FROM categorias c JOIN torneos t ON c.id_torneo = t.id
        ORDER BY t.anio DESC, c.genero, c.nombre
    """)
    return rows

@app.get("/jugadores/{nombre}")
def buscar_jugador(nombre: str):
    rows = query("""
        SELECT j.nombre, j.edad, i.nombre as institucion,
               e.nombre as equipo, t.anio, t.tipo, cat.nombre as categoria
        FROM jugadores j
        LEFT JOIN instituciones i ON j.id_institucion = i.id
        LEFT JOIN lista_buena_fe lbf ON lbf.id_jugador = j.id
        LEFT JOIN equipos e ON lbf.id_equipo = e.id
        LEFT JOIN categorias cat ON e.id_categoria = cat.id
        LEFT JOIN torneos t ON cat.id_torneo = t.id
        WHERE j.nombre LIKE %s
        LIMIT 20
    """, (f"%{nombre}%",))
    return rows

@app.get("/health")
def health():
    return {"status": "ok", "service": "FACCMA Tenis API"}

# ------------------------------------------------------------
# WHATSAPP WEBHOOK (Twilio)
# ------------------------------------------------------------
from fastapi import Request
from fastapi.responses import PlainTextResponse

@app.post("/whatsapp", response_class=PlainTextResponse)
async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = form.get("Body", "").strip()
    from_number = form.get("From", "")

    if not incoming_msg:
        return "<?xml version='1.0'?><Response></Response>"

    try:
        context = build_context(incoming_msg)
        system = SYSTEM_PROMPT + "\n\nDATOS:\n" + context
        # WhatsApp: respuesta mas corta
        system += "\nIMPORTANTE: Responde en maximo 3-4 lineas. Sé muy conciso para WhatsApp."

        response = claude.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=system,
            messages=[{"role": "user", "content": incoming_msg}]
        )
        reply = response.content[0].text
    except Exception as e:
        reply = "Lo siento, hubo un error procesando tu consulta. Intenta nuevamente."

    twiml = f"""<?xml version='1.0' encoding='UTF-8'?>
<Response>
    <Message>{reply}</Message>
</Response>"""
    return twiml


# Endpoint adicional requerido por el frontend
@app.get("/standings-by-name")
def get_standings_by_name(categoria: str):
    rows = query("""
        SELECT
            s.posicion, e.nombre AS equipo,
            s.puntos, s.series_jugadas AS series_jugadas,
            s.series_ganadas, s.parciales_favor,
            s.dif_sets, s.dif_games
        FROM standings s
        JOIN categorias cat ON s.id_categoria = cat.id
        JOIN torneos t ON cat.id_torneo = t.id
        JOIN equipos e ON s.id_equipo = e.id
        WHERE cat.nombre = %s AND t.anio = 2026
        ORDER BY s.posicion
    """, (categoria,))
    return rows

@app.get("/resultados-by-name")
def get_resultados_by_name(categoria: str):
    rows = query("""
        SELECT
            sr.fecha, sr.hora, sr.sede,
            el.nombre AS local, ev.nombre AS visitante,
            sr.score_local, sr.score_visitante, sr.estado
        FROM series sr
        JOIN categorias cat ON sr.id_categoria = cat.id
        JOIN torneos t ON cat.id_torneo = t.id
        JOIN equipos el ON sr.id_equipo_local = el.id
        JOIN equipos ev ON sr.id_equipo_visit = ev.id
        WHERE cat.nombre = %s AND t.anio = 2026
        ORDER BY sr.fecha DESC, sr.hora
    """, (categoria,))
    return rows
