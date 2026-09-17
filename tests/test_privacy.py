from __future__ import annotations

import pytest

import privacy


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Meu CPF é 123.456.789-00", "[CPF]"),
        ("cpf 12345678900 por favor", "[CPF]"),
        ("Ligue para 11987650011", "[TELEFONE]"),
        ("Meu telefone é (11) 98765-0011", "[TELEFONE]"),
        ("Envie para cliente@exemplo.com.br", "[E-MAIL]"),
        ("CNPJ 12.345.678/0001-95 da empresa", "[CNPJ]"),
        ("cartão 4111 1111 1111 1111", "[CARTÃO]"),
        ("minha senha é claro2026", "[DADO SENSÍVEL]"),
        ("o código de verificação é 482913", "[DADO SENSÍVEL]"),
        ("agência 1234 conta corrente 56789-0", "[DADOS BANCÁRIOS]"),
    ],
)
def test_sensitive_data_is_masked(text, expected):
    masked, count = privacy.redact(text)
    assert expected in masked
    assert count >= 1
    assert "4111" not in masked


@pytest.mark.parametrize(
    "text",
    [
        "Meu protocolo é 482913",
        "A cobrança foi de R$ 35,00",
        "O técnico veio em 17/09/2026",
        "Tenho 3 aparelhos conectados",
    ],
)
def test_ordinary_content_is_preserved(text):
    masked, count = privacy.redact(text)
    assert masked == text
    assert count == 0


def test_masking_is_idempotent():
    once, _ = privacy.redact("CPF 123.456.789-00")
    twice, count = privacy.redact(once)
    assert once == twice
    assert count == 0


def test_entities_drop_sensitive_keys_and_limit_size():
    entities = {
        "valor": 35.0,
        "cpf_do_titular": "123.456.789-00",
        "senha": "abc123",
        "cartao_final": "4111111111111111",
        "email_contato": "a@b.com",
        "endereco": "Rua Um, 100",
        "observacao": "Cliente ligou do número 11987650011",
        "detalhes": {"nested": True},
    }
    cleaned, removed = privacy.sanitize_entities(entities)
    assert cleaned["valor"] == 35.0
    assert cleaned["observacao"] == "Cliente ligou do número [TELEFONE]"
    assert set(cleaned) == {"valor", "observacao"}
    assert removed >= 6


def test_entity_limit_and_value_truncation():
    entities = {f"chave_{index}": "x" * 200 for index in range(20)}
    cleaned, _ = privacy.sanitize_entities(entities)
    assert len(cleaned) == privacy.MAX_ENTITIES
    assert all(len(value) <= privacy.MAX_ENTITY_VALUE for value in cleaned.values())


def test_sanitize_text_trims_and_masks():
    cleaned, count = privacy.sanitize_text("  Cliente  com  CPF 123.456.789-00  ", 400)
    assert cleaned == "Cliente com CPF [CPF]"
    assert count == 1
