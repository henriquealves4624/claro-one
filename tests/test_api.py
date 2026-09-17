from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app import app
from routes.pages import ASSET_VERSION
from schemas import ContextCase
from services import cce_service, context_service


PAGES = ("/", "/telefone", "/whatsapp", "/minha-claro", "/atendente", "/debug")


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def webm_bytes(size: int = 512) -> bytes:
    return b"\x1a\x45\xdf\xa3" + b"\x00" * (size - 4)


def internet_case(interaction_summary: str = "Cliente relatou internet fora do ar.") -> ContextCase:
    return ContextCase(
        intent="INTERNET_SEM_CONEXAO",
        category="INTERNET",
        problem="Internet sem funcionar",
        summary="Cliente informa indisponibilidade da internet.",
        interaction_summary=interaction_summary,
        entities={"desde": "ontem"},
        destination_department="SUPORTE_TECNICO",
        suggested_action="DIAGNOSTICAR_CONEXAO",
        priority="NORMAL",
    )


def identify(client: TestClient, channel: str, cpf: str, protocol: str | None = None) -> dict:
    response = client.post("/api/channel/identify", json={"channel": channel, "cpf": cpf, "protocol": protocol})
    assert response.status_code == 200
    return response.json()


def verified_headers(client: TestClient, channel: str, cpf: str, protocol: str | None = None) -> dict:
    result = identify(client, channel, cpf, protocol)
    headers = {"X-Channel-Token": result["access_token"]}
    if result["verification"] == "SMS":
        confirmed = client.post("/api/channel/verify", json={"code": result["sms"]["demo_code"]}, headers=headers)
        assert confirmed.status_code == 200
    return headers


# ---------------------------------------------------------------- páginas

def test_pages_open_with_the_shared_shell(client):
    for path in PAGES:
        response = client.get(path)
        assert response.status_code == 200
        assert "Protótipo acadêmico" in response.text
        assert '<span class="brand-mark">CCE</span>' in response.text
        assert "C1" not in response.text


def test_header_keeps_only_home_and_cockpit(client):
    for path in PAGES:
        header = re.search(r'<header class="topbar">(.*?)</header>', client.get(path).text, re.DOTALL)
        assert header
        markup = header.group(1)
        assert 'class="brand" href="/"' in markup and 'href="/atendente"' in markup
        assert 'href="/telefone"' not in markup and 'href="/whatsapp"' not in markup


def test_home_presents_three_simulations_and_the_cockpit_delivery(client):
    home = client.get("/").text
    assert "SIMULAÇÃO DE CANAIS" in home
    assert "CANAIS CONECTADOS" not in home
    assert "O contexto é o mesmo" not in home
    channel_cards = re.findall(r'class="channel-card[^"]*" href="(/[^"]+)"', home)
    assert channel_cards == ["/telefone", "/whatsapp", "/minha-claro"]
    assert 'class="cockpit-card"' in home
    assert 'href="/atendente?aba=gestor"' in home
    for node in ("CLIENTE", "CPF + PROTOCOLO", "ATENDENTE CLARO", "RETORNO AO CLIENTE"):
        assert node in home
    assert "retroalimenta a CCE" in home


def test_the_prototype_does_not_expose_the_context_window_duration(client):
    for path in PAGES:
        markup = client.get(path).text
        assert "02:00:00" not in markup
        assert "Sessão disponível por" not in markup
        assert not re.search(r"TTL", markup)
        assert "duas horas" not in markup


def test_cockpit_shell_has_search_manager_tab_and_no_simulated_label(client):
    cockpit = client.get("/atendente").text
    assert "Clientes encontrados" in cockpit
    assert "Sessões relevantes" not in cockpit
    assert "Ambiente simulado" not in cockpit
    assert 'id="customer-search"' in cockpit
    assert 'placeholder="CPF, protocolo, departamento ou canal"' in cockpit
    assert 'data-tab="gestor"' in cockpit
    for element in ('id="cp-timeline"', 'id="executive-card"', 'id="tl-channel"', 'id="tl-from"', 'id="snapshot-back"'):
        assert element in cockpit


def test_taxonomy_is_shared_with_the_frontend_by_one_source(client):
    cockpit = client.get("/atendente").text
    taxonomy = re.search(r'<script id="claro-taxonomy" type="application/json">(.*?)</script>', cockpit, re.DOTALL)
    assert taxonomy and "SUPORTE_TV" in taxonomy.group(1)
    assert '<option value="SERVICOS_CAMPO">Serviços de campo</option>' in cockpit
    common = client.get("/static/js/common.js").text
    assert "categoryLabels" not in common  # sem duplicação de rótulos no JavaScript


