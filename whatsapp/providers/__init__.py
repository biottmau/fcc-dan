"""Factory de proveedores WhatsApp — lee WHATSAPP_PROVIDER del .env."""

import os
from whatsapp.providers.base import ProveedorWhatsApp


def obtener_proveedor() -> ProveedorWhatsApp:
    proveedor = os.getenv("WHATSAPP_PROVIDER", "twilio").lower().strip()
    if proveedor == "twilio":
        from whatsapp.providers.twilio import ProveedorTwilio
        return ProveedorTwilio()
    raise ValueError(f"Proveedor no soportado: '{proveedor}'. Usar: twilio")
