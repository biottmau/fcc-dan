"""
Cerebro del agente WhatsApp FACCMA.
Delega en _chat_with_sql de faccma_backend_out para hacer text-to-SQL con Gemini.
"""

import logging

from faccma_backend_out import SYSTEM_PROMPT_DB, _build_contents, _chat_with_sql

logger = logging.getLogger("faccma_wa")

# Adición específica para WhatsApp: respuestas cortas y sin markdown complejo
_WA_ADDON = (
    "\n\nIMPORTANTE — Canal WhatsApp: "
    "Respondé de forma BREVE y CONCISA (máximo 4-5 líneas por respuesta). "
    "Evitá tablas largas y listas extensas; resumí lo más relevante. "
    "No uses formato markdown avanzado. "
    "En WhatsApp el asterisco *texto* forma negrita — usalo con moderación."
)

SYSTEM_PROMPT_WHATSAPP = SYSTEM_PROMPT_DB + _WA_ADDON


async def generar_respuesta(mensaje: str, historial: list[dict]) -> tuple[str, object]:
    """
    Genera una respuesta para WhatsApp consultando la DB de FACCMA via Gemini.

    Args:
        mensaje:   Texto del usuario.
        historial: Lista de turnos previos [{"role": "user"|"assistant", "content": "..."}].

    Returns:
        (texto_respuesta, TokenUsage) — TokenUsage tiene .tokens_in y .tokens_out.
    """
    contents = _build_contents(historial, mensaje)
    return await _chat_with_sql(
        contents,
        SYSTEM_PROMPT_WHATSAPP,
        max_tokens=800,
        temp=0.2,
    )
