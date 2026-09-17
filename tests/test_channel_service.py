from __future__ import annotations

from datetime import timedelta

import pytest

from config import settings
from database import get_connection
from schemas import ContextCase
from services import cce_service, channel_service, context_service
from utils import now_local


def tv_case() -> ContextCase:
    return ContextCase(
        intent="CANAIS_FORA_DO_AR",
        category="TV",
        problem="Canais HD sem sinal",
        summary="Canais HD sem sinal no decodificador.",
        interaction_summary="Relatou canais HD sem sinal.",
        entities={"equipamento": "decodificador"},
        destination_department="SUPORTE_TV",
        suggested_action="ATUALIZAR_DECODIFICADOR",
        priority="NORMAL",
    )


@pytest.fixture
def fake_ai(monkeypatch):
    calls = []

    def analyze(text, *, channel, department_hint=None, previous=None, resumed=False):
        calls.append({"text": text, "channel": channel, "hint": department_hint, "previous": previous, "resumed": resumed})
        return tv_case()

    monkeypatch.setattr(context_service, "analyze_context", analyze)
    return calls


def verified_access(channel: str, cpf: str, protocol: str | None = None) -> str:
    result = channel_service.identify(channel, cpf, protocol)
    token = result["access_token"]
    if result["verification"] == "SMS":
        channel_service.verify_code(token, result["sms"]["demo_code"])
    return token


def test_first_contact_needs_no_sms_and_opens_a_protocol(fake_ai):
    result = channel_service.identify("WHATSAPP", "987.654.321-00")
    assert result["verification"] == "NENHUMA"
    assert result["verified"] is True
    assert result["has_open_case"] is False

    opened = channel_service.open_message_case(result["access_token"], "Minha TV está sem sinal nos canais HD")
    assert opened["case"]["category"] == "TV"
    assert opened["case"]["department_label"] == "Suporte de TV"
    assert opened["case"]["status"] == "EM_ATENDIMENTO_HUMANO"
    assert fake_ai[0]["channel"] == "WHATSAPP"
    assert fake_ai[0]["resumed"] is False


def test_return_requires_sms_before_revealing_any_context(seeded_history):
    result = channel_service.identify("TELEFONE", "12345678900", "123")
    assert result["protocol_status"] == "OPEN"
    assert result["verification"] == "SMS"
    assert result["verified"] is False
    assert "Internet" not in str(result)  # nada do contexto antes da verificação
    with pytest.raises(channel_service.AccessError):
        channel_service.list_cases(result["access_token"])

    channel_service.verify_code(result["access_token"], result["sms"]["demo_code"])
    cases = channel_service.list_cases(result["access_token"])
    assert cases["focus_protocol"] == "123"
    assert cases["cases"][0]["category_label"] == "Internet"
    assert cases["cases"][0]["last_contact"]["channel_label"] == "WhatsApp"


def test_customer_projection_hides_internal_data(seeded_history):
    token = verified_access("TELEFONE", "12345678900", "123")
    case = channel_service.list_cases(token)["cases"][0]
    assert set(case) & {"cpf", "transcript", "id", "structured_context"} == set()
    assert case["protocol"] == "123"


def test_protocol_of_another_customer_is_not_confirmed(seeded_history):
    result = channel_service.identify("TELEFONE", "98765432100", "123")
    assert result == {"protocol_status": "NOT_FOUND", "access_token": None}


def test_closed_protocol_is_reported_and_does_not_block_new_contact(seeded_history, fake_ai):
    closed = next(case for case in cce_service.list_sessions() if case["status"] == "RESOLVIDA" and case["cpf"] == "88899900011")
    result = channel_service.identify("WHATSAPP", "88899900011", closed["protocol"])
    assert result["protocol_status"] == "CLOSED"
    assert result["closed_protocol"] == closed["protocol"]
    assert result["verification"] == "NENHUMA"
    opened = channel_service.open_message_case(result["access_token"], "Agora minha TV está sem sinal")
    assert opened["case"]["protocol"] != closed["protocol"]


def test_wrong_codes_are_limited_and_expire(seeded_history):
    result = channel_service.identify("WHATSAPP", "12345678900", "123")
    token = result["access_token"]
    wrong = "000000" if result["sms"]["demo_code"] != "000000" else "111111"
    for _ in range(settings.sms_max_attempts - 1):
        with pytest.raises(channel_service.VerificationError, match="incorreto"):
            channel_service.verify_code(token, wrong)
    with pytest.raises(channel_service.VerificationError, match="Muitas tentativas"):
        channel_service.verify_code(token, wrong)
    with pytest.raises(channel_service.VerificationError, match="Muitas tentativas"):
        channel_service.verify_code(token, result["sms"]["demo_code"])


