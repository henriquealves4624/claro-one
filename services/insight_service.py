"""Resumo executivo da vivência de um CPF com a Claro (Cockpit)."""
from __future__ import annotations

import hashlib
import json
import logging
from collections import Counter
from typing import Any

from database import get_connection
from models import CATEGORY_LABELS, CHANNEL_LABELS, CLOSED_STATUSES, CUSTOMER_CHANNELS, INTERACTION_TYPE_LABELS, STATUS_LABELS
from services import cce_service, context_service
from utils import format_datetime, now_local, parse_datetime


logger = logging.getLogger(__name__)


def _short_date(value: str | None) -> str:
    return parse_datetime(value).strftime("%d/%m %H:%M") if value else "—"


def journey_stats(overview: dict[str, Any]) -> dict[str, Any]:
    interactions = overview["interactions"]
    cases = overview["cases"]
    channels = Counter(item["channel"] for item in interactions)
    topics = Counter(case["category"] for case in cases if case.get("category"))
    channels_by_case: dict[str, set[str]] = {}
    for item in interactions:
        channels_by_case.setdefault(item["session_id"], set()).add(item["channel"])
    preferred = channels.most_common(1)[0][0] if channels else None
    return {
        "contacts": len(interactions),
        "channels_used": len(channels),
        "channel_breakdown": [
            {"channel": channel, "label": CHANNEL_LABELS[channel], "count": channels[channel]}
            for channel in CUSTOMER_CHANNELS
            if channels[channel]
        ],
        "cases_total": len(cases),
        "cases_open": sum(case["status"] not in CLOSED_STATUSES for case in cases),
        "cases_resolved": sum(case["status"] == "RESOLVIDA" for case in cases),
        "context_reuses": sum(item["interaction_type"] == "RETOMADA" for item in interactions),
        "cross_channel_cases": sum(len(value) > 1 for value in channels_by_case.values()),
        "top_topics": [
            {"category": category, "label": CATEGORY_LABELS.get(category, category), "count": count}
            for category, count in topics.most_common(3)
        ],
        "preferred_channel": CHANNEL_LABELS.get(preferred) if preferred else None,
        "first_contact_at": interactions[0]["started_at"] if interactions else None,
        "last_contact_at": interactions[-1]["started_at"] if interactions else None,
        "agents": sorted({item["agent"] for item in interactions if item.get("agent")}),
    }


def _journey_text(overview: dict[str, Any], stats: dict[str, Any]) -> str:
    first_name = overview["customer"]["name"].split()[0]
    lines = [
        f"Cliente: {first_name}",
        (
            f"Indicadores: {stats['contacts']} contatos em {stats['channels_used']} canais; "
            f"{stats['cases_total']} protocolos ({stats['cases_open']} em aberto); "
            f"{stats['context_reuses']} retomadas de contexto sem nova triagem; "
            f"{stats['cross_channel_cases']} protocolos passaram por mais de um canal."
        ),
        "Protocolos:",
    ]
    for case in overview["cases"]:
        lines.append(
            f"- {case['protocol']} | {CATEGORY_LABELS.get(case.get('category'), 'em análise')} | "
            f"{STATUS_LABELS.get(case['status'], case['status'])} | prioridade {case.get('priority') or 'NORMAL'} | "
            f"aberto em {_short_date(case['created_at'])} | problema: {case.get('problem') or 'não identificado'}"
        )
    lines.append("Contatos (do mais antigo ao mais recente):")
    for item in overview["interactions"][-20:]:
        lines.append(
            f"- {_short_date(item['started_at'])} | {CHANNEL_LABELS.get(item['channel'], item['channel'])} | "
            f"protocolo {item['protocol']} | {INTERACTION_TYPE_LABELS.get(item['interaction_type'])} | "
            f"{CATEGORY_LABELS.get(item.get('category'), 'em análise')} | {item.get('summary') or 'sem resumo'}"
        )
    return "\n".join(lines)


