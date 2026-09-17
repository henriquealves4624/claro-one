"""Histórico fictício de demonstração.

Cria jornadas multicanal com datas relativas ao momento do reinício, para que Cockpit,
timeline e visão do gestor tenham dados desde o início. Os registros usam source='DEMO'
e aparecem identificados como histórico de demonstração. Marina Costa, Henrique Barros Dias
e Isabela Monteiro Luz ficam sem histórico para demonstrar o primeiro contato.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from typing import Any

from database import DEMO_CUSTOMERS, get_connection
from models import CATEGORY_DESTINATIONS, CHANNEL_LABELS
from utils import now_local

DEMO_PROTOCOL = "123"
# O histórico de demonstração não pode "apodrecer" com o TTL de 2h: os protocolos
# semeados valem 30 dias, enquanto os atendimentos reais seguem CCE_TTL_HOURS.
DEMO_VALIDITY_DAYS = 30

HISTORY: list[dict[str, Any]] = [
    {
        "cpf": "12345678900",
        "protocol": DEMO_PROTOCOL,
        "category": "INTERNET",
        "status": "SUSPENSA",
        "priority": "ALTA",
        "intent": "INTERNET_SEM_CONEXAO",
        "problem": "Internet sem conexão e modem com luz vermelha.",
        "summary": (
            "Internet fora do ar desde o fim de semana; modem segue com luz vermelha mesmo após reinício. "
            "Cliente pediu visita técnica e aguarda a confirmação de falha regional."
        ),
        "entities": {"luz_modem": "vermelha", "reinicio_realizado": True, "visita_tecnica_solicitada": True},
        "suggested_action": "AGENDAR_VISITA_TECNICA",
        "agent": "Paula Ribeiro",
        "contacts": [
            {
                "channel": "TELEFONE", "type": "ABERTURA", "at": (2, 9, 12), "agent": None,
                "intent": "INTERNET_SEM_CONEXAO", "problem": "Internet sem conexão.",
                "summary": "Relatou internet fora do ar e modem com luz vermelha; já reiniciou o equipamento.",
                "entities": {"luz_modem": "vermelha", "reinicio_realizado": True},
                "transcript": (
                    "Oi, minha internet parou de funcionar desde sábado. O modem está com a luz vermelha, "
                    "eu já desliguei e liguei de novo duas vezes e continua sem conexão em nenhum aparelho."
                ),
            },
            {
                "channel": "WHATSAPP", "type": "RETOMADA", "at": (1, 18, 40), "agent": "Paula Ribeiro",
                "verification": "SMS", "intent": "SOLICITAR_VISITA_TECNICA",
                "problem": "Luz do modem segue vermelha.",
                "summary": "Retomou sem repetir a triagem; informou que a luz segue vermelha e pediu visita técnica.",
                "entities": {"visita_tecnica_solicitada": True},
                "messages": [
                    ("CLIENTE", "Continua a luz vermelha no modem. Dá para mandar um técnico?"),
                    ("CLARO", "Anotado, Lucas. O time de Suporte técnico já está com o histórico do protocolo 123."),
                    ("CLIENTE", "Posso receber o técnico em qualquer horário depois das 14h."),
                ],
            },
        ],
    },
    {
        "cpf": "12345678900",
        "protocol": "384120",
        "category": "FATURAMENTO",
        "status": "RESOLVIDA",
        "resolved_at": (10, 14, 20),
        "intent": "SEGUNDA_VIA_FATURA",
        "problem": "Solicitação de segunda via da fatura.",
        "summary": "Cliente pediu a segunda via da fatura de agosto pelo aplicativo e recebeu o documento.",
        "entities": {"mes_referencia": "agosto"},
        "suggested_action": "ENVIAR_SEGUNDA_VIA",
        "contacts": [
            {
                "channel": "MINHA_CLARO", "type": "ABERTURA", "at": (10, 14, 5), "verification": "LOGIN",
                "intent": "SEGUNDA_VIA_FATURA", "problem": "Segunda via da fatura.",
                "summary": "Solicitou a segunda via da fatura de agosto pelo app.",
                "outcome": "RESOLVIDO",
                "messages": [("CLIENTE", "Preciso da segunda via da fatura de agosto.")],
            },
        ],
    },
    {
        "cpf": "11122233344",
        "protocol": "517302",
        "category": "FATURAMENTO",
        "status": "SUSPENSA",
        "priority": "NORMAL",
        "intent": "CONTESTACAO_FATURA",
        "problem": "Cobrança não reconhecida de pacote adicional.",
        "summary": (
            "Cliente contestou cobrança de R$ 35,00 por pacote adicional de internet não contratado. "
            "Estorno aberto com prazo de 5 dias úteis; cliente acompanha pelo app."
        ),
        "entities": {"valor": 35.0, "produto": "Pacote adicional de internet", "reconhece_contratacao": False},
        "suggested_action": "ACOMPANHAR_ESTORNO",
        "agent": "Carlos Mendes",
        "contacts": [
            {
                "channel": "WHATSAPP", "type": "ABERTURA", "at": (3, 10, 30),
                "intent": "CONTESTACAO_FATURA", "problem": "Cobrança não reconhecida.",
                "summary": "Contestou cobrança de R$ 35,00 por pacote adicional de internet que não contratou.",
                "entities": {"valor": 35.0, "produto": "Pacote adicional de internet"},
                "messages": [
                    ("CLIENTE", "Veio na minha fatura um pacote adicional de internet de 35 reais que eu não contratei."),
                    ("CLARO", "Entendi: cobrança não reconhecida. Direcionei seu atendimento para Financeiro."),
                ],
            },
            {
                "channel": "TELEFONE", "type": "RETOMADA", "at": (2, 16, 5), "agent": "Carlos Mendes",
                "verification": "SMS", "intent": "CONFIRMAR_ESTORNO", "problem": "Cobrança não reconhecida.",
                "summary": "Confirmou a contestação por telefone; estorno aberto e prazo de 5 dias úteis informado.",
                "entities": {"prazo_estorno": "5 dias úteis"},
                "transcript": "Estou ligando sobre a cobrança do pacote adicional. Quero confirmar se o estorno foi aberto.",
            },
            {
                "channel": "MINHA_CLARO", "type": "RETOMADA", "at": (0, -3, 0), "verification": "LOGIN",
                "status": "CONCLUIDA", "intent": "CONSULTAR_ESTORNO", "problem": "Acompanhamento do estorno.",
                "summary": "Consultou o andamento do estorno na área de faturas.",
            },
        ],
    },
    {
        "cpf": "22233344455",
        "protocol": "602948",
        "category": "CANCELAMENTO",
        "status": "RESOLVIDA",
        "resolved_at": (4, 20, 30),
        "intent": "CANCELAMENTO_MUDANCA_CIDADE",
        "problem": "Pedido de cancelamento por mudança de cidade.",
        "summary": "Cliente pediu cancelamento por mudança de cidade; aceitou transferir o serviço para o novo endereço.",
        "entities": {"motivo": "mudança de cidade", "oferta_aceita": "transferência de endereço"},
        "suggested_action": "TRANSFERIR_ENDERECO",
        "agent": "Marcos Lima",
        "contacts": [
            {
                "channel": "TELEFONE", "type": "ABERTURA", "at": (5, 11, 20),
                "intent": "CANCELAMENTO_MUDANCA_CIDADE", "problem": "Pedido de cancelamento.",
                "summary": "Pediu o cancelamento da internet porque vai mudar de cidade.",
                "entities": {"motivo": "mudança de cidade"},
                "transcript": "Quero cancelar a minha internet porque vou me mudar de cidade no mês que vem.",
            },
            {
                "channel": "MINHA_CLARO", "type": "RETOMADA", "at": (4, 19, 2), "verification": "LOGIN",
                "status": "CONCLUIDA", "intent": "CONSULTAR_PROPOSTA", "problem": "Proposta de retenção.",
                "summary": "Consultou pelo app a proposta de transferência de endereço enviada pela retenção.",
            },
            {
                "channel": "WHATSAPP", "type": "RETOMADA", "at": (4, 20, 15), "agent": "Marcos Lima",
                "verification": "SMS", "intent": "ACEITAR_TRANSFERENCIA", "problem": "Cancelamento revertido.",
                "summary": "Aceitou transferir o serviço para o novo endereço; cancelamento revertido.",
                "outcome": "RESOLVIDO",
                "messages": [
                    ("CLIENTE", "Vi a proposta no app. Se der para levar a internet para a nova cidade, eu fico."),
                    ("CLARO", "Anotado, Ana. O time de Retenção e cancelamento já está com o histórico do protocolo 602948."),
                ],
            },
        ],
    },
    {
        "cpf": "33344455566",
        "protocol": "239571",
        "category": "TV",
        "status": "RESOLVIDA",
        "resolved_at": (6, 21, 40),
        "intent": "CANAIS_FORA_DO_AR",
        "problem": "Canais HD fora do ar no decodificador.",
        "summary": "Canais HD sem sinal no decodificador; resolvido após atualização remota do equipamento.",
        "entities": {"equipamento": "decodificador", "tipo_canal": "HD"},
        "suggested_action": "ATUALIZAR_DECODIFICADOR",
        "agent": "Juliana Prado",
        "contacts": [
            {
                "channel": "WHATSAPP", "type": "ABERTURA", "at": (6, 21, 10), "agent": "Juliana Prado",
                "intent": "CANAIS_FORA_DO_AR", "problem": "Canais HD fora do ar.",
                "summary": "Relatou canais HD sem sinal; problema resolvido após atualização remota.",
                "outcome": "RESOLVIDO",
                "messages": [("CLIENTE", "Os canais HD estão todos sem sinal no decodificador.")],
            },
        ],
    },
    {
        "cpf": "44455566677",
        "protocol": "448210",
        "category": "PLANOS",
        "status": "EM_ATENDIMENTO_HUMANO",
        "priority": "NORMAL",
        "intent": "AUMENTAR_FRANQUIA",
        "problem": "Deseja aumentar a franquia de dados do plano móvel.",
        "summary": "Cliente quer mais franquia de dados e está comparando os planos de 50 GB e 80 GB com o comercial.",
        "entities": {"franquia_desejada": "acima de 50 GB"},
        "suggested_action": "APRESENTAR_OFERTAS",
        "agent": "Juliana Prado",
        "contacts": [
            {
                "channel": "MINHA_CLARO", "type": "ABERTURA", "at": (1, 12, 30), "verification": "LOGIN",
                "intent": "AUMENTAR_FRANQUIA", "problem": "Aumentar franquia de dados.",
                "summary": "Pediu pelo app para aumentar a franquia de dados do plano móvel.",
                "messages": [("CLIENTE", "Meu plano acaba antes do fim do mês. Quero aumentar a franquia de dados.")],
            },
            {
                "channel": "WHATSAPP", "type": "RETOMADA", "at": (0, -1, 30), "agent": "Juliana Prado",
                "verification": "SMS", "status": "EM_ANDAMENTO", "intent": "COMPARAR_PLANOS",
                "problem": "Comparação de planos.",
                "summary": "Retomou pelo WhatsApp e pediu a comparação entre os planos de 50 GB e 80 GB.",
                "messages": [("CLIENTE", "Pode me mandar a diferença entre o plano de 50 e o de 80 GB?")],
            },
        ],
    },
    {
        "cpf": "55566677788",
        "protocol": "310845",
        "category": "OUTROS",
        "status": "RESOLVIDA",
        "resolved_at": (8, 15, 20),
        "intent": "ATUALIZACAO_CADASTRAL",
        "problem": "Atualização de dado cadastral.",
        "summary": "Cliente pediu para atualizar o e-mail cadastrado; tema fora das filas principais.",
        "entities": {"tipo_atualizacao": "e-mail de contato"},
        "suggested_action": "ATUALIZAR_CADASTRO",
        "contacts": [
            {
                "channel": "WHATSAPP", "type": "ABERTURA", "at": (8, 15, 0),
                "intent": "ATUALIZACAO_CADASTRAL", "problem": "Atualização cadastral.",
                "summary": "Pediu a atualização do e-mail de contato cadastrado.",
                "outcome": "RESOLVIDO",
                "messages": [("CLIENTE", "Quero trocar o e-mail do meu cadastro.")],
            },
        ],
    },
    {
        "cpf": "55566677788",
        "protocol": "725166",
        "category": "TELEFONIA",
        "status": "SUSPENSA",
        "priority": "ALTA",
        "intent": "LINHA_SEM_SINAL",
        "problem": "Linha móvel sem sinal para chamadas.",
        "summary": "Linha móvel sem sinal para fazer e receber chamadas desde a manhã; dados móveis funcionando.",
        "entities": {"servico_afetado": "chamadas de voz", "dados_moveis": "funcionando"},
        "suggested_action": "VERIFICAR_CHIP_E_COBERTURA",
        "contacts": [
            {
                "channel": "TELEFONE", "type": "ABERTURA", "at": (0, -5, 0),
                "intent": "LINHA_SEM_SINAL", "problem": "Linha sem sinal para chamadas.",
                "summary": "Relatou linha sem sinal para chamadas desde a manhã; internet móvel funciona.",
                "entities": {"servico_afetado": "chamadas de voz"},
                "transcript": "Desde hoje de manhã eu não consigo fazer nem receber ligação, mas a internet do celular funciona.",
            },
        ],
    },
    {
        "cpf": "66677788899",
        "protocol": "861204",
        "category": "INSTALACAO",
        "status": "RESOLVIDA",
        "resolved_at": (9, 10, 10),
        "intent": "MUDANCA_ENDERECO",
        "problem": "Mudança de endereço da internet.",
        "summary": "Cliente mudou de endereço; instalação agendada por telefone e concluída conforme confirmado no WhatsApp.",
        "entities": {"servico": "internet residencial", "instalacao_concluida": True},
        "suggested_action": "CONFIRMAR_INSTALACAO",
        "agent": "Rogério Alves",
        "contacts": [
            {
                "channel": "MINHA_CLARO", "type": "ABERTURA", "at": (12, 9, 40), "verification": "LOGIN",
                "intent": "MUDANCA_ENDERECO", "problem": "Mudança de endereço.",
                "summary": "Solicitou pelo app a mudança de endereço da internet residencial.",
                "messages": [("CLIENTE", "Vou mudar de apartamento e preciso levar a internet para o novo endereço.")],
            },
            {
                "channel": "TELEFONE", "type": "RETOMADA", "at": (11, 17, 25), "agent": "Rogério Alves",
                "verification": "SMS", "intent": "AGENDAR_INSTALACAO", "problem": "Agendamento da instalação.",
                "summary": "Agendou a instalação no novo endereço para sexta-feira.",
                "transcript": "Liguei para agendar a instalação no endereço novo, pode ser na sexta-feira de manhã.",
            },
            {
                "channel": "WHATSAPP", "type": "RETOMADA", "at": (9, 10, 5), "verification": "SMS",
                "intent": "CONFIRMAR_INSTALACAO", "problem": "Instalação concluída.",
                "summary": "Confirmou que a instalação no novo endereço foi concluída.",
                "outcome": "RESOLVIDO",
                "messages": [("CLIENTE", "O técnico veio e a internet já está funcionando no endereço novo.")],
            },
        ],
    },
    {
        "cpf": "77788899900",
        "protocol": "154738",
        "category": "INTERNET",
        "status": "RESOLVIDA",
        "resolved_at": (11, 18, 0),
        "intent": "INTERNET_LENTA",
        "problem": "Internet lenta no período da noite.",
        "summary": "Internet lenta à noite; ajuste de canal do Wi-Fi resolveu a lentidão.",
        "entities": {"periodo": "noite"},
        "suggested_action": "AJUSTAR_WIFI",
        "contacts": [
            {
                "channel": "TELEFONE", "type": "ABERTURA", "at": (13, 8, 50),
                "intent": "INTERNET_LENTA", "problem": "Internet lenta à noite.",
                "summary": "Relatou internet lenta principalmente à noite.",
                "transcript": "A minha internet fica muito lenta toda noite, principalmente depois das oito.",
            },
        ],
    },
    {
        "cpf": "77788899900",
        "protocol": "154902",
        "category": "INTERNET",
        "status": "RESOLVIDA",
        "resolved_at": (11, 18, 0),
        "intent": "INTERNET_LENTA",
        "problem": "Internet lenta (registro repetido).",
        "summary": "Cliente abriu nova solicitação pelo app para a mesma lentidão, sem retomar o protocolo existente.",
        "entities": {"periodo": "noite"},
        "suggested_action": "UNIFICAR_PROTOCOLOS",
        "contacts": [
            {
                "channel": "MINHA_CLARO", "type": "ABERTURA", "at": (12, 22, 10), "verification": "LOGIN",
                "intent": "INTERNET_LENTA", "problem": "Internet lenta.",
                "summary": "Registrou novamente a lentidão pelo app, gerando um protocolo duplicado.",
                "messages": [("CLIENTE", "Internet continua lenta de noite.")],
            },
        ],
    },
    {
        "cpf": "88899900011",
        "protocol": "690317",
        "category": "FATURAMENTO",
        "status": "RESOLVIDA",
        "resolved_at": (7, 13, 25),
        "intent": "CODIGO_BARRAS_FATURA",
        "problem": "Pagamento de fatura em atraso.",
        "summary": "Cliente pediu o código de barras para pagar a fatura em atraso e recebeu pelo WhatsApp.",
        "entities": {"situacao_fatura": "em atraso"},
        "suggested_action": "ENVIAR_CODIGO_BARRAS",
        "contacts": [
            {
                "channel": "WHATSAPP", "type": "ABERTURA", "at": (7, 13, 15),
                "intent": "CODIGO_BARRAS_FATURA", "problem": "Fatura em atraso.",
                "summary": "Pediu o código de barras para pagar a fatura em atraso.",
                "outcome": "RESOLVIDO",
                "messages": [("CLIENTE", "Preciso do código de barras da fatura que venceu.")],
            },
        ],
    },
]


def _moment(now: datetime, spec: tuple[int, int, int]) -> datetime:
    """(dias atrás, hora, minuto). Hora negativa significa 'horas atrás' no dia de hoje."""
    days, hour, minute = spec
    if hour < 0:
        return now - timedelta(hours=-hour, minutes=minute)
    return (now - timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)


def _input_kind(channel: str) -> str:
    return {"TELEFONE": "AUDIO", "WHATSAPP": "CONVERSA", "MINHA_CLARO": "FORMULARIO"}[channel]


def seed_demo_history() -> None:
    now = now_local()
    names = dict(DEMO_CUSTOMERS)
    with get_connection() as connection:
        for case in HISTORY:
            session_id = str(uuid.uuid4())
            contacts = case["contacts"]
            times = [_moment(now, contact["at"]) for contact in contacts]
            created_at, updated_at = times[0], times[-1]
            resolved_at = _moment(now, case["resolved_at"]) if case.get("resolved_at") else None
            if resolved_at:
                updated_at = max(updated_at, resolved_at)
            expires_at = (
                now + timedelta(days=DEMO_VALIDITY_DAYS)
                if case["status"] not in {"RESOLVIDA", "EXPIRADA"}
                else updated_at
            )
            first_transcript = next((c.get("transcript") for c in contacts if c.get("transcript")), None)
            connection.execute(
                """INSERT INTO cce_sessions (
                    id, protocol, cpf, customer_name, status, channel_origin, current_channel,
                    initial_department, transcript, intent, category, problem, summary, structured_context,
                    destination_department, suggested_action, priority, assigned_agent,
                    created_at, updated_at, expires_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    session_id, case["protocol"], case["cpf"], names[case["cpf"]], case["status"],
                    contacts[0]["channel"], contacts[-1]["channel"], case["category"], first_transcript,
                    case["intent"], case["category"], case["problem"], case["summary"],
                    json.dumps(case["entities"], ensure_ascii=False),
                    CATEGORY_DESTINATIONS[case["category"]], case["suggested_action"],
                    case.get("priority", "NORMAL"), case.get("agent"),
                    created_at.isoformat(), updated_at.isoformat(), expires_at.isoformat(),
                    resolved_at.isoformat() if resolved_at else None,
                ),
            )
            connection.execute(
                """INSERT INTO cce_events (session_id, channel, event_type, description, created_at)
                   VALUES (?, ?, 'SESSION_CREATED', ?, ?)""",
                (session_id, contacts[0]["channel"], f"Protocolo {case['protocol']} (histórico de demonstração)",
                 created_at.isoformat()),
            )
            for index, (contact, started) in enumerate(zip(contacts, times)):
                is_last = index == len(contacts) - 1
                closed = case["status"] in {"RESOLVIDA", "EXPIRADA"}
                status = contact.get("status", "CONCLUIDA")
                ended = None if status == "EM_ANDAMENTO" else (started + timedelta(minutes=8)).isoformat()
                if status == "EM_ANDAMENTO":
                    outcome = None
                else:
                    outcome = contact.get("outcome") or ("RESOLVIDO" if closed and is_last else "EM_ABERTO")
                interaction_id = str(uuid.uuid4())
                connection.execute(
                    """INSERT INTO cce_interactions (
                        id, session_id, cpf, channel, interaction_type, status, verification, input_kind,
                        agent, transcript, intent, problem, summary, category, destination_department,
                        structured_context, outcome, source, started_at, ended_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'DEMO', ?, ?)""",
                    (
                        interaction_id, session_id, case["cpf"], contact["channel"], contact["type"], status,
                        contact.get("verification", "NENHUMA"), _input_kind(contact["channel"]),
                        contact.get("agent"), contact.get("transcript"), contact["intent"], contact["problem"],
                        contact["summary"], case["category"], CATEGORY_DESTINATIONS[case["category"]],
                        json.dumps(contact.get("entities", {}), ensure_ascii=False),
                        outcome, started.isoformat(), ended,
                    ),
                )
                for offset, (author, text) in enumerate(contact.get("messages", [])):
                    connection.execute(
                        "INSERT INTO cce_messages (interaction_id, author, text, created_at) VALUES (?, ?, ?, ?)",
                        (interaction_id, author, text, (started + timedelta(minutes=offset)).isoformat()),
                    )
                if index:
                    previous = contacts[index - 1]["channel"]
                    if previous != contact["channel"]:
                        connection.execute(
                            """INSERT INTO cce_events (session_id, channel, event_type, description, created_at)
                               VALUES (?, ?, 'CHANNEL_CHANGED', ?, ?)""",
                            (
                                session_id, contact["channel"],
                                f"Transbordo de {CHANNEL_LABELS[previous]} para {CHANNEL_LABELS[contact['channel']]}",
                                started.isoformat(),
                            ),
                        )
            if resolved_at:
                connection.execute(
                    """INSERT INTO cce_events (session_id, channel, event_type, description, created_at)
                       VALUES (?, ?, 'SESSION_RESOLVED', 'Atendimento resolvido', ?)""",
                    (session_id, contacts[-1]["channel"], resolved_at.isoformat()),
                )