def test_static_assets_share_one_version_and_common_js_loads_first(client):
    for path in PAGES:
        markup = client.get(path).text
        urls = re.findall(r'(?:src|href)="([^"]*/static/[^"]+)"', markup)
        assert urls and all(url.endswith(f"?v={ASSET_VERSION}") for url in urls)
    whatsapp = client.get("/whatsapp").text
    assert whatsapp.index("/static/js/common.js") < whatsapp.index("/static/js/whatsapp.js")


# ---------------------------------------------------------------- canais

def test_phone_first_contact_creates_context_from_audio(client, monkeypatch):
    transcript = "Minha internet está sem funcionar desde ontem e o modem está vermelho."
    monkeypatch.setattr(context_service, "analyze_context", lambda text, **kwargs: internet_case())
    monkeypatch.setattr("services.transcription_service.transcribe_audio", lambda _path, _channel=None: transcript)

    headers = verified_headers(client, "TELEFONE", "987.654.321-00")
    opened = client.post("/api/channel/cases/phone", json={"department": "INTERNET"}, headers=headers)
    assert opened.status_code == 201
    interaction_id = opened.json()["interaction"]["id"]
    protocol = opened.json()["case"]["protocol"]
    assert protocol.isdigit()

    assert client.post(f"/api/channel/interactions/{interaction_id}/call/start", headers=headers).status_code == 200
    uploaded = client.post(
        f"/api/channel/interactions/{interaction_id}/audio",
        data={"duration_ms": "2500"},
        files={"audio": ("gravacao.webm", webm_bytes(), "audio/webm")},
        headers=headers,
    )
    assert uploaded.status_code == 200
    assert client.post(f"/api/channel/interactions/{interaction_id}/transcribe", headers=headers).status_code == 200
    finished = client.post(f"/api/channel/interactions/{interaction_id}/finish", json={"outcome": "EM_ABERTO"}, headers=headers)
    assert finished.status_code == 200
    case = finished.json()["case"]
    assert case["status"] == "SUSPENSA" and case["category"] == "INTERNET"
    assert finished.json()["interaction"]["summary"] == "Cliente relatou internet fora do ar."

    stored = next(item for item in client.get("/api/sessions").json() if item["protocol"] == protocol)
    detail = client.get(f"/api/sessions/{stored['id']}").json()
    assert [event["event_type"] for event in detail["events"]][:4] == [
        "CUSTOMER_AUTHENTICATED", "DEPARTMENT_SELECTED", "SESSION_CREATED", "CALL_STARTED"
    ]
    assert detail["interactions"][0]["audio_available"] is False  # gravação descartada após a transcrição
    from config import settings

    assert [path.name for path in settings.upload_dir.iterdir()] == []


def test_phone_return_asks_for_the_sms_code_before_the_context(client, seeded_history):
    result = identify(client, "TELEFONE", "12345678900", "123")
    assert result["verification"] == "SMS" and result["verified"] is False
    headers = {"X-Channel-Token": result["access_token"]}
    assert client.get("/api/channel/cases", headers=headers).status_code == 401

    wrong = "000000" if result["sms"]["demo_code"] != "000000" else "111111"
    assert client.post("/api/channel/verify", json={"code": wrong}, headers=headers).status_code == 400
    assert client.post("/api/channel/verify", json={"code": result["sms"]["demo_code"]}, headers=headers).status_code == 200

    cases = client.get("/api/channel/cases", headers=headers).json()
    assert cases["focus_protocol"] == "123"
    resumed = client.post("/api/channel/cases/123/resume", headers=headers)
    assert resumed.status_code == 200
    assert resumed.json()["case"]["status"] == "EM_ATENDIMENTO_HUMANO"


def test_unknown_protocol_is_reported_without_a_token(client, seeded_history):
    result = identify(client, "TELEFONE", "98765432100", "123")
    assert result == {"protocol_status": "NOT_FOUND", "access_token": None}
    assert identify(client, "WHATSAPP", "12345678900", "999999")["protocol_status"] == "NOT_FOUND"


def test_channel_calls_require_a_token(client):
    assert client.get("/api/channel/cases").status_code == 401
    assert client.post("/api/channel/cases", json={"message": "Minha internet caiu"}).status_code == 401
    assert client.post("/api/channel/cases/123/resume").status_code == 401


