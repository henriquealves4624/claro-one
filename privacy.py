"""Minimização de dados pessoais antes e depois das IAs.

Todo texto livre (transcrição, mensagem ou formulário) passa por `redact` antes de ser
persistido ou enviado à Groq. Toda saída da IA passa por `sanitize_*` antes de chegar
ao banco ou a qualquer tela, inclusive se o modelo for induzido a repetir um dado.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

MAX_ENTITIES = 8
MAX_ENTITY_VALUE = 120

_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CNPJ = re.compile(r"(?<!\d)\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}(?!\d)")
_CPF_FORMATTED = re.compile(r"(?<!\d)\d{3}\.\d{3}\.\d{3}-\d{2}(?!\d)")
_CARD = re.compile(r"(?<!\d)(?:\d[ -]?){12,18}\d(?!\d)")
_ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")
_PHONE = re.compile(r"(?<!\d)(?:\+?55[\s-]?)?(?:\(?\d{2}\)?[\s-]?)?9?\d{4}[\s-]?\d{4}(?!\d)")
_SECRET = re.compile(
    r"\b(senhas?|password|pin|cvv|cvc|c[óo]digo(?:\s+de)?\s+(?:seguran[çc]a|verifica[çc][ãa]o|acesso)|token)"
    r"(\s*(?:[:=]|é|eh|e|seria)?\s*)((?=\S*\d)\S+)",
    re.IGNORECASE,
)
_BANK = re.compile(
    r"\b(ag[êe]ncia|conta(?:\s+corrente|\s+poupan[çc]a)?)(\s*(?:n[º°o.]*)?\s*[:\-]?\s*)(\d[\d.\-]{3,}\d)",
    re.IGNORECASE,
)

_SENSITIVE_KEY_TOKENS = {
    "cpf", "cnpj", "rg", "senha", "password", "cartao", "card", "cvv", "cvc", "token", "pin",
    "email", "mail", "telefone", "celular", "fone", "whatsapp", "endereco", "logradouro",
    "cep", "agencia", "pix", "nascimento",
}


def _luhn_valid(digits: str) -> bool:
    total = 0
    for index, char in enumerate(reversed(digits)):
        value = int(char)
        if index % 2:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total % 10 == 0


def redact(text: str | None) -> tuple[str, int]:
    """Mascara dados pessoais e sensíveis. Retorna o texto e a quantidade de trechos mascarados."""
    if not text:
        return text or "", 0
    count = 0

    def replace_with(label: str):
        def _replace(match: re.Match) -> str:
            nonlocal count
            count += 1
            return label

        return _replace

    def replace_secret(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{match.group(2)}[DADO SENSÍVEL]"

    def replace_bank(match: re.Match) -> str:
        nonlocal count
        count += 1
        return f"{match.group(1)}{match.group(2)}[DADOS BANCÁRIOS]"

    def replace_card(match: re.Match) -> str:
        nonlocal count
        digits = re.sub(r"\D", "", match.group(0))
        if 13 <= len(digits) <= 19 and _luhn_valid(digits):
            count += 1
            return "[CARTÃO]"
        return match.group(0)

    def replace_eleven(match: re.Match) -> str:
        nonlocal count
        count += 1
        digits = match.group(0)
        # Celular brasileiro: DDD sem zero seguido do nono dígito.
        return "[TELEFONE]" if re.fullmatch(r"[1-9]{2}9\d{8}", digits) else "[CPF]"

    result = _SECRET.sub(replace_secret, text)
    result = _BANK.sub(replace_bank, result)
    result = _EMAIL.sub(replace_with("[E-MAIL]"), result)
    result = _CNPJ.sub(replace_with("[CNPJ]"), result)
    result = _CPF_FORMATTED.sub(replace_with("[CPF]"), result)
    result = _CARD.sub(replace_card, result)
    result = _ELEVEN_DIGITS.sub(replace_eleven, result)
    result = _PHONE.sub(replace_with("[TELEFONE]"), result)
    return result, count


def sanitize_text(value: Any, max_length: int = 400) -> tuple[str | None, int]:
    if value is None:
        return None, 0
    text = re.sub(r"\s+", " ", str(value)).strip()
    if not text:
        return None, 0
    cleaned, count = redact(text)
    if len(cleaned) > max_length:
        cleaned = cleaned[: max_length - 1].rstrip() + "…"
    return cleaned, count


def _key_tokens(key: str) -> set[str]:
    normalized = unicodedata.normalize("NFKD", key).encode("ascii", "ignore").decode().lower()
    return set(re.split(r"[^a-z0-9]+", normalized)) - {""}


def is_sensitive_key(key: str) -> bool:
    tokens = _key_tokens(key)
    if tokens & _SENSITIVE_KEY_TOKENS:
        return True
    return "conta" in tokens and bool(tokens & {"bancaria", "corrente", "poupanca"})


def sanitize_entities(entities: dict[str, Any] | None) -> tuple[dict[str, Any], int]:
    """Mantém apenas entidades simples, sem chaves sensíveis e com valores mascarados."""
    result: dict[str, Any] = {}
    removed = 0
    for key, value in (entities or {}).items():
        if len(result) >= MAX_ENTITIES:
            break
        key = str(key).strip()[:60]
        if not key or is_sensitive_key(key):
            removed += 1
            continue
        if isinstance(value, (dict, list)):
            removed += 1
            continue
        if isinstance(value, str):
            cleaned, count = sanitize_text(value, MAX_ENTITY_VALUE)
            removed += count
            if cleaned is None:
                continue
            value = cleaned
        result[key] = value
    return result, removed
