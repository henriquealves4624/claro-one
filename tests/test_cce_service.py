from __future__ import annotations

from datetime import timedelta

import pytest

from schemas import ContextCase
from services import cce_service
from utils import now_local


def internet_case(interaction_summary: str = "Cliente relatou modem com luz vermelha.") -> ContextCase:
    return ContextCase(
        intent="INTERNET_SEM_CONEXAO",
        category="INTERNET",
        problem="Internet sem conexão",
        summary="Cliente sem internet; modem com luz vermelha.",
        interaction_summary=interaction_summary,
        entities={"luz_modem": "vermelha"},
        destination_department="SUPORTE_TECNICO",
        suggested_action="DIAGNOSTICAR_CONEXAO",
        priority="ALTA",
    )


def open_phone_case(cpf: str = "12345678900"):
    return cce_service.create_case(
        cpf, "TELEFONE", department="INTERNET", input_kind="AUDIO", verification="NENHUMA", status="EM_ATENDIMENTO"
    )


def test_case_creation_registers_numeric_protocol_and_first_contact():
    session, interaction = open_phone_case()
    assert session["status"] == "EM_ATENDIMENTO"
    assert session["protocol"].isdigit() and len(session["protocol"]) == 6
    assert session["customer_name"] == "Lucas de Alencar"
    assert interaction["interaction_type"] == "ABERTURA"
    assert interaction["channel"] == "TELEFONE"
    events = [event["event_type"] for event in cce_service.get_timeline(session["id"])]
    assert events == ["CUSTOMER_AUTHENTICATED", "DEPARTMENT_SELECTED", "SESSION_CREATED"]


def test_context_finishes_contact_and_keeps_case_open_for_continuity():
    session, interaction = open_phone_case()
    cce_service.update_interaction(interaction["id"], transcript="Minha internet caiu.")
    session, interaction = cce_service.apply_context(interaction["id"], internet_case(), finish=True)
    assert session["status"] == "SUSPENSA"
    assert session["category"] == "INTERNET"
    assert session["destination_department"] == "SUPORTE_TECNICO"
    assert interaction["status"] == "CONCLUIDA"
    assert interaction["summary"] == "Cliente relatou modem com luz vermelha."
    assert session["summary"] != interaction["summary"]
    assert cce_service.find_open_cases("123.456.789-00")[0]["id"] == session["id"]


def test_resume_registers_new_contact_renews_validity_and_keeps_history():
    session, interaction = open_phone_case()
    session, _ = cce_service.apply_context(interaction["id"], internet_case(), finish=True)
    previous_expiration = session["expires_at"]

    resumed, contact = cce_service.resume_case(session["id"], "WHATSAPP", verification="SMS", route_human=True)
    assert resumed["status"] == "EM_ATENDIMENTO_HUMANO"
    assert resumed["current_channel"] == "WHATSAPP"
    assert resumed["expires_at"] >= previous_expiration
    assert contact["interaction_type"] == "RETOMADA"
    assert contact["problem"] == "Internet sem conexão"
    assert "sem repetir a triagem" in contact["summary"]

    overview = cce_service.customer_overview("12345678900")
    assert [item["channel"] for item in overview["interactions"]] == ["TELEFONE", "WHATSAPP"]
    assert {item["protocol"] for item in overview["interactions"]} == {session["protocol"]}


def test_same_cpf_may_keep_more_than_one_open_protocol():
    first, first_contact = open_phone_case()
    cce_service.apply_context(first_contact["id"], internet_case(), finish=True)
    second, second_contact = cce_service.create_case(
        "12345678900", "WHATSAPP", department=None, input_kind="CONVERSA", verification="NENHUMA", status="PROCESSANDO"
    )
    cce_service.apply_context(second_contact["id"], internet_case("Outro tema"), finish=True)
    protocols = {case["protocol"] for case in cce_service.find_open_cases("12345678900")}
    assert protocols == {first["protocol"], second["protocol"]}