def test_code_is_stored_only_as_hash_and_expires(seeded_history):
    result = channel_service.identify("WHATSAPP", "12345678900", "123")
    token = result["access_token"]
    code = result["sms"]["demo_code"]
    with get_connection() as connection:
        row = connection.execute("SELECT code_hash FROM channel_access WHERE token = ?", (token,)).fetchone()
        assert code not in row["code_hash"]
        connection.execute(
            "UPDATE channel_access SET code_expires_at = ? WHERE token = ?",
            ((now_local() - timedelta(seconds=1)).isoformat(), token),
        )
    with pytest.raises(channel_service.VerificationError, match="expirou"):
        channel_service.verify_code(token, code)


def test_resend_is_limited(seeded_history):
    result = channel_service.identify("WHATSAPP", "12345678900", "123")
    token = result["access_token"]
    for _ in range(settings.sms_max_sends - 1):
        channel_service.resend_code(token)
    with pytest.raises(channel_service.VerificationError, match="Limite de reenvios"):
        channel_service.resend_code(token)


def test_expired_access_is_rejected(seeded_history):
    token = verified_access("MINHA_CLARO", "12345678900")
    with get_connection() as connection:
        connection.execute(
            "UPDATE channel_access SET expires_at = ? WHERE token = ?",
            ((now_local() - timedelta(seconds=1)).isoformat(), token),
        )
    with pytest.raises(channel_service.AccessError, match="expirou"):
        channel_service.list_cases(token)


def test_token_cannot_reach_another_customer_data(seeded_history, fake_ai):
    token = verified_access("WHATSAPP", "98765432100")
    other = cce_service.customer_overview("12345678900")["interactions"][0]
    with pytest.raises(cce_service.NotFoundError):
        channel_service.add_message(token, other["id"], "oi")
    with pytest.raises(cce_service.NotFoundError):
        channel_service.resume(token, "123")


def test_minha_claro_uses_login_and_finishes_the_contact_immediately(fake_ai):
    result = channel_service.identify("MINHA_CLARO", "98765432100")
    assert result["verification"] == "LOGIN"
    opened = channel_service.open_message_case(result["access_token"], "Quero trocar de plano", "PLANOS")
    assert opened["case"]["status"] == "SUSPENSA"
    assert opened["interaction"]["status"] == "CONCLUIDA"
    assert fake_ai[0]["hint"] == "PLANOS"


def test_resume_then_finish_sends_previous_context_to_the_ai(seeded_history, fake_ai):
    token = verified_access("WHATSAPP", "12345678900", "123")
    resumed = channel_service.resume(token, "123")
    interaction_id = resumed["interaction"]["id"]
    channel_service.add_message(token, interaction_id, "A luz do modem continua vermelha")
    finished = channel_service.finish(token, interaction_id, "EM_ABERTO")

    assert fake_ai[0]["resumed"] is True
    assert fake_ai[0]["previous"]["category"] == "INTERNET"
    assert "vermelha" in fake_ai[0]["text"]
    assert finished["case"]["status"] == "Aguardando continuidade" or finished["case"]["status"] == "SUSPENSA"
    assert finished["interaction"]["status"] == "CONCLUIDA"


def test_finish_marked_as_resolved_closes_the_protocol(seeded_history, fake_ai):
    token = verified_access("WHATSAPP", "12345678900", "123")
    resumed = channel_service.resume(token, "123")
    channel_service.add_message(token, resumed["interaction"]["id"], "Já voltou a funcionar, obrigado")
    finished = channel_service.finish(token, resumed["interaction"]["id"], "RESOLVIDO")
    assert finished["case"]["status"] == "RESOLVIDA"
    assert channel_service.list_cases(token)["cases"] == []


def test_finish_without_new_information_keeps_the_protocol_open(seeded_history, fake_ai):
    token = verified_access("WHATSAPP", "12345678900", "123")
    resumed = channel_service.resume(token, "123")
    finished = channel_service.finish(token, resumed["interaction"]["id"])
    assert finished["case"]["open"] is True
    assert "sem novas informações" in finished["interaction"]["summary"]
    assert fake_ai == []


def test_scripted_reply_never_comes_from_the_model(seeded_history, fake_ai):
    token = verified_access("WHATSAPP", "12345678900", "123")
    resumed = channel_service.resume(token, "123")
    answer = channel_service.add_message(token, resumed["interaction"]["id"], "Alguma novidade?")
    assert "protocolo 123" in answer["reply"]["text"]
    assert fake_ai == []


def test_ai_failure_does_not_leave_an_orphan_protocol(monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise context_service.ContextServiceError("IA indisponível.")

    monkeypatch.setattr(context_service, "analyze_context", unavailable)
    result = channel_service.identify("WHATSAPP", "98765432100")
    with pytest.raises(context_service.ContextServiceError):
        channel_service.open_message_case(result["access_token"], "Minha internet caiu")
    assert cce_service.list_sessions() == []
