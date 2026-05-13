# ============================================================
# FACCMA TENIS - Backend API
# FastAPI + MySQL + Google Gemini API
# Deploy: AWS EC2 / Elastic Beanstalk
# ============================================================

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

from context import SYSTEM_PROMPT, build_context, build_context_from_json, build_prompt

# Modulos propios
from database import USE_DB, load_json_data, query

# ------------------------------------------------------------
# GEMINI CONFIG
# ------------------------------------------------------------
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)
GEMINI_MODEL = "gemini-2.5-flash"

# ------------------------------------------------------------
# APP
# ------------------------------------------------------------
app = FastAPI(title="FACCMA Tenis API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # En produccion: restringir al dominio
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
        context = build_context(req.message)
        system = SYSTEM_PROMPT + "\n\nDATOS ACTUALES DE LA BASE:\n" + context

        prompt = build_prompt(system, req.history, req.message)

        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=1000,
                temperature=0.2,
            ),
        )
        return ChatResponse(reply=response.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/standings/{id_categoria}")
def get_standings(id_categoria: int):
    if not USE_DB:
        return {"modo": "demo", "info": "Use /standings-demo para datos del JSON"}
    rows = query(
        "SELECT * FROM v_standings WHERE categoria = (SELECT nombre FROM categorias WHERE id = %s)",
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
            "SELECT * FROM v_proximos WHERE categoria = %s LIMIT 50", (categoria,)
        )
    else:
        rows = query("SELECT * FROM v_proximos LIMIT 50")
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
            "SELECT * FROM v_resultados WHERE local = %s OR visitante = %s LIMIT 50",
            (equipo, equipo),
        )
    elif categoria:
        rows = query(
            "SELECT * FROM v_resultados WHERE categoria = %s LIMIT 50", (categoria,)
        )
    else:
        rows = query("SELECT * FROM v_resultados LIMIT 50")
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
        SELECT t.anio, t.tipo, t.nombre as torneo, c.nombre as categoria, c.genero
        FROM categorias c JOIN torneos t ON c.id_torneo = t.id
        ORDER BY t.anio DESC, c.genero, c.nombre
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
    """,
        (f"%{nombre}%",),
    )
    return rows


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "FACCMA Tenis API",
        "modo": "demo (JSON)" if not USE_DB else "produccion (MySQL)",
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
        context = build_context(incoming_msg)
        system = SYSTEM_PROMPT + "\n\nDATOS:\n" + context
        system += (
            "\nIMPORTANTE: Responde en maximo 3-4 lineas. Sé muy conciso para WhatsApp."
        )

        prompt = build_prompt(system, [], incoming_msg)
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                max_output_tokens=400,
                temperature=0.2,
            ),
        )
        reply = response.text
    except Exception as e:
        reply = "Lo siento, hubo un error procesando tu consulta. Intenta nuevamente."

    twiml = f"""<?xml version='1.0' encoding='UTF-8'?>
<Response>
    <Message>{reply}</Message>
</Response>"""
    return twiml
