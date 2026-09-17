"""Cápsula de Contexto Efêmera (CCE).

- Protocolo (tabela cce_sessions): um atendimento sobre um tema, com o contexto consolidado.
- Contato (tabela cce_interactions): cada passagem do cliente por um canal dentro de um protocolo.
- Eventos (tabela cce_events): trilha técnica usada na inspeção (Debug).
"""
from __future__ import annotations

import json
import re
import secrets
import sqlite3
import unicodedata
import uuid
from datetime import timedelta
from typing import Any

import privacy
from config import settings
from database import clear_data, get_connection, seed_customers
from models import (
    CATEGORY_DESTINATIONS,
    CATEGORY_LABELS,
    CHANNEL_LABELS,
    CLOSED_STATUSES,
    CUSTOMER_CHANNELS,
    DESTINATION_LABELS,
    RESUMABLE_STATUSES,
)
from schemas import ContextCase
from utils import mask_cpf, normalize_cpf, now_local, parse_datetime


class CCEError(Exception):
    pass


class NotFoundError(CCEError):
    pass


class SessionUnavailableError(CCEError):
    pass


def _load_json(value: str | None) -> dict[str, Any]:
    try:
        loaded = json.loads(value or "{}")
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    result = dict(row)
    if "structured_context" in result:
        result["structured_context"] = _load_json(result["structured_context"])
    return result


def _generate_protocol(connection: sqlite3.Connection) -> str:
    while True:
        candidate = str(100000 + secrets.randbelow(900000))
        exists = connection.execute(
            "SELECT 1 FROM cce_sessions WHERE protocol = ?", (candidate,)
        ).fetchone()
        if not exists:
            return candidate


def _renewed_expiration() -> str:
    return (now_local() + timedelta(hours=settings.cce_ttl_hours)).isoformat()


