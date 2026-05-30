"""
Servidor FastAPI para el agente WhatsApp de FACCMA Tenis.
Corre en un puerto separado al backend web (por defecto 8001).

Uso:
    uvicorn whatsapp.main:app --reload --port 8001
"""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse

from whatsapp.brain import generar_respuesta
from whatsapp.gastos import (
    LIMITE_ALERTA_USD,
    alerta_enviada_hoy,
    formatear_estadisticas,
    gasto_total_hoy,
    inicializar_tablas,
    limite_excedido,
    marcar_alerta_enviada,
    obtener_estadisticas,
    rate_limit_excedido,
    registrar_uso,
)
from whatsapp.memory import (
    es_nueva_sesion_hoy,
    guardar_mensaje,
    inicializar_db,
    obtener_historial,
)
from whatsapp.providers import obtener_proveedor
from whatsapp.webhook_dedup import inicializar_tabla as inicializar_dedup, reservar_mensaje
from whatsapp.acceso import es_admin

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("faccma_wa")

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").strip()

MSG_BIENVENIDA = (
    "👋 ¡Hola! Soy el asistente de *FACCMA Tenis*.\n"
    "Puedo contarte posiciones, resultados y fixtures del torneo.\n"
    "¿En qué te puedo ayudar?"
)
MSG_LIMITE = "⚠️ Alcanzaste el límite de consultas por hoy. Volvé mañana para seguir."
MSG_RATE_LIMIT = "⏳ Estás enviando mensajes muy rápido. Esperá un momento."
MSG_ERROR = "❌ Ocurrió un error al procesar tu consulta. Intentá de nuevo en unos minutos."


@asynccontextmanager
async def lifespan(app: FastAPI):
    await inicializar_db()
    inicializar_tablas()
    inicializar_dedup()
    logger.info("FACCMA WhatsApp Agent iniciado")
    yield


app = FastAPI(title="FACCMA WhatsApp Agent", lifespan=lifespan)
proveedor = obtener_proveedor()


@app.get("/")
def health():
    return {"status": "ok", "service": "faccma-whatsapp"}


@app.get("/webhook")
async def webhook_get(request: Request):
    resultado = await proveedor.validar_webhook(request)
    if resultado is not None:
        return PlainTextResponse(str(resultado))
    return {"status": "ok"}


@app.post("/webhook")
async def webhook_post(request: Request):
    mensajes = await proveedor.parsear_webhook(request)

    for msg in mensajes:
        if msg.es_propio or not msg.texto:
            continue
        if not reservar_mensaje(msg.mensaje_id):
            continue

        telefono = msg.telefono
        texto    = msg.texto.strip()
        logger.info(f"[WA] {telefono}: {texto[:80]}")

        # Comandos de administrador
        if es_admin(telefono):
            cmd = texto.lower()
            if cmd in ("/stats", "stats"):
                stats = obtener_estadisticas(dias=7)
                await proveedor.enviar_mensaje(telefono, formatear_estadisticas(stats, dias=7))
                continue
            if cmd in ("/stats hoy", "stats hoy"):
                stats = obtener_estadisticas(dias=1)
                await proveedor.enviar_mensaje(telefono, formatear_estadisticas(stats, dias=1))
                continue

        # Rate limiting
        if rate_limit_excedido(telefono):
            await proveedor.enviar_mensaje(telefono, MSG_RATE_LIMIT)
            continue

        # Límite de gasto diario
        if limite_excedido(telefono):
            await proveedor.enviar_mensaje(telefono, MSG_LIMITE)
            continue

        try:
            # Saludo de bienvenida en la primera interacción del día
            nueva_sesion = await es_nueva_sesion_hoy(telefono)

            historial = await obtener_historial(telefono, limite=10)
            reply, usage = await generar_respuesta(texto, historial)

            await guardar_mensaje(telefono, "user", texto)
            await guardar_mensaje(telefono, "assistant", reply)

            registrar_uso(telefono, usage.tokens_in, usage.tokens_out)

            # Alerta global al admin si se supera el umbral de gasto
            if (
                ADMIN_PHONE
                and gasto_total_hoy() >= LIMITE_ALERTA_USD
                and not alerta_enviada_hoy()
            ):
                marcar_alerta_enviada()
                asyncio.create_task(
                    proveedor.enviar_mensaje(
                        ADMIN_PHONE,
                        f"⚠️ FACCMA Bot: gasto diario superó ${LIMITE_ALERTA_USD:.2f}",
                    )
                )

            # Prefijo de bienvenida en la primera consulta del día
            if nueva_sesion:
                reply = MSG_BIENVENIDA + "\n\n" + reply

            await proveedor.enviar_mensaje(telefono, reply)

        except Exception as e:
            logger.error(f"Error procesando mensaje de {telefono}: {e}", exc_info=True)
            await proveedor.enviar_mensaje(telefono, MSG_ERROR)

    return {"status": "ok"}