def _fingerprint(overview: dict[str, Any]) -> str:
    material = [
        [item["id"], item["status"], item.get("summary"), item.get("agent")] for item in overview["interactions"]
    ] + [[case["id"], case["status"], case.get("problem")] for case in overview["cases"]]
    return hashlib.sha256(json.dumps(material, ensure_ascii=False).encode()).hexdigest()


def rule_based_summary(overview: dict[str, Any], stats: dict[str, Any]) -> dict[str, Any]:
    first_name = overview["customer"]["name"].split()[0]
    if not stats["contacts"]:
        return {
            "headline": "Nenhum contato registrado na CCE",
            "narrative": f"{first_name} ainda não possui contatos registrados nos canais simulados.",
            "attention_points": [],
            "next_best_action": None,
        }
    topic = stats["top_topics"][0]["label"] if stats["top_topics"] else "não identificado"
    open_cases = [case for case in overview["cases"] if case["status"] not in CLOSED_STATUSES]
    headline = (
        f"{len(open_cases)} protocolo(s) em aberto · último contato em {format_datetime(stats['last_contact_at'])}"
        if open_cases
        else "Sem pendências: os protocolos registrados foram encerrados"
    )
    narrative = (
        f"{first_name} fez {stats['contacts']} contato(s) em {stats['channels_used']} canal(is) desde "
        f"{format_datetime(stats['first_contact_at'])}. Tema mais recorrente: {topic}. "
        f"A CCE evitou {stats['context_reuses']} nova(s) triagem(ns) ao retomar o contexto entre canais."
    )
    points = []
    for case in open_cases:
        if case.get("priority") in {"ALTA", "URGENTE"}:
            points.append(f"Protocolo {case['protocol']} com prioridade {case['priority'].lower()}.")
        contacts = sum(item["session_id"] == case["id"] for item in overview["interactions"])
        if contacts >= 3:
            points.append(f"Protocolo {case['protocol']} já teve {contacts} contatos sem resolução.")
    latest_open = open_cases[-1] if open_cases else None
    action = None
    if latest_open and latest_open.get("suggested_action"):
        action = latest_open["suggested_action"].replace("_", " ").capitalize()
    return {"headline": headline, "narrative": narrative, "attention_points": points[:3], "next_best_action": action}


def executive_summary(cpf: str) -> dict[str, Any]:
    overview = cce_service.customer_overview(cpf)
    stats = journey_stats(overview)
    result: dict[str, Any] = {"stats": stats}
    if not stats["contacts"]:
        result.update(rule_based_summary(overview, stats), source="REGRAS", generated_at=now_local().isoformat())
        return result

    fingerprint = _fingerprint(overview)
    normalized = overview["customer"]["cpf"]
    with get_connection() as connection:
        cached = connection.execute(
            "SELECT * FROM customer_insights WHERE cpf = ?", (normalized,)
        ).fetchone()
    if cached and cached["fingerprint"] == fingerprint:
        result.update(json.loads(cached["payload"]), source=cached["source"], generated_at=cached["generated_at"])
        return result

    try:
        summary = context_service.generate_executive_summary(_journey_text(overview, stats)).model_dump()
        source = "IA"
    except context_service.ContextServiceError as exc:
        logger.warning("Resumo executivo por IA indisponível (%s); usando regras", exc)
        summary = rule_based_summary(overview, stats)
        source = "REGRAS"
    generated_at = now_local().isoformat()
    if source == "IA":
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO customer_insights (cpf, fingerprint, payload, source, generated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(cpf) DO UPDATE SET fingerprint = excluded.fingerprint,
                   payload = excluded.payload, source = excluded.source, generated_at = excluded.generated_at""",
                (normalized, fingerprint, json.dumps(summary, ensure_ascii=False), source, generated_at),
            )
    result.update(summary, source=source, generated_at=generated_at)
    return result
