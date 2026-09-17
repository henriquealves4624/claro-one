from __future__ import annotations

import pytest

from models import taxonomy_payload
from utils import format_cpf, format_currency, friendly_label, mask_cpf, mask_phone, normalize_cpf


def test_normalize_formatted_and_plain_cpf():
    assert normalize_cpf("123.456.789-00") == "12345678900"
    assert normalize_cpf("12345678900") == "12345678900"


def test_reject_invalid_cpf_length():
    with pytest.raises(ValueError):
        normalize_cpf("123")


def test_format_and_mask_cpf():
    assert format_cpf("12345678900") == "123.456.789-00"
    assert mask_cpf("12345678900") == "***.456.789-**"


def test_mask_phone_keeps_only_area_code_and_last_digits():
    assert mask_phone("11900000001") == "(11) •••••-0001"
    assert mask_phone("") == "celular cadastrado"


def test_brazilian_currency():
    assert format_currency(35) == "R$ 35,00"


def test_taxonomy_has_friendly_labels():
    assert friendly_label("SUPORTE_TELEFONIA") == "Suporte de telefonia"
    assert friendly_label("SERVICOS_CAMPO") == "Serviços de campo"
    assert friendly_label("OUTROS") == "Outros assuntos"
    assert friendly_label("WHATSAPP") == "WhatsApp"
    assert friendly_label("SUSPENSA") == "Aguardando continuidade"


def test_taxonomy_payload_is_complete_for_the_frontend():
    payload = taxonomy_payload()
    assert len(payload["categories"]) == 8
    assert all({"value", "label", "department", "departmentLabel", "area"} <= set(item) for item in payload["categories"])
    assert payload["customerChannels"] == ["TELEFONE", "WHATSAPP", "MINHA_CLARO"]
    assert payload["statuses"]["EM_ATENDIMENTO_HUMANO"] == "Com especialista"
