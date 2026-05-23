# ============================================================
# FACCMA TENIS - Backend API
# FastAPI + PostgreSQL + Google Gemini API
# Deploy: AWS EC2 / Render / Supabase
# ============================================================

import json
import os
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse
from google import genai
from google.genai import types
from pydantic import BaseModel

from context import DB_SCHEMA, SYSTEM_PROMPT, build_context_from_json, build_prompt, validate_and_run

# Modulos propios
from database import USE_DB, load_json_data, query

# ------------------------------------------------------------
# GEMINI CONFIG
# ------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

# ------------------------------------------------------------
# TOOL: execute_sql (Text-to-SQL con Function Calling)
# ------------------------------------------------------------
EXECUTE_SQL_TOOL = types.Tool(
    function_declarations=[
        types.FunctionDeclaration(
            name="execute_sql",
            description=(
                "Ejecuta una consulta SQL SELECT sobre la base de datos PostgreSQL de FACCMA Tenis "
                "y retorna los resultados. Usá esta función cada vez que necesites datos para responder."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="Consulta SQL SELECT válida para PostgreSQL",
                    )
                },
                required=["query"],
            ),
        )
    ]
)

SYSTEM_PROMPT_DB = (
    SYSTEM_PROMPT
    + "\n\nTenés acceso a una base de datos PostgreSQL. "
    "Usá la función execute_sql para consultar los datos que necesites antes de responder. "
    "Podés hacer múltiples consultas si es necesario. "
    "NUNCA respondas sin consultar la base de datos primero cuando la pregunta requiera datos.\n\n"
    "SCHEMA DE LA BASE DE DATOS:\n" + DB_SCHEMA
)


def _build_contents(history: list, user_message: str) -> list:
    """Convierte historial + mensaje actual a lista de Content para Gemini."""
    contents = []
    for msg in history:
        role = "user" if msg.get("role") == "user" else "model"
        contents.append(
            types.Content(role=role, parts=[types.Part(text=msg.get("content", ""))])
        )
    contents.append(
        types.Content(role="user", parts=[types.Part(text=user_message)])
    )
    return contents


async def _chat_with_sql(
    contents: list,
    system: str,
    max_tokens: int = 1000,
    temp: float = 0.2,
) -> str:
    """
    Flujo de chat con Function Calling:
    Gemini llama a execute_sql → backend valida y ejecuta → Gemini recibe resultados → responde.
    Se permite hasta 5 rondas de consultas para preguntas complejas.
    """
    config_with_tools = types.GenerateContentConfig(
        system_instruction=system,
        tools=[EXECUTE_SQL_TOOL],
        max_output_tokens=max_tokens,
        temperature=temp,
    )
    config_final = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        temperature=temp,
    )

    response = gemini_client.models.generate_content(
        model=GEMINI_MODEL,
        contents=contents,
        config=config_with_tools,
    )

    for _ in range(5):
        fn_parts = [
            p for p in response.candidates[0].content.parts
            if p.function_call
        ]
        if not fn_parts:
            break

        # Agregar respuesta del modelo al hilo
        contents.append(response.candidates[0].content)

        # Ejecutar cada function call y armar las respuestas
        fn_responses = []
        for part in fn_parts:
            fc = part.function_call
            try:
                sql = fc.args["query"]
                print(f"[SQL] {sql}")
                rows = validate_and_run(sql)
                result = json.dumps(rows, ensure_ascii=False, default=str)
                print(f"[SQL] {len(rows)} filas retornadas")
            except Exception as e:
                result = f"Error: {str(e)}"
                print(f"[SQL ERROR] {result}")

            fn_responses.append(
                types.Part(
                    function_response=types.FunctionResponse(
                        name=fc.name,
                        response={"result": result},
                    )
                )
            )

        contents.append(types.Content(role="user", parts=fn_responses))

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=contents,
            config=config_with_tools,
        )

    return response.text


