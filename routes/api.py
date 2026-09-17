"""API interna: Cockpit, visão do gestor, inspeção técnica e ferramentas da demonstração.

Em produção, estas rotas ficariam atrás da autenticação corporativa da Claro.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from config import settings
from database import database_health
from services import cce_service, context_service, insight_service, metrics_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")


def clear_uploads() -> None:
    for path in settings.upload_dir.iterdir():
        if path.is_file() and path.name != ".gitkeep":
            path.unlink()


def handle_domain_error(exc: Exception) -> HTTPException:
    if isinstance(exc, cce_service.NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, cce_service.SessionUnavailableError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (cce_service.CCEError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    logger.exception("Erro inesperado", exc_info=exc)
    return HTTPException(status_code=500, detail="Não foi possível concluir a operação.")


@router.get("/health")
def health():
    groq_state, key_configured = context_service.health_check()
    return {
        "backend": "ok",
        "database": "ok" if database_health() else "error",
        "groq": groq_state,
        "groq_key_configured": key_configured,
        "transcription_model": settings.groq_transcription_model,
        "context_model": settings.groq_context_model,
        "demo_fallback": settings.demo_fallback,
        "sms_mode": "REAL" if settings.sms_provider == "twilio" else "SIMULADO",
    }


# ---------------------------------------------------------------- inspeção (Debug)

@router.get("/sessions")
def sessions(include_closed: bool = True):
    return cce_service.list_sessions(include_closed=include_closed)


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    try:
        return cce_service.session_detail(session_id)
    except Exception as exc:
        raise handle_domain_error(exc) from exc


@router.get("/sessions/{session_id}/events")
def events(session_id: str):
    try:
        return cce_service.get_timeline(session_id)
    except Exception as exc:
        raise handle_domain_error(exc) from exc


# ---------------------------------------------------------------- Cockpit

@router.get("/cockpit/customers")
def cockpit_customers(
    q: str = Query(default="", max_length=80),
    department: str = Query(default="", max_length=40),
    channel: str = Query(default="", max_length=20),
):
    return cce_service.list_customers(q, department, channel)


@router.get("/cockpit/customers/{cpf}")
def cockpit_customer(cpf: str):
    try:
        return cce_service.customer_overview(cpf)
    except Exception as exc:
        raise handle_domain_error(exc) from exc


@router.get("/cockpit/customers/{cpf}/executive-summary")
def cockpit_executive_summary(cpf: str):
    try:
        return insight_service.executive_summary(cpf)
    except Exception as exc:
        raise handle_domain_error(exc) from exc


@router.get("/cockpit/interactions/{interaction_id}/record")
def cockpit_interaction_record(interaction_id: str):
    try:
        return cce_service.interaction_record(interaction_id)
    except Exception as exc:
        raise handle_domain_error(exc) from exc


@router.post("/sessions/{session_id}/handoff")
def handoff(session_id: str):
    try:
        return cce_service.handoff_session(session_id)
    except Exception as exc:
        raise handle_domain_error(exc) from exc


@router.post("/sessions/{session_id}/resolve")
def resolve(session_id: str):
    try:
        return cce_service.resolve_session(session_id)
    except Exception as exc:
        raise handle_domain_error(exc) from exc


@router.get("/cockpit/metrics")
def cockpit_metrics(days: int = Query(default=14, ge=0, le=365)):
    return metrics_service.dashboard(days or None)


# ---------------------------------------------------------------- demonstração

@router.post("/demo/reset")
def reset_demo():
    try:
        cce_service.reset_demo(seed_history=True)
        clear_uploads()
        return {"message": "Demonstração reiniciada com o histórico fictício. Clientes preservados."}
    except Exception as exc:
        logger.exception("Falha ao reiniciar demonstração")
        raise HTTPException(status_code=500, detail="Não foi possível reiniciar a demonstração.") from exc


@router.post("/demo/clear")
def clear_demo_data():
    try:
        cce_service.reset_demo(seed_history=False)
        clear_uploads()
        return {"message": "Dados da demonstração removidos. Clientes fictícios preservados."}
    except Exception as exc:
        logger.exception("Falha ao limpar dados da demonstração")
        raise HTTPException(status_code=500, detail="Não foi possível limpar os dados.") from exc
