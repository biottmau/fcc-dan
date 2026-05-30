"""Adaptador Twilio WhatsApp con validación de firma HMAC-SHA1."""

import base64
import hashlib
import hmac
import logging
import os
from urllib.parse import urlparse

import httpx
from fastapi import Request

from whatsapp.providers.base import MensajeEntrante, ProveedorWhatsApp

logger = logging.getLogger("faccma_wa")


class ProveedorTwilio(ProveedorWhatsApp):

    def _credenciales(self) -> dict:
        return {
            "account_sid": os.environ.get("TWILIO_ACCOUNT_SID",  "").strip(),
            "auth_token":  os.environ.get("TWILIO_AUTH_TOKEN",   "").strip(),
            "phone":       os.environ.get("TWILIO_PHONE_NUMBER", "").strip(),
        }

    def _url_para_firma(self, request_url: str) -> str:
        base = os.environ.get("WEBHOOK_BASE_URL", "").strip().rstrip("/")
        if not base:
            dominio = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
            if dominio:
                base = f"https://{dominio}"
        if base:
            path = urlparse(request_url).path
            return f"{base}{path}"
        return request_url

    def _validar_firma(self, url: str, params: dict, firma: str, auth_token: str) -> bool:
        cuerpo = url + "".join(f"{k}{v}" for k, v in sorted(params.items()))
        mac = hmac.new(auth_token.encode("utf-8"), cuerpo.encode("utf-8"), hashlib.sha1)
        firma_esperada = base64.b64encode(mac.digest()).decode()
        return hmac.compare_digest(firma_esperada, firma)

    async def parsear_webhook(self, request: Request) -> list[MensajeEntrante]:
        creds = self._credenciales()
        auth_token = creds["auth_token"]
        form = await request.form()

        if auth_token:
            firma = request.headers.get("X-Twilio-Signature", "")
            if not firma:
                ip = request.client.host if request.client else "desconocida"
                logger.warning(f"Webhook rechazado: sin X-Twilio-Signature (IP: {ip})")
                return []
            url_firma = self._url_para_firma(str(request.url))
            if not self._validar_firma(url_firma, dict(form), firma, auth_token):
                ip = request.client.host if request.client else "desconocida"
                logger.warning(
                    f"Webhook rechazado: firma inválida (IP: {ip}). "
                    f"URL usada: {url_firma}. Verificar WEBHOOK_BASE_URL."
                )
                return []
        else:
            logger.warning("TWILIO_AUTH_TOKEN no configurado — validación desactivada (solo desarrollo)")

        texto      = form.get("Body", "")
        telefono   = form.get("From", "").replace("whatsapp:", "")
        mensaje_id = form.get("MessageSid", "")

        if not texto:
            return []

        return [MensajeEntrante(
            telefono=telefono,
            texto=texto,
            mensaje_id=mensaje_id,
            es_propio=False,
        )]

    async def enviar_mensaje(self, telefono: str, mensaje: str) -> bool:
        creds = self._credenciales()
        account_sid  = creds["account_sid"]
        auth_token   = creds["auth_token"]
        phone_number = creds["phone"]

        if not all([account_sid, auth_token, phone_number]):
            logger.warning(
                f"No se puede enviar: credenciales incompletas — "
                f"SID={'OK' if account_sid else 'FALTA'} "
                f"TOKEN={'OK' if auth_token else 'FALTA'} "
                f"PHONE={'OK' if phone_number else 'FALTA'}"
            )
            return False

        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        auth_header = base64.b64encode(f"{account_sid}:{auth_token}".encode()).decode()

        async with httpx.AsyncClient() as cliente:
            respuesta = await cliente.post(
                url,
                data={
                    "From": f"whatsapp:{phone_number}",
                    "To":   f"whatsapp:{telefono}",
                    "Body": mensaje,
                },
                headers={"Authorization": f"Basic {auth_header}"},
            )

        if respuesta.status_code != 201:
            logger.error(f"Error Twilio al enviar a {telefono}: HTTP {respuesta.status_code} — {respuesta.text[:200]}")
        return respuesta.status_code == 201