# ------------------------------------------------------------
# APP
# ------------------------------------------------------------
app = FastAPI(title="FACCMA Tenis API", version="2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------
# MODELOS
# ------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str
    history: list = []


class ChatResponse(BaseModel):
    reply: str


# ------------------------------------------------------------
# ENDPOINTS
# ------------------------------------------------------------
@app.get("/")
def serve_index():
    return FileResponse("index_out.html")


@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    try:
        if USE_DB:
            contents = _build_contents(req.history, req.message)
            reply = await _chat_with_sql(contents, SYSTEM_PROMPT_DB)
        else:
            context = build_context_from_json()
            system = SYSTEM_PROMPT + "\n\nDATOS ACTUALES:\n" + context
            prompt = build_prompt(system, req.history, req.message)
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=1000, temperature=0.2),
            )
            reply = response.text
        return ChatResponse(reply=reply)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/standings/{id_categoria}")
def get_standings(id_categoria: int):
    if not USE_DB:
        return {"modo": "demo", "info": "Use /standings-demo para datos del JSON"}
    rows = query(
        """
        SELECT eq.nombre AS equipo, tp.posicion, tp.puntos,
               tp.series_jugadas, tp.series_ganadas,
               tp.parciales_favor, tp.diferencia_sets, tp.diferencia_games
        FROM tabla_posiciones tp
        JOIN equipos eq ON tp.equipo_id = eq.equipo_id
        WHERE tp.categoria_id = %s
        ORDER BY tp.posicion
        """,
        (id_categoria,),
    )
    return rows


@app.get("/standings-by-name")
def get_standings_by_name(categoria: Optional[str] = None):
    """Endpoint compatible con el frontend: devuelve standings con nombres de campos esperados."""
    data = load_json_data()
    result = []
    for t in data.get("torneos", []):
        if categoria and t.get("categoria", "").lower() != categoria.lower():
            continue
        for s in t.get("standings", []):
            result.append(
                {
                    "posicion": s.get("pos"),
                    "equipo": s.get("equipo"),
                    "series_jugadas": s.get("pj"),
                    "series_ganadas": s.get("pg"),
                    "series_perdidas": s.get("pp"),
                    "parciales_favor": s.get("sg"),
                    "parciales_contra": s.get("sp"),
                    "dif_sets": s.get("dif_sets"),
                    "dif_games": s.get("dif_games"),
                    "puntos": s.get("pts"),
                    "torneo": t.get("torneo"),
                    "anio": t.get("anio"),
                    "categoria": t.get("categoria"),
                    "genero": t.get("genero"),
                }
            )
    return result[:300]


@app.get("/standings-demo")
def get_standings_demo(categoria: Optional[str] = None):
    """Endpoint demo: devuelve standings directo del JSON."""
    data = load_json_data()
    result = []
    for t in data.get("torneos", []):
        if categoria and t.get("categoria", "").lower() != categoria.lower():
            continue
        for s in t.get("standings", []):
            result.append(
                {
                    "torneo": t.get("torneo"),
                    "anio": t.get("anio"),
                    "tipo": t.get("tipo"),
                    "categoria": t.get("categoria"),
                    "genero": t.get("genero"),
                    **s,
                }
            )
    return result[:300]


