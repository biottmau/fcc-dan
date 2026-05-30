"""Control de acceso simplificado — sin restricciones de miembros."""

import os

ADMIN_PHONE = os.getenv("ADMIN_PHONE", "").strip()


def es_admin(telefono: str) -> bool:
    return bool(ADMIN_PHONE and telefono == ADMIN_PHONE)


def tiene_acceso(telefono: str) -> bool:
    """Acceso abierto: cualquier número de WhatsApp puede consultar."""
    return True