def test_unknown_customer_and_invalid_cpf_are_friendly(client):
    missing = client.post("/api/channel/identify", json={"channel": "WHATSAPP", "cpf": "00000000000"})
    assert missing.status_code == 404
    assert "CPF" in missing.json()["detail"]
    invalid = client.post("/api/channel/identify", json={"channel": "WHATSAPP", "cpf": "123"})
    assert invalid.status_code == 400


def test_whatsapp_conversation_creates_classifies_and_closes_the_protocol(client, monkeypatch):
    monkeypatch.setattr(context_service, "analyze_context", lambda text, **kwargs: internet_case("Conversa consolidada."))
    headers = verified_headers(client, "WHATSAPP", "987.654.321-00")
    created = client.post("/api/channel/cases", json={"message": "Minha internet caiu desde ontem"}, headers=headers)
    assert created.status_code == 201
    interaction_id = created.json()["interaction"]["id"]
    assert created.json()["case"]["status"] == "EM_ATENDIMENTO_HUMANO"

    answer = client.post(
        f"/api/channel/interactions/{interaction_id}/messages",
        json={"text": "O modem está com a luz vermelha"},
        headers=headers,
    )
    assert answer.status_code == 201
    assert answer.json()["reply"]["text"]

    finished = client.post(f"/api/channel/interactions/{interaction_id}/finish", json={"outcome": "RESOLVIDO"}, headers=headers)
    assert finished.status_code == 200
    assert finished.json()["case"]["status"] == "RESOLVIDA"
    assert client.get("/api/channel/cases", headers=headers).json()["cases"] == []


def test_minha_claro_registers_a_request_without_sms(client, monkeypatch):
    monkeypatch.setattr(context_service, "analyze_context", lambda text, **kwargs: internet_case())
    result = identify(client, "MINHA_CLARO", "987.654.321-00")
    assert result["verification"] == "LOGIN" and result["verified"] is True
    headers = {"X-Channel-Token": result["access_token"]}
    created = client.post(
        "/api/channel/cases",
        json={"message": "Quero abrir um chamado de internet", "area_category": "INTERNET"},
        headers=headers,
    )
    assert created.status_code == 201
    assert created.json()["case"]["area"] == "internet"
    assert created.json()["interaction"]["status"] == "CONCLUIDA"


def test_whatsapp_ai_failure_does_not_leave_an_orphan_protocol(client, monkeypatch):
    def unavailable(*_args, **_kwargs):
        raise context_service.ContextServiceError("IA de contextualização indisponível.")

    monkeypatch.setattr(context_service, "analyze_context", unavailable)
    headers = verified_headers(client, "WHATSAPP", "987.654.321-00")
    response = client.post("/api/channel/cases", json={"message": "Minha linha não realiza chamadas."}, headers=headers)
    assert response.status_code == 503
    assert client.get("/api/sessions").json() == []


def test_invalid_uploads_are_rejected_before_any_external_call(client):
    headers = verified_headers(client, "TELEFONE", "987.654.321-00")
    interaction_id = client.post("/api/channel/cases/phone", json={"department": "INTERNET"}, headers=headers).json()["interaction"]["id"]

    wrong_format = client.post(
        f"/api/channel/interactions/{interaction_id}/audio",
        files={"audio": ("anotacoes.txt", b"nao e audio", "text/plain")},
        headers=headers,
    )
    assert wrong_format.status_code == 400 and "WEBM ou OGG" in wrong_format.json()["detail"]

    fake_wav = client.post(
        f"/api/channel/interactions/{interaction_id}/audio",
        files={"audio": ("gravacao.wav", b"isto nao e um wav", "audio/wav")},
        headers=headers,
    )
    assert fake_wav.status_code == 422 and "gravação" in fake_wav.json()["detail"]

    empty = client.post(
        f"/api/channel/interactions/{interaction_id}/audio",
        files={"audio": ("gravacao.webm", b"", "audio/webm")},
        headers=headers,
    )
    assert empty.status_code == 400 and "vazio" in empty.json()["detail"]

    too_short = client.post(
        f"/api/channel/interactions/{interaction_id}/audio",
        data={"duration_ms": "400"},
        files={"audio": ("gravacao.webm", webm_bytes(), "audio/webm")},
        headers=headers,
    )
    assert too_short.status_code == 400 and "curta demais" in too_short.json()["detail"]


def test_cancelling_a_call_removes_the_protocol(client):
    headers = verified_headers(client, "TELEFONE", "987.654.321-00")
    opened = client.post("/api/channel/cases/phone", json={"department": "INTERNET"}, headers=headers).json()
    removed = client.delete(f"/api/channel/interactions/{opened['interaction']['id']}", headers=headers)
    assert removed.status_code == 200
    assert client.get("/api/sessions").json() == []