@app.get("/proximos")
def get_proximos(categoria: Optional[str] = None):
    if not USE_DB:
        data = load_json_data()
        result = []
        for t in data.get("torneos", []):
            if categoria and t.get("categoria", "").lower() != categoria.lower():
                continue
            for sr in t.get("series", []):
                if sr.get("estado") in ("PENDIENTE", "REPROGRAMADO"):
                    result.append(
                        {
                            "torneo": t.get("torneo"),
                            "categoria": t.get("categoria"),
                            "fecha": sr.get("fecha"),
                            "hora": sr.get("hora"),
                            "local": sr.get("local"),
                            "visitante": sr.get("visitante"),
                            "estado": sr.get("estado"),
                            "sede": sr.get("sede"),
                        }
                    )
        return result[:50]
    if categoria:
        rows = query(
            """
            SELECT t.nombre AS torneo, c.nombre AS categoria,
                   p.fecha, p.hora, p.local_nombre, p.visitante_nombre,
                   p.estado, p.sede
            FROM partidos p
            JOIN categorias c ON p.categoria_id = c.categoria_id
            JOIN torneos t ON c.torneo_id = t.torneo_id
            WHERE p.estado IN ('PENDIENTE', 'REPROGRAMADO')
              AND c.nombre ILIKE %s
            ORDER BY p.fecha, p.hora
            LIMIT 50
            """,
            (f"%{categoria}%",),
        )
    else:
        rows = query(
            """
            SELECT t.nombre AS torneo, c.nombre AS categoria,
                   p.fecha, p.hora, p.local_nombre, p.visitante_nombre,
                   p.estado, p.sede
            FROM partidos p
            JOIN categorias c ON p.categoria_id = c.categoria_id
            JOIN torneos t ON c.torneo_id = t.torneo_id
            WHERE p.estado IN ('PENDIENTE', 'REPROGRAMADO')
            ORDER BY p.fecha, p.hora
            LIMIT 50
            """
        )
    return rows


@app.get("/resultados")
def get_resultados(categoria: Optional[str] = None, equipo: Optional[str] = None):
    if not USE_DB:
        data = load_json_data()
        result = []
        for t in data.get("torneos", []):
            if categoria and t.get("categoria", "").lower() != categoria.lower():
                continue
            for sr in t.get("series", []):
                if sr.get("estado") in ("CONFIRMADO", "A CONFIRMAR"):
                    local = sr.get("local", "")
                    visitante = sr.get("visitante", "")
                    if (
                        equipo
                        and equipo.lower() not in local.lower()
                        and equipo.lower() not in visitante.lower()
                    ):
                        continue
                    result.append(
                        {
                            "torneo": t.get("torneo"),
                            "categoria": t.get("categoria"),
                            "fecha": sr.get("fecha"),
                            "local": local,
                            "score_local": sr.get("score_local"),
                            "score_visitante": sr.get("score_visitante"),
                            "visitante": visitante,
                            "estado": sr.get("estado"),
                        }
                    )
        return result[:50]
    if equipo:
        rows = query(
            """
            SELECT t.nombre AS torneo, c.nombre AS categoria,
                   p.fecha, p.local_nombre, p.sets_local,
                   p.sets_visitante, p.visitante_nombre, p.score_text, p.estado
            FROM partidos p
            JOIN categorias c ON p.categoria_id = c.categoria_id
            JOIN torneos t ON c.torneo_id = t.torneo_id
            WHERE p.estado IN ('CONFIRMADO', 'A CONFIRMAR')
              AND (p.local_nombre ILIKE %s OR p.visitante_nombre ILIKE %s)
            ORDER BY p.fecha DESC
            LIMIT 50
            """,
            (f"%{equipo}%", f"%{equipo}%"),
        )
    elif categoria:
        rows = query(
            """
            SELECT t.nombre AS torneo, c.nombre AS categoria,
                   p.fecha, p.local_nombre, p.sets_local,
                   p.sets_visitante, p.visitante_nombre, p.score_text, p.estado
            FROM partidos p
            JOIN categorias c ON p.categoria_id = c.categoria_id
            JOIN torneos t ON c.torneo_id = t.torneo_id
            WHERE p.estado IN ('CONFIRMADO', 'A CONFIRMAR')
              AND c.nombre ILIKE %s
            ORDER BY p.fecha DESC
            LIMIT 50
            """,
            (f"%{categoria}%",),
        )
    else:
        rows = query(
            """
            SELECT t.nombre AS torneo, c.nombre AS categoria,
                   p.fecha, p.local_nombre, p.sets_local,
                   p.sets_visitante, p.visitante_nombre, p.score_text, p.estado
            FROM partidos p
            JOIN categorias c ON p.categoria_id = c.categoria_id
            JOIN torneos t ON c.torneo_id = t.torneo_id
            WHERE p.estado IN ('CONFIRMADO', 'A CONFIRMAR')
            ORDER BY p.fecha DESC
            LIMIT 50
            """
        )
    return rows


