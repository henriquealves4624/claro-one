"""Indicadores de funcionamento da CCE para a visão do gestor.

Os indicadores medem a solução (continuidade de contexto, transbordo entre canais,
classificação e saúde das IAs). Não há dados de satisfação.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from typing import Any

from config import settings
from database import get_connection
from models import (
    CATEGORY_DESTINATIONS,
    CATEGORY_LABELS,
    CHANNEL_LABELS,
    CLOSED_STATUSES,
    CUSTOMER_CHANNELS,
    DESTINATION_LABELS,
)
from services import cce_service
from utils import now_local, parse_datetime

AI_STAGES = {
    "TRANSCRICAO": "IA de transcrição",
    "CONTEXTO": "IA de contexto",
    "RESUMO_EXECUTIVO": "Resumo executivo",
}


def _ratio(part: float, total: float) -> float | None:
    return round(part / total, 4) if total else None


def _duplicate_openings(interactions: list[dict[str, Any]], sessions: dict[str, dict[str, Any]]) -> int:
    """Novos protocolos abertos no mesmo tema enquanto o cliente já tinha um protocolo aberto."""
    duplicates = 0
    openings = [item for item in interactions if item["interaction_type"] == "ABERTURA"]
    for opening in openings:
        category = opening.get("category")
        if not category or category == "OUTROS":
            continue
        started = parse_datetime(opening["started_at"])
        for other in sessions.values():
            if other["id"] == opening["session_id"] or other["cpf"] != opening["cpf"]:
                continue
            if other.get("category") != category or parse_datetime(other["created_at"]) >= started:
                continue
            closed_at = other.get("resolved_at")
            if closed_at is None and other["status"] == "EXPIRADA":
                closed_at = other["updated_at"]
            if closed_at is None or parse_datetime(closed_at) > started:
                duplicates += 1
                break
    return duplicates


def dashboard(days: int | None = 14) -> dict[str, Any]:
    cce_service.list_sessions(include_closed=True)  # aplica expiração pendente
    now = now_local()
    since = now - timedelta(days=days) if days else None
    with get_connection() as connection:
        all_sessions = {
            row["id"]: dict(row) for row in connection.execute("SELECT * FROM cce_sessions")
        }
        interaction_rows = connection.execute(
            "SELECT * FROM cce_interactions ORDER BY started_at ASC"
        ).fetchall()
        run_rows = connection.execute(
            "SELECT * FROM ai_runs WHERE (? IS NULL OR created_at >= ?)",
            (since.isoformat() if since else None, since.isoformat() if since else None),
        ).fetchall()

    interactions = [
        dict(row)
        for row in interaction_rows
        if since is None or parse_datetime(row["started_at"]) >= since
    ]
    touched_ids = {item["session_id"] for item in interactions}
    sessions = [all_sessions[session_id] for session_id in touched_ids]

    contacts = len(interactions)
    resumed = sum(item["interaction_type"] == "RETOMADA" for item in interactions)
    openings = contacts - resumed

    by_session: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in interactions:
        by_session[item["session_id"]].append(item)
    transitions: Counter[tuple[str, str]] = Counter()
    for items in by_session.values():
        for previous, current in zip(items, items[1:]):
            if previous["channel"] != current["channel"]:
                transitions[(previous["channel"], current["channel"])] += 1
    handoffs = sum(transitions.values())
    cross_channel_cases = sum(len({item["channel"] for item in items}) > 1 for items in by_session.values())
    duplicates = _duplicate_openings(interactions, all_sessions)

    resolved = [session for session in sessions if session["status"] == "RESOLVIDA" and session.get("resolved_at")]
    resolution_hours = [
        (parse_datetime(session["resolved_at"]) - parse_datetime(session["created_at"])).total_seconds() / 3600
        for session in resolved
    ]
    classified = [session for session in sessions if session.get("category")]
    specific = [session for session in classified if session["category"] != "OUTROS"]

    department_counts: dict[str, dict[str, int]] = {
        department: {"cases": 0, "open": 0, "contacts": 0} for department in CATEGORY_DESTINATIONS.values()
    }
    for session in sessions:
        department = session.get("destination_department")
        if department in department_counts:
            department_counts[department]["cases"] += 1
            department_counts[department]["open"] += session["status"] not in CLOSED_STATUSES
    for item in interactions:
        department = item.get("destination_department")
        if department in department_counts:
            department_counts[department]["contacts"] += 1

    channel_counts = {
        channel: {"openings": 0, "resumptions": 0} for channel in CUSTOMER_CHANNELS
    }
    for item in interactions:
        key = "resumptions" if item["interaction_type"] == "RETOMADA" else "openings"
        channel_counts[item["channel"]][key] += 1

    first_day = (since or (parse_datetime(interactions[0]["started_at"]) if interactions else now)).date()
    span = min((now.date() - first_day).days, 60)
    daily_index = {
        (now.date() - timedelta(days=offset)).isoformat(): {"openings": 0, "resumptions": 0}
        for offset in range(span, -1, -1)
    }
    for item in interactions:
        day = parse_datetime(item["started_at"]).date().isoformat()
        if day in daily_index:
            key = "resumptions" if item["interaction_type"] == "RETOMADA" else "openings"
            daily_index[day][key] += 1

    runs = [dict(row) for row in run_rows]
    ai_health = []
    for stage, label in AI_STAGES.items():
        stage_runs = [run for run in runs if run["stage"] == stage]
        successes = [run for run in stage_runs if run["success"]]
        ai_health.append(
            {
                "stage": stage,
                "label": label,
                "runs": len(stage_runs),
                "success_rate": _ratio(len(successes), len(stage_runs)),
                "avg_latency_ms": round(sum(run["duration_ms"] for run in successes) / len(successes))
                if successes else None,
            }
        )

    return {
        "generated_at": now.isoformat(),
        "period_days": days,
        "provenance": {
            "contacts": contacts,
            "demo_contacts": sum(item["source"] == "DEMO" for item in interactions),
        },
        "kpis": {
            "contacts": contacts,
            "openings": openings,
            "resumptions": resumed,
            "context_reuse_rate": _ratio(resumed, contacts),
            "cases": len(sessions),
            "open_cases": sum(session["status"] not in CLOSED_STATUSES for session in sessions),
            "resolved_cases": sum(session["status"] == "RESOLVIDA" for session in sessions),
            "cross_channel_cases": cross_channel_cases,
            "cross_channel_rate": _ratio(cross_channel_cases, len(by_session)),
            "channel_handoffs": handoffs,
            "duplicate_openings": duplicates,
            "continuity_rate": _ratio(handoffs, handoffs + duplicates),
            "contacts_per_case": round(contacts / len(by_session), 2) if by_session else None,
            "triage_avoided": resumed,
            "triage_minutes_saved": round(resumed * settings.triage_minutes_estimate, 1),
            "triage_minutes_assumption": settings.triage_minutes_estimate,
            "avg_resolution_hours": round(sum(resolution_hours) / len(resolution_hours), 1)
            if resolution_hours else None,
            "classification_coverage": _ratio(len(specific), len(classified)),
            "redactions": sum(run["redactions"] for run in runs),
        },
        "departments": [
            {
                "department": department,
                "label": DESTINATION_LABELS[department],
                "category_label": CATEGORY_LABELS[category],
                **department_counts[department],
            }
            for category, department in CATEGORY_DESTINATIONS.items()
        ],
        "channels": [
            {"channel": channel, "label": CHANNEL_LABELS[channel], **channel_counts[channel]}
            for channel in CUSTOMER_CHANNELS
        ],
        "handoff_flows": [
            {
                "from": origin,
                "from_label": CHANNEL_LABELS[origin],
                "to": destination,
                "to_label": CHANNEL_LABELS[destination],
                "count": count,
            }
            for (origin, destination), count in transitions.most_common()
        ],
        "daily": [{"date": day, **values} for day, values in daily_index.items()],
        "ai_health": ai_health,
    }