def create_event(
    session_id: str,
    channel: str,
    event_type: str,
    description: str,
    connection: sqlite3.Connection | None = None,
) -> None:
    if connection is None:
        with get_connection() as owned_connection:
            create_event(session_id, channel, event_type, description, owned_connection)
        return
    connection.execute(
        """INSERT INTO cce_events
           (session_id, channel, event_type, description, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, channel, event_type, description, now_local().isoformat()),
    )


# ---------------------------------------------------------------- clientes

def get_customer(cpf: str) -> dict[str, str] | None:
    normalized = normalize_cpf(cpf)
    with get_connection() as connection:
        row = connection.execute(
            "SELECT cpf, name, phone FROM customers WHERE cpf = ?", (normalized,)
        ).fetchone()
    return dict(row) if row else None


# ---------------------------------------------------------------- protocolos

def create_case(
    cpf: str,
    channel: str,
    *,
    department: str | None,
    input_kind: str,
    verification: str,
    status: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Abre um protocolo e registra o primeiro contato do cliente no canal."""
    normalized = normalize_cpf(cpf)
    channel = channel.upper()
    if channel not in CUSTOMER_CHANNELS:
        raise CCEError("Canal inválido.")
    department = (department or "NAO_INFORMADO").strip().upper()
    if department != "NAO_INFORMADO" and department not in CATEGORY_LABELS:
        raise CCEError("Selecione uma opção válida.")
    customer = get_customer(normalized)
    if not customer:
        raise NotFoundError("Cliente fictício não encontrado.")

    session_id = str(uuid.uuid4())
    interaction_id = str(uuid.uuid4())
    timestamp = now_local().isoformat()
    with get_connection() as connection:
        protocol = _generate_protocol(connection)
        connection.execute(
            """INSERT INTO cce_sessions (
                id, protocol, cpf, customer_name, status, channel_origin, current_channel,
                initial_department, structured_context, created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, '{}', ?, ?, ?)""",
            (
                session_id, protocol, normalized, customer["name"], status, channel, channel,
                department, timestamp, timestamp, _renewed_expiration(),
            ),
        )
        connection.execute(
            """INSERT INTO cce_interactions (
                id, session_id, cpf, channel, interaction_type, status, verification,
                input_kind, category, destination_department, started_at
            ) VALUES (?, ?, ?, ?, 'ABERTURA', 'EM_ANDAMENTO', ?, ?, ?, ?, ?)""",
            (
                interaction_id, session_id, normalized, channel, verification, input_kind,
                department if department in CATEGORY_LABELS else None,
                CATEGORY_DESTINATIONS.get(department),
                timestamp,
            ),
        )
        create_event(session_id, channel, "CUSTOMER_AUTHENTICATED", "Cliente identificado no canal", connection)
        if channel == "TELEFONE" and department in CATEGORY_LABELS:
            create_event(
                session_id, "URA", "DEPARTMENT_SELECTED", f"{CATEGORY_LABELS[department]} selecionado", connection
            )
        create_event(session_id, channel, "SESSION_CREATED", f"Protocolo {protocol} aberto", connection)
    return get_session(session_id), get_interaction(interaction_id)


def get_session(session_id: str, check_expiration: bool = True) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM cce_sessions WHERE id = ?", (session_id,)).fetchone()
    session = _row_to_dict(row)
    if not session:
        raise NotFoundError("Protocolo não encontrado.")
    if check_expiration:
        session = expire_if_needed(session)
    return session


def expire_if_needed(session: dict[str, Any]) -> dict[str, Any]:
    if session["status"] in CLOSED_STATUSES:
        return session
    if parse_datetime(session["expires_at"]) <= now_local():
        with get_connection() as connection:
            connection.execute(
                "UPDATE cce_sessions SET status = 'EXPIRADA', updated_at = ? WHERE id = ?",
                (now_local().isoformat(), session["id"]),
            )
            create_event(session["id"], "SISTEMA", "SESSION_EXPIRED", "CCE expirada", connection)
        session["status"] = "EXPIRADA"
    return session


def find_case_by_protocol(protocol: str) -> dict[str, Any] | None:
    digits = re.sub(r"\D", "", protocol or "")
    if not digits:
        return None
    with get_connection() as connection:
        row = connection.execute("SELECT * FROM cce_sessions WHERE protocol = ?", (digits,)).fetchone()
    session = _row_to_dict(row)
    return expire_if_needed(session) if session else None


def find_open_cases(cpf: str) -> list[dict[str, Any]]:
    """Protocolos com contexto disponível para retomada, do mais recente para o mais antigo."""
    normalized = normalize_cpf(cpf)
    placeholders = ", ".join("?" for _ in RESUMABLE_STATUSES)
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT * FROM cce_sessions
                WHERE cpf = ? AND status IN ({placeholders})
                ORDER BY updated_at DESC""",
            (normalized, *sorted(RESUMABLE_STATUSES)),
        ).fetchall()
    sessions = [expire_if_needed(_row_to_dict(row)) for row in rows]
    return [session for session in sessions if session["status"] in RESUMABLE_STATUSES]


def list_sessions(include_closed: bool = True) -> list[dict[str, Any]]:
    query = "SELECT * FROM cce_sessions"
    if not include_closed:
        query += " WHERE status NOT IN ('RESOLVIDA', 'EXPIRADA')"
    query += " ORDER BY updated_at DESC"
    with get_connection() as connection:
        rows = connection.execute(query).fetchall()
    sessions = [expire_if_needed(_row_to_dict(row)) for row in rows]
    if include_closed:
        return sessions
    return [session for session in sessions if session["status"] not in CLOSED_STATUSES]


def _update(table: str, allowed: set[str], record_id: str, fields: dict[str, Any]) -> None:
    values = {key: value for key, value in fields.items() if key in allowed}
    if not values:
        return
    if "structured_context" in values:
        values["structured_context"] = json.dumps(values["structured_context"], ensure_ascii=False)
    assignments = ", ".join(f"{key} = ?" for key in values)
    with get_connection() as connection:
        cursor = connection.execute(
            f"UPDATE {table} SET {assignments} WHERE id = ?", (*values.values(), record_id)
        )
        if cursor.rowcount == 0:
            raise NotFoundError("Registro não encontrado.")


SESSION_FIELDS = {
    "status", "current_channel", "transcript", "intent", "category", "problem", "summary",
    "structured_context", "destination_department", "suggested_action", "priority",
    "assigned_agent", "expires_at", "resolved_at", "updated_at",
}


def update_session(session_id: str, **fields: Any) -> dict[str, Any]:
    fields.setdefault("updated_at", now_local().isoformat())
    _update("cce_sessions", SESSION_FIELDS, session_id, fields)
    return get_session(session_id, check_expiration=False)


# ---------------------------------------------------------------- contatos

INTERACTION_FIELDS = {
    "status", "agent", "audio_path", "transcript", "intent", "problem", "summary", "category",
    "destination_department", "structured_context", "outcome", "ended_at",
}


def get_interaction(interaction_id: str) -> dict[str, Any]:
    with get_connection() as connection:
        row = connection.execute(
            """SELECT i.*, s.protocol FROM cce_interactions i
               JOIN cce_sessions s ON s.id = i.session_id WHERE i.id = ?""",
            (interaction_id,),
        ).fetchone()
    interaction = _row_to_dict(row)
    if not interaction:
        raise NotFoundError("Contato não encontrado.")
    return interaction


def update_interaction(interaction_id: str, **fields: Any) -> dict[str, Any]:
    _update("cce_interactions", INTERACTION_FIELDS, interaction_id, fields)
    return get_interaction(interaction_id)


def _open_interaction_or_fail(interaction_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    interaction = get_interaction(interaction_id)
    session = get_session(interaction["session_id"])
    if interaction["status"] == "CONCLUIDA":
        raise SessionUnavailableError("Este contato já foi encerrado.")
    if session["status"] in CLOSED_STATUSES:
        raise SessionUnavailableError("Este protocolo não está mais disponível.")
    return interaction, session


def resume_case(
    session_id: str,
    channel: str,
    *,
    verification: str,
    route_human: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Registra a retomada de um protocolo em um canal, sem nova triagem."""
    channel = channel.upper()
    if channel not in CUSTOMER_CHANNELS:
        raise CCEError("Canal de retomada inválido.")
    session = get_session(session_id)
    if session["status"] not in RESUMABLE_STATUSES:
        raise SessionUnavailableError("Este protocolo não está disponível para retomada.")

    interaction_id = str(uuid.uuid4())
    timestamp = now_local().isoformat()
    previous_channel = session["current_channel"]
    placeholder = f"Retomou o protocolo {session['protocol']} sem repetir a triagem."
    with get_connection() as connection:
        connection.execute(
            """INSERT INTO cce_interactions (
                id, session_id, cpf, channel, interaction_type, status, verification, input_kind,
                agent, intent, problem, summary, category, destination_department, started_at
            ) VALUES (?, ?, ?, ?, 'RETOMADA', 'EM_ANDAMENTO', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                interaction_id, session_id, session["cpf"], channel, verification,
                "AUDIO" if channel == "TELEFONE" else "CONVERSA" if channel == "WHATSAPP" else "FORMULARIO",
                session.get("assigned_agent"), session.get("intent"), session.get("problem"), placeholder,
                session.get("category"), session.get("destination_department"), timestamp,
            ),
        )
        connection.execute(
            """UPDATE cce_sessions SET status = ?, current_channel = ?, expires_at = ?, updated_at = ?
               WHERE id = ?""",
            (
                "EM_ATENDIMENTO_HUMANO" if route_human else "RETOMADA",
                channel, _renewed_expiration(), timestamp, session_id,
            ),
        )
        create_event(session_id, channel, "SESSION_RESUMED", f"Contexto retomado em {CHANNEL_LABELS[channel]}", connection)
        if previous_channel != channel:
            create_event(
                session_id, channel, "CHANNEL_CHANGED",
                f"Transbordo de {CHANNEL_LABELS.get(previous_channel, previous_channel)} para {CHANNEL_LABELS[channel]}",
                connection,
            )
        if route_human:
            create_event(session_id, channel, "HUMAN_HANDOFF", "Encaminhado a especialista com o contexto", connection)
    return get_session(session_id, check_expiration=False), get_interaction(interaction_id)


def add_message(interaction_id: str, author: str, text: str) -> dict[str, Any]:
    interaction, _session = _open_interaction_or_fail(interaction_id)
    if interaction["input_kind"] == "AUDIO":
        raise CCEError("Este contato é por voz.")
    cleaned, _count = privacy.redact(text.strip()[:2000])
    created_at = now_local().isoformat()
    with get_connection() as connection:
        cursor = connection.execute(
            "INSERT INTO cce_messages (interaction_id, author, text, created_at) VALUES (?, ?, ?, ?)",
            (interaction_id, author, cleaned, created_at),
        )
    return {"id": cursor.lastrowid, "author": author, "text": cleaned, "created_at": created_at}


def get_messages(interaction_id: str) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT author, text, created_at FROM cce_messages WHERE interaction_id = ? ORDER BY id",
            (interaction_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def customer_text(interaction_id: str) -> str:
    return "\n".join(
        message["text"] for message in get_messages(interaction_id) if message["author"] == "CLIENTE"
    )


def register_audio(interaction_id: str, audio_path: str) -> tuple[dict[str, Any], str | None]:
    interaction, session = _open_interaction_or_fail(interaction_id)
    if interaction["input_kind"] != "AUDIO":
        raise CCEError("Este contato não recebe áudio.")
    if interaction.get("transcript"):
        raise SessionUnavailableError("A gravação deste contato já foi processada.")
    previous = interaction.get("audio_path")
    updated = update_interaction(interaction_id, audio_path=audio_path)
    create_event(session["id"], "TELEFONE", "AUDIO_RECEIVED", "Gravação da ligação recebida")
    return updated, previous


def _event_once(session_id: str, channel: str, event_type: str, description: str) -> None:
    with get_connection() as connection:
        already = connection.execute(
            "SELECT 1 FROM cce_events WHERE session_id = ? AND event_type = ? AND description = ?",
            (session_id, event_type, description),
        ).fetchone()
        if not already:
            create_event(session_id, channel, event_type, description, connection)


def start_call(interaction_id: str) -> dict[str, Any]:
    interaction, session = _open_interaction_or_fail(interaction_id)
    if interaction["input_kind"] != "AUDIO" or interaction.get("audio_path"):
        raise SessionUnavailableError("Esta ligação não pode ser iniciada novamente.")
    _event_once(session["id"], "TELEFONE", "CALL_STARTED", f"Ligação iniciada · contato {interaction_id[:8]}")
    return interaction


def start_transcription(interaction_id: str) -> dict[str, Any]:
    interaction, session = _open_interaction_or_fail(interaction_id)
    if not interaction.get("audio_path"):
        raise CCEError("Adicione uma gravação para processar o atendimento.")
    if interaction.get("transcript"):
        raise SessionUnavailableError("Esta gravação já foi transcrita e não será processada novamente.")
    if interaction["interaction_type"] == "ABERTURA":
        update_session(session["id"], status="PROCESSANDO")
    _event_once(session["id"], "TELEFONE", "CALL_FINISHED", f"Ligação encerrada · contato {interaction_id[:8]}")
    create_event(session["id"], "IA_TRANSCRICAO", "TRANSCRIPTION_STARTED", "Transcrição iniciada")
    return interaction


def store_transcript(interaction_id: str, transcript: str) -> tuple[dict[str, Any], str | None]:
    """Guarda a transcrição mascarada e libera a gravação para exclusão."""
    interaction = get_interaction(interaction_id)
    cleaned, _count = privacy.redact(transcript)
    audio_path = interaction.get("audio_path")
    updated = update_interaction(interaction_id, transcript=cleaned, audio_path=None)
    session = get_session(interaction["session_id"], check_expiration=False)
    if interaction["interaction_type"] == "ABERTURA" and not session.get("transcript"):
        update_session(session["id"], transcript=cleaned)
    create_event(session["id"], "IA_TRANSCRICAO", "TRANSCRIPTION_COMPLETED", "Transcrição concluída")
    return updated, audio_path


def mark_context_processing(interaction_id: str) -> None:
    interaction = get_interaction(interaction_id)
    create_event(
        interaction["session_id"], "IA_CONTEXTO", "CONTEXT_PROCESSING_STARTED", "Interpretação do contexto iniciada"
    )


def apply_context(
    interaction_id: str,
    case: ContextCase,
    *,
    finish: bool,
    outcome: str = "EM_ABERTO",
    live_status: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Atualiza o protocolo e o contato com o case gerado pela IA."""
    interaction = get_interaction(interaction_id)
    session = get_session(interaction["session_id"], check_expiration=False)
    timestamp = now_local().isoformat()
    entities = dict(case.structured_context)
    merged_entities, _ = privacy.sanitize_entities({**session["structured_context"], **entities})

    if finish and outcome == "RESOLVIDO":
        status = "RESOLVIDA"
    elif finish:
        status = "SUSPENSA"
    else:
        status = live_status or session["status"]

    session_fields: dict[str, Any] = {
        "status": status,
        "current_channel": interaction["channel"],
        # Campos opcionais preservam o valor anterior quando a IA não os identifica de novo.
        "intent": case.intent or session.get("intent"),
        "category": case.category,
        "problem": case.problem,
        "summary": case.summary,
        "structured_context": merged_entities,
        "destination_department": case.destination_department,
        "suggested_action": case.suggested_action or session.get("suggested_action"),
        "priority": case.priority,
        "expires_at": _renewed_expiration(),
        "updated_at": timestamp,
    }
    if status == "RESOLVIDA":
        session_fields["resolved_at"] = timestamp
    interaction_fields: dict[str, Any] = {
        "intent": case.intent or interaction.get("intent"),
        "problem": case.problem,
        "summary": case.interaction_summary or case.summary,
        "category": case.category,
        "destination_department": case.destination_department,
        "structured_context": entities,
        "status": "CONCLUIDA" if finish else "EM_ANDAMENTO",
    }
    if finish:
        interaction_fields.update(ended_at=timestamp, outcome=outcome)
    update_session(session["id"], **session_fields)
    update_interaction(interaction_id, **interaction_fields)
    create_event(session["id"], "IA_CONTEXTO", "CONTEXT_IDENTIFIED", "Contexto estruturado identificado")
    if status == "RESOLVIDA":
        _close_open_interactions(session["id"], "RESOLVIDO")
        create_event(session["id"], interaction["channel"], "SESSION_RESOLVED", "Atendimento resolvido")
    elif finish:
        create_event(session["id"], "SISTEMA", "SESSION_SUSPENDED", "CCE mantida ativa para continuidade")
    return get_session(session["id"], check_expiration=False), get_interaction(interaction_id)


def finish_without_context(interaction_id: str, summary: str, outcome: str) -> tuple[dict[str, Any], dict[str, Any]]:
    interaction, session = _open_interaction_or_fail(interaction_id)
    timestamp = now_local().isoformat()
    update_interaction(interaction_id, status="CONCLUIDA", summary=summary, outcome=outcome, ended_at=timestamp)
    if outcome == "RESOLVIDO":
        update_session(session["id"], status="RESOLVIDA", resolved_at=timestamp)
        _close_open_interactions(session["id"], "RESOLVIDO")
        create_event(session["id"], interaction["channel"], "SESSION_RESOLVED", "Atendimento resolvido")
    else:
        update_session(session["id"], status="SUSPENSA", expires_at=_renewed_expiration())
        create_event(session["id"], "SISTEMA", "SESSION_SUSPENDED", "CCE mantida ativa para continuidade")
    return get_session(session["id"], check_expiration=False), get_interaction(interaction_id)


def _close_open_interactions(session_id: str, outcome: str) -> None:
    with get_connection() as connection:
        connection.execute(
            """UPDATE cce_interactions SET status = 'CONCLUIDA', outcome = ?, ended_at = ?
               WHERE session_id = ? AND status != 'CONCLUIDA'""",
            (outcome, now_local().isoformat(), session_id),
        )


def delete_interaction(interaction_id: str) -> list[str]:
    """Cancela um contato. Um protocolo aberto só por ele é removido junto. Retorna áudios a apagar."""
    interaction = get_interaction(interaction_id)
    with get_connection() as connection:
        others = connection.execute(
            "SELECT COUNT(*) FROM cce_interactions WHERE session_id = ? AND id != ?",
            (interaction["session_id"], interaction_id),
        ).fetchone()[0]
        if interaction["interaction_type"] == "ABERTURA" and others == 0:
            connection.execute("DELETE FROM cce_sessions WHERE id = ?", (interaction["session_id"],))
        else:
            connection.execute("DELETE FROM cce_interactions WHERE id = ?", (interaction_id,))
            create_event(interaction["session_id"], interaction["channel"], "INTERACTION_CANCELLED", "Contato cancelado", connection)
    return [interaction["audio_path"]] if interaction.get("audio_path") else []


# ---------------------------------------------------------------- ações do Cockpit

def handoff_session(session_id: str, agent: str | None = None) -> dict[str, Any]:
    agent = agent or settings.cockpit_agent_name
    session = get_session(session_id)
    if session["status"] in CLOSED_STATUSES:
        raise SessionUnavailableError("Este protocolo não está disponível.")
    if session["status"] == "EM_ATENDIMENTO_HUMANO" and session.get("assigned_agent") == agent:
        return session
    with get_connection() as connection:
        connection.execute(
            "UPDATE cce_sessions SET status = 'EM_ATENDIMENTO_HUMANO', assigned_agent = ?, updated_at = ? WHERE id = ?",
            (agent, now_local().isoformat(), session_id),
        )
        latest = connection.execute(
            "SELECT id FROM cce_interactions WHERE session_id = ? ORDER BY started_at DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if latest:
            connection.execute("UPDATE cce_interactions SET agent = ? WHERE id = ?", (agent, latest["id"]))
        create_event(session_id, "COCKPIT", "HUMAN_HANDOFF", f"Atendimento assumido por {agent}", connection)
    return get_session(session_id, check_expiration=False)


def resolve_session(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    if session["status"] == "EXPIRADA":
        raise SessionUnavailableError("Um protocolo expirado não pode ser resolvido.")
    if session["status"] != "RESOLVIDA":
        timestamp = now_local().isoformat()
        update_session(session_id, status="RESOLVIDA", resolved_at=timestamp)
        _close_open_interactions(session_id, "RESOLVIDO")
        create_event(session_id, "COCKPIT", "SESSION_RESOLVED", "Atendimento marcado como resolvido")
    return get_session(session_id, check_expiration=False)


# ---------------------------------------------------------------- consultas internas

def get_timeline(session_id: str) -> list[dict[str, Any]]:
    get_session(session_id, check_expiration=False)
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM cce_events WHERE session_id = ? ORDER BY created_at ASC, id ASC",
            (session_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _interaction_rows(where: str, params: tuple) -> list[dict[str, Any]]:
    with get_connection() as connection:
        rows = connection.execute(
            f"""SELECT i.*, s.protocol, s.status AS case_status,
                       (SELECT COUNT(*) FROM cce_messages m WHERE m.interaction_id = i.id) AS message_count
                FROM cce_interactions i JOIN cce_sessions s ON s.id = i.session_id
                WHERE {where} ORDER BY i.started_at ASC""",
            params,
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


def session_detail(session_id: str) -> dict[str, Any]:
    session = get_session(session_id)
    session["events"] = get_timeline(session_id)
    session["interactions"] = _interaction_rows("i.session_id = ?", (session_id,))
    for interaction in session["interactions"]:
        interaction["messages"] = get_messages(interaction["id"])
        interaction["audio_available"] = bool(interaction.pop("audio_path", None))
    return session


def interaction_record(interaction_id: str) -> dict[str, Any]:
    interaction = get_interaction(interaction_id)
    return {
        "id": interaction["id"],
        "protocol": interaction["protocol"],
        "channel": interaction["channel"],
        "input_kind": interaction["input_kind"],
        "transcript": interaction.get("transcript"),
        "messages": get_messages(interaction_id),
        "source": interaction["source"],
    }


def _normalize_search(value: str) -> str:
    return unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower().strip()


def _customer_matches(query: str, customer: dict[str, Any]) -> bool:
    if not query:
        return True
    text = _normalize_search(query)
    digits = re.sub(r"\D", "", query)
    if digits and any(digits == protocol for protocol in customer["protocols"]):
        return True
    if len(digits) >= 3 and (digits in customer["cpf"] or any(digits in p for p in customer["protocols"])):
        return True
    haystack = [customer["name"], *customer["protocols"]]
    haystack += [CATEGORY_LABELS.get(value, "") for value in customer["categories"]]
    haystack += [DESTINATION_LABELS.get(value, "") for value in customer["departments"]]
    haystack += [CHANNEL_LABELS.get(value, "") for value in customer["channels"]]
    haystack += list(customer["channels"]) + list(customer["departments"])
    return any(text and text in _normalize_search(item) for item in haystack)


def list_customers(query: str = "", department: str = "", channel: str = "") -> list[dict[str, Any]]:
    """Clientes encontrados para o Cockpit, com o resumo da jornada de cada CPF."""
    list_sessions(include_closed=True)  # aplica expiração pendente
    with get_connection() as connection:
        customers = {row["cpf"]: dict(row) for row in connection.execute("SELECT cpf, name FROM customers")}
        sessions = [_row_to_dict(row) for row in connection.execute("SELECT * FROM cce_sessions")]
    interactions = _interaction_rows("1 = 1", ())

    grouped: dict[str, dict[str, Any]] = {}
    for cpf, customer in customers.items():
        grouped[cpf] = {
            "cpf": cpf,
            "masked_cpf": mask_cpf(cpf),
            "name": customer["name"],
            "protocols": [],
            "open_cases": 0,
            "total_cases": 0,
            "categories": set(),
            "departments": set(),
            "channels": set(),
            "contacts": 0,
            "last_contact_at": None,
            "last_channel": None,
            "last_department": None,
            "last_summary": None,
        }
    for session in sessions:
        entry = grouped[session["cpf"]]
        entry["protocols"].append(session["protocol"])
        entry["total_cases"] += 1
        entry["open_cases"] += session["status"] not in CLOSED_STATUSES
        if session.get("category"):
            entry["categories"].add(session["category"])
        if session.get("destination_department"):
            entry["departments"].add(session["destination_department"])
    for interaction in interactions:
        entry = grouped[interaction["cpf"]]
        entry["contacts"] += 1
        entry["channels"].add(interaction["channel"])
        if interaction.get("destination_department"):
            entry["departments"].add(interaction["destination_department"])
        entry["last_contact_at"] = interaction["started_at"]
        entry["last_channel"] = interaction["channel"]
        entry["last_department"] = interaction.get("destination_department")
        entry["last_summary"] = interaction.get("summary")

    department = (department or "").upper()
    channel = (channel or "").upper()
    result = []
    for entry in grouped.values():
        if not entry["contacts"] and not (query and _customer_matches(query, entry)):
            continue
        if department and department not in entry["departments"]:
            continue
        if channel and channel not in entry["channels"]:
            continue
        if not _customer_matches(query, entry):
            continue
        entry["categories"] = sorted(entry["categories"])
        entry["departments"] = sorted(entry["departments"])
        entry["channels"] = [item for item in CUSTOMER_CHANNELS if item in entry["channels"]]
        result.append(entry)
    result.sort(key=lambda item: item["last_contact_at"] or "", reverse=True)
    return result


def customer_overview(cpf: str) -> dict[str, Any]:
    normalized = normalize_cpf(cpf)
    customer = get_customer(normalized)
    if not customer:
        raise NotFoundError("Cliente não encontrado.")
    with get_connection() as connection:
        rows = connection.execute(
            "SELECT * FROM cce_sessions WHERE cpf = ? ORDER BY created_at ASC", (normalized,)
        ).fetchall()
    cases = [expire_if_needed(_row_to_dict(row)) for row in rows]
    interactions = _interaction_rows("i.cpf = ?", (normalized,))
    for interaction in interactions:
        interaction["has_record"] = bool(interaction.get("transcript") or interaction["message_count"])
        interaction.pop("transcript", None)
        interaction["audio_available"] = bool(interaction.pop("audio_path", None))
    return {
        "customer": {"cpf": normalized, "masked_cpf": mask_cpf(normalized), "name": customer["name"]},
        "cases": [
            {key: value for key, value in case.items() if key != "transcript"}
            for case in cases
        ],
        "interactions": interactions,
    }


def reset_demo(seed_history: bool = True) -> None:
    with get_connection() as connection:
        clear_data(connection)
        seed_customers(connection)
    if seed_history:
        from demo_seed import seed_demo_history

        seed_demo_history()
