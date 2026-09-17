from __future__ import annotations

import pytest

from schemas import ExecutiveSummary
from services import cce_service, context_service, insight_service, metrics_service, telemetry


def test_dashboard_measures_continuity_over_the_seeded_history(seeded_history):
    data = metrics_service.dashboard(30)
    kpis = data["kpis"]
    assert kpis["contacts"] == 20
    assert kpis["resumptions"] == 8
    assert kpis["openings"] == 12
    assert kpis["context_reuse_rate"] == pytest.approx(0.4)
    assert kpis["channel_handoffs"] == 8
    assert kpis["duplicate_openings"] == 1
    assert kpis["continuity_rate"] == pytest.approx(8 / 9, rel=1e-3)
    assert kpis["triage_avoided"] == kpis["resumptions"]
    assert kpis["cross_channel_cases"] == 5
    assert data["provenance"]["demo_contacts"] == 20


def test_dashboard_period_filter_and_flows(seeded_history):
    recent = metrics_service.dashboard(1)
    assert recent["kpis"]["contacts"] < metrics_service.dashboard(30)["kpis"]["contacts"]
    flows = metrics_service.dashboard(30)["handoff_flows"]
    assert {(flow["from"], flow["to"]) for flow in flows} >= {("TELEFONE", "WHATSAPP"), ("MINHA_CLARO", "WHATSAPP")}
    assert all(flow["count"] > 0 for flow in flows)


def test_departments_and_channels_cover_the_whole_taxonomy(seeded_history):
    data = metrics_service.dashboard(30)
    assert len(data["departments"]) == 8
    assert {item["channel"] for item in data["channels"]} == {"TELEFONE", "WHATSAPP", "MINHA_CLARO"}
    internet = next(item for item in data["departments"] if item["department"] == "SUPORTE_TECNICO")
    assert internet["cases"] >= 1 and internet["open"] >= 1


def test_ai_health_reflects_real_runs_only(seeded_history):
    empty = metrics_service.dashboard(30)["ai_health"]
    assert all(stage["runs"] == 0 and stage["success_rate"] is None for stage in empty)
    telemetry.record_ai_run("CONTEXTO", "WHATSAPP", True, 820, redactions=2)
    telemetry.record_ai_run("CONTEXTO", "WHATSAPP", False, 400)
    data = metrics_service.dashboard(30)
    context_stage = next(stage for stage in data["ai_health"] if stage["stage"] == "CONTEXTO")
    assert context_stage["runs"] == 2
    assert context_stage["success_rate"] == pytest.approx(0.5)
    assert context_stage["avg_latency_ms"] == 820
    assert data["kpis"]["redactions"] == 2


def test_executive_summary_uses_the_ai_and_caches_by_journey(monkeypatch, seeded_history):
    calls = []

    def fake_summary(journey: str) -> ExecutiveSummary:
        calls.append(journey)
        return ExecutiveSummary(
            headline="Protocolo de internet em aberto",
            narrative="Cliente tratou de internet por telefone e WhatsApp sem repetir a triagem.",
            attention_points=["Aguarda visita técnica"],
            next_best_action="Agendar visita",
        )

    monkeypatch.setattr(context_service, "generate_executive_summary", fake_summary)
    first = insight_service.executive_summary("12345678900")
    assert first["source"] == "IA"
    assert first["stats"]["contacts"] == 3
    assert first["stats"]["context_reuses"] == 1
    assert first["stats"]["cases_open"] == 1
    assert "123.456.789-00" not in calls[0] and "Lucas" in calls[0]

    cached = insight_service.executive_summary("12345678900")
    assert cached["headline"] == first["headline"]
    assert len(calls) == 1

    case = cce_service.find_case_by_protocol("123")
    cce_service.resume_case(case["id"], "MINHA_CLARO", verification="LOGIN", route_human=False)
    insight_service.executive_summary("12345678900")
    assert len(calls) == 2  # a jornada mudou, o resumo é refeito


def test_executive_summary_falls_back_to_rules_when_the_ai_fails(monkeypatch, seeded_history):
    def unavailable(_journey):
        raise context_service.ContextServiceError("IA indisponível.")

    monkeypatch.setattr(context_service, "generate_executive_summary", unavailable)
    summary = insight_service.executive_summary("11122233344")
    assert summary["source"] == "REGRAS"
    assert "contato" in summary["narrative"]
    assert summary["stats"]["channels_used"] == 3


def test_customer_without_history_has_an_empty_summary():
    summary = insight_service.executive_summary("98765432100")
    assert summary["stats"]["contacts"] == 0
    assert summary["source"] == "REGRAS"
    assert "ainda não possui" in summary["narrative"]
