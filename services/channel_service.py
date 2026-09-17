"""Casos de uso dos canais do cliente (Telefone/URA, WhatsApp e Minha Claro).

O cliente se identifica com CPF e, opcionalmente, protocolo. Quando existe contexto aberto,
Telefone e WhatsApp exigem um código por SMS antes de revelar qualquer detalhe; no Minha
Claro o login do aplicativo já cumpre esse papel. Os canais recebem somente uma visão
reduzida do protocolo (sem CPF, transcrição ou dados internos).
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import timedelta
from typing import Any

from config import settings
from database import get_connection
from models import (
    CATEGORY_AREAS,
    CATEGORY_LABELS,
    CHANNEL_LABELS,
    DESTINATION_LABELS,
    RESUMABLE_STATUSES,
    STATUS_LABELS,
)
from services import cce_service, context_service, sms_service
from utils import mask_phone, normalize_cpf, now_local, parse_datetime


class AccessError(Exception):
    """Acesso ausente, expirado ou ainda não verificado."""


class VerificationError(Exception):
    pass


# ---------------------------------------------------------------- visão do cliente

def public_case(session: dict[str, Any]) -> dict[str, Any]:
    category = session.get("category")
    department = session.get("destination_department")
    entities = {
        key: value
        for key, value in (session.get("structured_context") or {}).items()
        if value is not None
    }
    return {
        "protocol": session["protocol"],
        "status": session["status"],
        "status_label": STATUS_LABELS.get(session["status"], session["status"]),
        "open": session["status"] in RESUMABLE_STATUSES,
        "category": category,
        "category_label": CATEGORY_LABELS.get(category, "Em análise"),
        "department": department,
        "department_label": DESTINATION_LABELS.get(department, "Em análise"),
        "area": CATEGORY_AREAS.get(category, "help"),
        "problem": session.get("problem"),
        "summary": session.get("summary"),
        "entities": dict(list(entities.items())[:4]),
        "channel_origin": session["channel_origin"],
        "channel_origin_label": CHANNEL_LABELS.get(session["channel_origin"], session["channel_origin"]),
        "current_channel": session["current_channel"],
        "current_channel_label": CHANNEL_LABELS.get(session["current_channel"], session["current_channel"]),
        "agent": session.get("assigned_agent"),
        "created_at": session["created_at"],
        "updated_at": session["updated_at"],
    }


def _last_contact(session_id: str) -> dict[str, Any] | None:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT channel, summary, started_at FROM cce_interactions
               WHERE session_id = ? ORDER BY started_at DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
    if not row:
        return None
    return {
        "channel": row["channel"],
        "channel_label": CHANNEL_LABELS.get(row["channel"], row["channel"]),
        "summary": row["summary"],
        "at": row["started_at"],
    }


def public_case_with_history(session: dict[str, Any]) -> dict[str, Any]:
    result = public_case(session)
    result["last_contact"] = _last_contact(session["id"])
    return result


def public_interaction(interaction: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": interaction["id"],
        "channel": interaction["channel"],
        "type": interaction["interaction_type"],
        "status": interaction["status"],
        "summary": interaction.get("summary"),
    }


# ---------------------------------------------------------------- acesso e verificação

def _hash_code(token: str, code: str) -> str:
    return hashlib.sha256(f"{token}:{code}".encode()).hexdigest()


def _get_access(token: str | None) -> dict[str, Any]:
    if not token:
        raise AccessError("Identifique-se novamente para continuar.")
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM channel_access WHERE token = ?", (token,)).fetchone()
    if not row:
        raise AccessError("Identifique-se novamente para continuar.")
    access = dict(row)
    if parse_datetime(access["expires_at"]) <= now_local():
        raise AccessError("Seu acesso expirou. Identifique-se novamente.")
    return access


def require_access(token: str | None) -> dict[str, Any]:
    access = _get_access(token)
    if not access["verified_at"]:
        raise AccessError("Confirme o código enviado por SMS para continuar.")
    return access


def _set_focus(token: str, session_id: str) -> None:
    with get_connection() as connection:
        connection.execute("UPDATE channel_access SET focus_session_id = ? WHERE token = ?", (session_id, token))


def _send_code(token: str) -> dict[str, Any]:
    access = _get_access(token)
    if access["verification"] != "SMS":
        raise VerificationError("Este acesso não usa verificação por SMS.")
    if access["verified_at"]:
        raise VerificationError("Sua identidade já foi confirmada.")
    if access["sends"] >= settings.sms_max_sends:
        raise VerificationError("Limite de reenvios atingido. Identifique-se novamente mais tarde.")
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = now_local() + timedelta(minutes=settings.sms_code_minutes)
    with get_connection() as connection:
        connection.execute(
            """UPDATE channel_access SET code_hash = ?, code_expires_at = ?, attempts = 0, sends = sends + 1
               WHERE token = ?""",
            (_hash_code(token, code), expires.isoformat(), token),
        )
    customer = cce_service.get_customer(access["cpf"])
    delivery = sms_service.send_verification_code(code)
    return {
        "masked_phone": mask_phone(customer["phone"]) if customer else "celular cadastrado",
        "mode": delivery.mode,
        "demo_code": code if delivery.reveal_code else None,
        "notice": delivery.notice,
        "expires_in_seconds": settings.sms_code_minutes * 60,
    }


def identify(channel: str, cpf: str, protocol: str | None = None) -> dict[str, Any]:
    normalized = normalize_cpf(cpf)
    customer = cce_service.get_customer(normalized)
    if not customer:
        raise cce_service.NotFoundError("Não localizamos um cliente com este CPF.")

    focus = None
    protocol_status = None
    protocol_digits = re.sub(r"\D", "", protocol or "")
    if protocol_digits:
        case = cce_service.find_case_by_protocol(protocol_digits)
        if not case or case["cpf"] != normalized:
            # Não revela se o protocolo existe para outro CPF.
            return {"protocol_status": "NOT_FOUND", "access_token": None}
        if case["status"] in RESUMABLE_STATUSES:
            protocol_status, focus = "OPEN", case
        else:
            protocol_status = "CLOSED"

    open_cases = cce_service.find_open_cases(normalized)
    if focus is None and open_cases:
        focus = open_cases[0]
    if channel == "MINHA_CLARO":
        verification = "LOGIN"
    elif open_cases:
        verification = "SMS"
    else:
        verification = "NENHUMA"

    token = secrets.token_urlsafe(32)
    timestamp = now_local()
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO channel_access (
                token, cpf, channel, focus_session_id, verification, verified_at, created_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                token, normalized, channel, focus["id"] if focus else None, verification,
                None if verification == "SMS" else timestamp.isoformat(),
                timestamp.isoformat(),
                (timestamp + timedelta(minutes=settings.channel_access_minutes)).isoformat(),
            ),
        )
    result: dict[str, Any] = {
        "access_token": token,
        "protocol_status": protocol_status,
        "closed_protocol": protocol_digits if protocol_status == "CLOSED" else None,
        "has_open_case": bool(open_cases),
        "verification": verification,
        "verified": verification != "SMS",
        "customer": {"first_name": customer["name"].split()[0]},
    }
    if verification == "SMS":
        result["sms"] = _send_code(token)
    return result


def resend_code(token: str | None) -> dict[str, Any]:
    return _send_code(_get_access(token)["token"])


def verify_code(token: str | None, code: str) -> dict[str, Any]:
    access = _get_access(token)
    if access["verified_at"]:
        return {"verified": True}
    if access["verification"] != "SMS" or not access["code_hash"]:
        raise VerificationError("Nenhum código foi enviado para este acesso.")
    if access["attempts"] >= settings.sms_max_attempts:
        raise VerificationError("Muitas tentativas incorretas. Solicite um novo código.")
    if parse_datetime(access["code_expires_at"]) <= now_local():
        raise VerificationError("O código expirou. Solicite um novo código.")
    digits = re.sub(r"\D", "", code or "")
    if not hmac.compare_digest(_hash_code(access["token"], digits), access["code_hash"]):
        remaining = settings.sms_max_attempts - access["attempts"] - 1
        with get_connection() as connection:
            connection.execute("UPDATE channel_access SET attempts = attempts + 1 WHERE token = ?", (access["token"],))
        if remaining <= 0:
            raise VerificationError("Muitas tentativas incorretas. Solicite um novo código.")
        raise VerificationError(f"Código incorreto. Você ainda tem {remaining} tentativa(s).")
    with get_connection() as connection:
        connection.execute(
            "UPDATE channel_access SET verified_at = ?, code_hash = NULL WHERE token = ?",
            (now_local().isoformat(), access["token"]),
        )
        if access["focus_session_id"]:
            cce_service.create_event(
                access["focus_session_id"], access["channel"], "CUSTOMER_VERIFIED",
                "Identidade confirmada por código SMS", connection,
            )
    return {"verified": True}


# ---------------------------------------------------------------- consultas do cliente

def _owned_case(access: dict[str, Any], protocol: str) -> dict[str, Any]:
    case = cce_service.find_case_by_protocol(protocol)
    if not case or case["cpf"] != access["cpf"]:
        raise cce_service.NotFoundError("Protocolo não encontrado para este cliente.")
    return case


def _owned_interaction(access: dict[str, Any], interaction_id: str) -> dict[str, Any]:
    interaction = cce_service.get_interaction(interaction_id)
    if interaction["cpf"] != access["cpf"] or interaction["channel"] != access["channel"]:
        raise cce_service.NotFoundError("Contato não encontrado.")
    return interaction


def list_cases(token: str | None) -> dict[str, Any]:
    access = require_access(token)
    customer = cce_service.get_customer(access["cpf"])
    open_cases = cce_service.find_open_cases(access["cpf"])
    focus_id = access["focus_session_id"]
    focus = next((case for case in open_cases if case["id"] == focus_id), open_cases[0] if open_cases else None)
    return {
        "customer": {"name": customer["name"], "first_name": customer["name"].split()[0]},
        "channel": access["channel"],
        "cases": [public_case_with_history(case) for case in open_cases],
        "focus_protocol": focus["protocol"] if focus else None,
    }


def resume(token: str | None, protocol: str) -> dict[str, Any]:
    access = require_access(token)
    case = _owned_case(access, protocol)
    session, interaction = cce_service.resume_case(
        case["id"],
        access["channel"],
        verification=access["verification"],
        route_human=access["channel"] in {"TELEFONE", "WHATSAPP"},
    )
    _set_focus(access["token"], session["id"])
    return {"case": public_case_with_history(session), "interaction": public_interaction(interaction)}


def open_phone_case(token: str | None, department: str) -> dict[str, Any]:
    access = require_access(token)
    if access["channel"] != "TELEFONE":
        raise cce_service.CCEError("Este canal não abre atendimentos por voz.")
    session, interaction = cce_service.create_case(
        access["cpf"], "TELEFONE",
        department=department,
        input_kind="AUDIO",
        verification=access["verification"],
        status="EM_ATENDIMENTO",
    )
    _set_focus(access["token"], session["id"])
    return {"case": public_case(session), "interaction": public_interaction(interaction)}


def open_message_case(token: str | None, message: str, area_category: str | None = None) -> dict[str, Any]:
    """Abre um protocolo por texto (WhatsApp ou Minha Claro) e classifica com a IA de contexto."""
    access = require_access(token)
    channel = access["channel"]
    if channel not in {"WHATSAPP", "MINHA_CLARO"}:
        raise cce_service.CCEError("Este canal não abre atendimentos por mensagem.")
    hint = (area_category or "").upper()
    session, interaction = cce_service.create_case(
        access["cpf"], channel,
        department=hint if hint in CATEGORY_LABELS else None,
        input_kind="CONVERSA" if channel == "WHATSAPP" else "FORMULARIO",
        verification=access["verification"],
        status="PROCESSANDO",
    )
    try:
        stored = cce_service.add_message(interaction["id"], "CLIENTE", message)
        cce_service.mark_context_processing(interaction["id"])
        case = context_service.analyze_context(
            stored["text"], channel=channel, department_hint=hint or None
        )
        finish = channel == "MINHA_CLARO"
        session, interaction = cce_service.apply_context(
            interaction["id"], case,
            finish=finish,
            live_status="EM_ATENDIMENTO_HUMANO",
        )
        if channel == "WHATSAPP":
            reply = (
                f"Entendi: {session['problem'].rstrip('.')}. Direcionei seu atendimento para "
                f"{DESTINATION_LABELS.get(session['destination_department'], 'o time responsável')}."
            )
            cce_service.add_message(interaction["id"], "CLARO", reply)
    except Exception:
        cce_service.delete_interaction(interaction["id"])
        raise
    _set_focus(access["token"], session["id"])
    return {"case": public_case_with_history(session), "interaction": public_interaction(interaction)}


def _scripted_reply(interaction: dict[str, Any], session: dict[str, Any], first_name: str) -> str:
    previous = [m for m in cce_service.get_messages(interaction["id"]) if m["author"] == "CLIENTE"]
    department = DESTINATION_LABELS.get(session.get("destination_department"), "responsável")
    if len(previous) <= 1 and interaction["interaction_type"] == "RETOMADA":
        return (
            f"Anotado, {first_name}. O time de {department} já está com o histórico do protocolo "
            f"{session['protocol']}, não é preciso repetir o que você já contou."
        )
    return "Recebido. Sua mensagem foi adicionada ao contexto do atendimento."


def add_message(token: str | None, interaction_id: str, text: str) -> dict[str, Any]:
    access = require_access(token)
    interaction = _owned_interaction(access, interaction_id)
    message = cce_service.add_message(interaction_id, "CLIENTE", text)
    session = cce_service.get_session(interaction["session_id"])
    reply = None
    if access["channel"] == "WHATSAPP":
        customer = cce_service.get_customer(access["cpf"])
        reply = cce_service.add_message(
            interaction_id, "CLARO", _scripted_reply(interaction, session, customer["name"].split()[0])
        )
    return {"message": message, "reply": reply}


def _previous_context(session: dict[str, Any]) -> dict[str, Any] | None:
    if not session.get("problem"):
        return None
    return {key: session.get(key) for key in ("category", "problem", "summary", "intent")}


def finish(token: str | None, interaction_id: str, outcome: str = "EM_ABERTO") -> dict[str, Any]:
    """Encerra um contato: a IA consolida o que foi dito e atualiza a CCE."""
    access = require_access(token)
    interaction = _owned_interaction(access, interaction_id)
    session = cce_service.get_session(interaction["session_id"])
    if interaction["status"] == "CONCLUIDA":
        raise cce_service.SessionUnavailableError("Este contato já foi encerrado.")

    if interaction["input_kind"] == "AUDIO":
        text = interaction.get("transcript") or ""
        if not text:
            raise cce_service.CCEError("Transcreva a gravação antes de interpretar o contexto.")
    else:
        text = cce_service.customer_text(interaction_id)

    if not text.strip():
        summary = "Retomou o contexto e encerrou o contato sem novas informações."
        session, interaction = cce_service.finish_without_context(interaction_id, summary, outcome)
    else:
        cce_service.mark_context_processing(interaction_id)
        case = context_service.analyze_context(
            text,
            channel=access["channel"],
            department_hint=session.get("initial_department"),
            previous=_previous_context(session),
            resumed=interaction["interaction_type"] == "RETOMADA",
        )
        session, interaction = cce_service.apply_context(interaction_id, case, finish=True, outcome=outcome)
    return {"case": public_case_with_history(session), "interaction": public_interaction(interaction)}


def owned_interaction(token: str | None, interaction_id: str) -> dict[str, Any]:
    return _owned_interaction(require_access(token), interaction_id)