# ---------------------------------------------------------------- cockpit e gestor

def test_cockpit_search_filters_and_customer_overview(client, seeded_history):
    customers = client.get("/api/cockpit/customers").json()
    assert customers[0]["last_contact_at"] >= customers[-1]["last_contact_at"]
    assert all("masked_cpf" in customer for customer in customers)

    by_protocol = client.get("/api/cockpit/customers?q=123").json()
    assert [customer["name"] for customer in by_protocol] == ["Lucas de Alencar"]
    assert client.get("/api/cockpit/customers?department=FINANCEIRO").json()
    assert client.get("/api/cockpit/customers?channel=MINHA_CLARO").json()

    overview = client.get("/api/cockpit/customers/12345678900").json()
    assert overview["customer"]["masked_cpf"] == "***.456.789-**"
    assert [item["channel"] for item in overview["interactions"]] == ["MINHA_CLARO", "TELEFONE", "WHATSAPP"]
    assert all("transcript" not in item for item in overview["interactions"])
    assert all("transcript" not in case for case in overview["cases"])
    assert overview["interactions"][-1]["summary"]
    assert overview["interactions"][-1]["agent"] == "Paula Ribeiro"


def test_cockpit_record_shows_the_conversation_of_one_contact(client, seeded_history):
    overview = client.get("/api/cockpit/customers/12345678900").json()
    whatsapp = next(item for item in overview["interactions"] if item["channel"] == "WHATSAPP")
    record = client.get(f"/api/cockpit/interactions/{whatsapp['id']}/record").json()
    assert record["input_kind"] == "CONVERSA"
    assert record["messages"] and record["messages"][0]["author"] == "CLIENTE"
    assert record["protocol"] == "123"


def test_cockpit_handoff_and_resolution(client, seeded_history):
    case = cce_service.find_case_by_protocol("123")
    assumed = client.post(f"/api/sessions/{case['id']}/handoff")
    assert assumed.status_code == 200
    assert assumed.json()["assigned_agent"] == "Atendente Demo"
    resolved = client.post(f"/api/sessions/{case['id']}/resolve")
    assert resolved.status_code == 200 and resolved.json()["status"] == "RESOLVIDA"
    assert client.post(f"/api/sessions/{case['id']}/resolve").status_code == 200


def test_metrics_endpoint_returns_the_dashboard_payload(client, seeded_history):
    data = client.get("/api/cockpit/metrics?days=30").json()
    assert data["kpis"]["contacts"] == 20
    assert data["period_days"] == 30
    assert len(data["daily"]) >= 14
    assert data["handoff_flows"]
    assert {stage["stage"] for stage in data["ai_health"]} == {"TRANSCRICAO", "CONTEXTO", "RESUMO_EXECUTIVO"}
    assert client.get("/api/cockpit/metrics?days=0").json()["period_days"] is None


def test_executive_summary_endpoint(client, seeded_history, monkeypatch):
    def unavailable(_journey):
        raise context_service.ContextServiceError("IA indisponível.")

    monkeypatch.setattr(context_service, "generate_executive_summary", unavailable)
    summary = client.get("/api/cockpit/customers/12345678900/executive-summary").json()
    assert summary["source"] == "REGRAS"
    assert summary["stats"]["contacts"] == 3
    assert summary["headline"]


def test_health_shape_without_exposing_the_key(client, monkeypatch):
    monkeypatch.setattr("routes.api.context_service.health_check", lambda: ("ok", True))
    payload = client.get("/api/health").json()
    assert payload == {
        "backend": "ok",
        "database": "ok",
        "groq": "ok",
        "groq_key_configured": True,
        "transcription_model": "whisper-large-v3-turbo",
        "context_model": "openai/gpt-oss-20b",
        "demo_fallback": False,
        "sms_mode": "SIMULADO",
    }
    assert "api_key" not in payload


def test_reset_recreates_the_demo_history_and_clear_empties_it(client, seeded_history):
    assert client.post("/api/demo/clear").status_code == 200
    assert client.get("/api/sessions").json() == []

    assert client.post("/api/demo/reset").status_code == 200
    sessions = client.get("/api/sessions").json()
    assert len(sessions) == 12
    assert any(session["protocol"] == "123" for session in sessions)

    from database import DEMO_CUSTOMERS

    customers = client.get("/api/cockpit/customers?q=").json()
    assert len(DEMO_CUSTOMERS) >= 12
    assert {customer["name"] for customer in customers} <= {name for _cpf, name in DEMO_CUSTOMERS}
