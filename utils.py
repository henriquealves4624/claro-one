from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from config import settings
from models import CATEGORY_LABELS, CHANNEL_LABELS, DESTINATION_LABELS, STATUS_LABELS


TZ = ZoneInfo(settings.timezone)


def now_local() -> datetime:
    return datetime.now(TZ)


def parse_datetime(value: str | datetime) -> datetime:
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=TZ)


def normalize_cpf(cpf: str) -> str:
    digits = re.sub(r"\D", "", cpf or "")
    if len(digits) != 11:
        raise ValueError("Informe um CPF com 11 dígitos.")
    return digits


def format_cpf(cpf: str) -> str:
    digits = normalize_cpf(cpf)
    return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"


def mask_cpf(cpf: str) -> str:
    digits = normalize_cpf(cpf)
    return f"***.{digits[3:6]}.{digits[6:9]}-**"


def mask_phone(phone: str) -> str:
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) < 6:
        return "celular cadastrado"
    return f"({digits[:2]}) •••••-{digits[-4:]}"


def format_datetime(value: str | datetime | None) -> str:
    if not value:
        return "—"
    return parse_datetime(value).astimezone(TZ).strftime("%d/%m/%Y às %H:%M")


def format_time(value: str | datetime | None) -> str:
    if not value:
        return "—"
    return parse_datetime(value).astimezone(TZ).strftime("%H:%M")


def friendly_label(value: str | None) -> str:
    if not value:
        return "Não identificado"
    for labels in (CATEGORY_LABELS, DESTINATION_LABELS, CHANNEL_LABELS, STATUS_LABELS):
        if value in labels:
            return labels[value]
    return value.replace("_", " ").strip().capitalize()


def format_currency(value: Any) -> str:
    try:
        number = Decimal(str(value))
    except Exception:
        return str(value)
    formatted = f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {formatted}"


def slugify_filename_suffix(filename: str) -> str:
    name = unicodedata.normalize("NFKD", filename)
    return re.sub(r"[^a-z0-9.]", "", name.lower())