@app.get("/categorias")
def get_categorias():
    if not USE_DB:
        data = load_json_data()
        seen = set()
        result = []
        for t in data.get("torneos", []):
            key = (
                t.get("anio"),
                t.get("tipo"),
                t.get("torneo"),
                t.get("categoria"),
                t.get("genero"),
            )
            if key not in seen:
                seen.add(key)
                result.append(
                    {
                        "anio": t.get("anio"),
                        "tipo": t.get("tipo"),
                        "torneo": t.get("torneo"),
                        "categoria": t.get("categoria"),
                        "genero": t.get("genero"),
                    }
                )
        return sorted(
            result,
            key=lambda x: (
                -(x["anio"] or 0),
                x.get("genero", ""),
                x.get("categoria", ""),
            ),
        )
    rows = query("""
        SELECT t.nombre AS torneo, c.nombre AS categoria
        FROM categorias c
        JOIN torneos t ON c.torneo_id = t.torneo_id
        ORDER BY t.nombre, c.nombre
    """)
    return rows


@app.get("/jugadores/{nombre}")
def buscar_jugador(nombre: str):
    if not USE_DB:
        data = load_json_data()
        result = []
        nombre_lower = nombre.lower()
        for t in data.get("torneos", []):
            for eq in t.get("equipos", []):
                for j in eq.get("jugadores", []):
                    if nombre_lower in j.get("nombre", "").lower():
                        result.append(
                            {
                                "nombre": j.get("nombre"),
                                "edad": j.get("edad"),
                                "equipo": eq.get("nombre"),
                                "categoria": t.get("categoria"),
                                "anio": t.get("anio"),
                                "tipo": t.get("tipo"),
                            }
                        )
        # Deduplicar por nombre
        seen = set()
        dedup = []
        for r in result:
            if r["nombre"] not in seen:
                seen.add(r["nombre"])
                dedup.append(r)
        return dedup[:20]
    rows = query(
        """
        SELECT j.nombre, j.edad,
               eq.nombre AS equipo, c.nombre AS categoria, t.nombre AS torneo
        FROM jugadores j
        JOIN equipos eq ON j.equipo_id = eq.equipo_id
        JOIN categorias c ON eq.categoria_id = c.categoria_id
        JOIN torneos t ON c.torneo_id = t.torneo_id
        WHERE j.nombre ILIKE %s
        LIMIT 20
    """,
        (f"%{nombre}%",),
    )
    return rows


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "FACCMA Tenis API",
        "modo": "demo (JSON)" if not USE_DB else "produccion (PostgreSQL)",
    }


# ------------------------------------------------------------
# WHATSAPP WEBHOOK (Twilio)
# ------------------------------------------------------------
@app.post("/whatsapp", response_class=PlainTextResponse)
async def whatsapp_webhook(request: Request):
    form = await request.form()
    incoming_msg = form.get("Body", "").strip()

    if not incoming_msg:
        return "<?xml version='1.0'?><Response></Response>"

    try:
        if USE_DB:
            system_wa = (
                SYSTEM_PROMPT_DB
                + "\nIMPORTANTE: Respondé en máximo 3-4 líneas. Sé muy conciso para WhatsApp."
            )
            contents = _build_contents([], incoming_msg)
            reply = await _chat_with_sql(contents, system_wa, max_tokens=400)
        else:
            context = build_context_from_json()
            system = SYSTEM_PROMPT + "\n\nDATOS:\n" + context
            system += "\nIMPORTANTE: Respondé en máximo 3-4 líneas. Sé muy conciso para WhatsApp."
            prompt = build_prompt(system, [], incoming_msg)
            response = gemini_client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(max_output_tokens=400, temperature=0.2),
            )
            reply = response.text
    except Exception:
        reply = "Lo siento, hubo un error procesando tu consulta. Intenta nuevamente."

    twiml = f"""<?xml version='1.0' encoding='UTF-8'?>
<Response>
    <Message>{reply}</Message>
</Response>"""
    return twiml
