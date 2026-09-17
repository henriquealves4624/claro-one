"""Envio do código de verificação por SMS.

O padrão é o modo simulado (sem custo): o código aparece como notificação no dispositivo
simulado. O modo "twilio" é opcional e usa a API REST da Twilio com uma conta própria;
nesse modo o código não é devolvido ao navegador.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import httpx

from config import settings


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SmsDelivery:
    mode: str
    reveal_code: bool
    notice: str | None = None


def _message(code: str) -> str:
    return f"Claro One: seu código de verificação é {code}. Ele expira em {settings.sms_code_minutes} min. Não compartilhe."


def _e164(phone: str) -> str:
    digits = re.sub(r"\D", "", phone)
    return f"+{digits}" if digits.startswith("55") else f"+55{digits}"


def _send_with_twilio(code: str) -> None:
    missing = [
        name
        for name, value in (
            ("TWILIO_ACCOUNT_SID", settings.twilio_account_sid),
            ("TWILIO_AUTH_TOKEN", settings.twilio_auth_token),
            ("TWILIO_FROM_NUMBER", settings.twilio_from_number),
            ("SMS_TEST_DESTINATION", settings.sms_test_destination),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(f"Configuração ausente: {', '.join(missing)}")
    response = httpx.post(
        f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json",
        auth=(settings.twilio_account_sid, settings.twilio_auth_token),
        data={
            "To": _e164(settings.sms_test_destination),
            "From": settings.twilio_from_number,
            "Body": _message(code),
        },
        timeout=10,
    )
    response.raise_for_status()


def send_verification_code(code: str) -> SmsDelivery:
    if settings.sms_provider == "twilio":
        try:
            _send_with_twilio(code)
            return SmsDelivery(mode="REAL", reveal_code=False)
        except Exception:
            logger.warning("Falha no envio real de SMS; usando o modo simulado", exc_info=True)
            return SmsDelivery(
                mode="SIMULADO",
                reveal_code=True,
                notice="O envio real falhou. O código foi exibido no modo simulado.",
            )
    return SmsDelivery(mode="SIMULADO", reveal_code=True)