def test_expired_case_is_not_resumable():
    session, interaction = open_phone_case()
    session, _ = cce_service.apply_context(interaction["id"], internet_case(), finish=True)
    cce_service.update_session(session["id"], expires_at=(now_local() - timedelta(seconds=1)).isoformat())
    assert cce_service.find_open_cases(session["cpf"]) == []
    with pytest.raises(cce_service.SessionUnavailableError):
        cce_service.resume_case(session["id"], "WHATSAPP", verification="SMS", route_human=True)
    assert cce_service.get_session(session["id"])["status"] == "EXPIRADA"


def test_resolution_closes_open_contacts_and_blocks_resume():
    session, interaction = open_phone_case()
    session, _ = cce_service.apply_context(interaction["id"], internet_case(), finish=True)
    cce_service.resume_case(session["id"], "MINHA_CLARO", verification="LOGIN", route_human=False)
    resolved = cce_service.resolve_session(session["id"])
    assert resolved["status"] == "RESOLVIDA"
    assert resolved["resolved_at"]
    contacts = cce_service.customer_overview(session["cpf"])["interactions"]
    assert all(contact["status"] == "CONCLUIDA" for contact in contacts)
    assert cce_service.find_open_cases(session["cpf"]) == []
    with pytest.raises(cce_service.SessionUnavailableError):
        cce_service.resume_case(session["id"], "WHATSAPP", verification="SMS", route_human=True)


def test_handoff_assigns_agent_to_case_and_latest_contact():
    session, interaction = open_phone_case()
    session, _ = cce_service.apply_context(interaction["id"], internet_case(), finish=True)
    updated = cce_service.handoff_session(session["id"], "Atendente Demo")
    assert updated["assigned_agent"] == "Atendente Demo"
    assert updated["status"] == "EM_ATENDIMENTO_HUMANO"
    assert updated["current_channel"] == "TELEFONE"  # o canal do cliente não vira "Cockpit"
    latest = cce_service.customer_overview(session["cpf"])["interactions"][-1]
    assert latest["agent"] == "Atendente Demo"


def test_transcript_is_masked_and_audio_released_for_deletion(tmp_path):
    session, interaction = open_phone_case()
    audio = tmp_path / "gravacao.webm"
    audio.write_bytes(b"\x1a\x45\xdf\xa3" + b"\x00" * 512)
    cce_service.register_audio(interaction["id"], str(audio))
    cce_service.start_transcription(interaction["id"])
    updated, released = cce_service.store_transcript(interaction["id"], "Aqui é o Lucas, CPF 123.456.789-00, sem internet.")
    assert "[CPF]" in updated["transcript"]
    assert "123.456.789-00" not in updated["transcript"]
    assert released == str(audio)
    assert updated["audio_path"] is None


def test_messages_are_masked_and_only_customer_text_feeds_the_ai():
    session, interaction = cce_service.create_case(
        "12345678900", "WHATSAPP", department=None, input_kind="CONVERSA", verification="NENHUMA", status="PROCESSANDO"
    )
    cce_service.add_message(interaction["id"], "CLIENTE", "Meu cartão 4111 1111 1111 1111 foi cobrado")
    cce_service.add_message(interaction["id"], "CLARO", "Recebido, vamos verificar.")
    stored = cce_service.get_messages(interaction["id"])
    assert "[CARTÃO]" in stored[0]["text"]
    assert cce_service.customer_text(interaction["id"]) == stored[0]["text"]


def test_cancelling_the_opening_contact_removes_the_protocol():
    session, interaction = open_phone_case()
    cce_service.delete_interaction(interaction["id"])
    with pytest.raises(cce_service.NotFoundError):
        cce_service.get_session(session["id"])


def test_customer_search_matches_cpf_protocol_department_and_channel(seeded_history):
    by_protocol = cce_service.list_customers("123")
    assert [customer["name"] for customer in by_protocol] == ["Lucas de Alencar"]
    assert cce_service.list_customers("456.789")[0]["cpf"] == "12345678900"
    assert "Rafael Nogueira" in {customer["name"] for customer in cce_service.list_customers("financeiro")}
    whatsapp = cce_service.list_customers("", "", "WHATSAPP")
    assert whatsapp and all("WHATSAPP" in customer["channels"] for customer in whatsapp)
    assert cce_service.list_customers("", "SUPORTE_TECNICO") != []
    assert cce_service.list_customers("cliente-inexistente") == []
