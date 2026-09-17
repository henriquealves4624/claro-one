from __future__ import annotations

from enum import StrEnum


class ServiceCategory(StrEnum):
    INTERNET = "INTERNET"
    TELEFONIA = "TELEFONIA"
    FATURAMENTO = "FATURAMENTO"
    TV = "TV"
    PLANOS = "PLANOS"
    INSTALACAO = "INSTALACAO"
    CANCELAMENTO = "CANCELAMENTO"
    OUTROS = "OUTROS"


class DestinationDepartment(StrEnum):
    SUPORTE_TECNICO = "SUPORTE_TECNICO"
    SUPORTE_TELEFONIA = "SUPORTE_TELEFONIA"
    FINANCEIRO = "FINANCEIRO"
    SUPORTE_TV = "SUPORTE_TV"
    COMERCIAL = "COMERCIAL"
    SERVICOS_CAMPO = "SERVICOS_CAMPO"
    RETENCAO_CANCELAMENTO = "RETENCAO_CANCELAMENTO"
    OUTROS = "OUTROS"


# A ordem das categorias define também o menu da URA (1 a 8).
CATEGORY_DESTINATIONS = {
    ServiceCategory.INTERNET.value: DestinationDepartment.SUPORTE_TECNICO.value,
    ServiceCategory.TELEFONIA.value: DestinationDepartment.SUPORTE_TELEFONIA.value,
    ServiceCategory.FATURAMENTO.value: DestinationDepartment.FINANCEIRO.value,
    ServiceCategory.TV.value: DestinationDepartment.SUPORTE_TV.value,
    ServiceCategory.PLANOS.value: DestinationDepartment.COMERCIAL.value,
    ServiceCategory.INSTALACAO.value: DestinationDepartment.SERVICOS_CAMPO.value,
    ServiceCategory.CANCELAMENTO.value: DestinationDepartment.RETENCAO_CANCELAMENTO.value,
    ServiceCategory.OUTROS.value: DestinationDepartment.OUTROS.value,
}

CATEGORY_LABELS = {
    ServiceCategory.INTERNET.value: "Internet",
    ServiceCategory.TELEFONIA.value: "Telefonia e linha",
    ServiceCategory.FATURAMENTO.value: "Fatura e pagamentos",
    ServiceCategory.TV.value: "TV e streaming",
    ServiceCategory.PLANOS.value: "Planos e ofertas",
    ServiceCategory.INSTALACAO.value: "Instalação e endereço",
    ServiceCategory.CANCELAMENTO.value: "Cancelamento",
    ServiceCategory.OUTROS.value: "Outros assuntos",
}

DESTINATION_LABELS = {
    DestinationDepartment.SUPORTE_TECNICO.value: "Suporte técnico",
    DestinationDepartment.SUPORTE_TELEFONIA.value: "Suporte de telefonia",
    DestinationDepartment.FINANCEIRO.value: "Financeiro",
    DestinationDepartment.SUPORTE_TV.value: "Suporte de TV",
    DestinationDepartment.COMERCIAL.value: "Comercial",
    DestinationDepartment.SERVICOS_CAMPO.value: "Serviços de campo",
    DestinationDepartment.RETENCAO_CANCELAMENTO.value: "Retenção e cancelamento",
    DestinationDepartment.OUTROS.value: "Outros",
}

# Área do Minha Claro mais adequada para cada categoria.
CATEGORY_AREAS = {
    ServiceCategory.INTERNET.value: "internet",
    ServiceCategory.TELEFONIA.value: "phone",
    ServiceCategory.FATURAMENTO.value: "billing",
    ServiceCategory.TV.value: "tv",
    ServiceCategory.PLANOS.value: "plans",
    ServiceCategory.INSTALACAO.value: "address",
    ServiceCategory.CANCELAMENTO.value: "cancel",
    ServiceCategory.OUTROS.value: "help",
}

CUSTOMER_CHANNELS = ("TELEFONE", "WHATSAPP", "MINHA_CLARO")
CHANNEL_LABELS = {
    "TELEFONE": "Telefone / URA",
    "WHATSAPP": "WhatsApp",
    "MINHA_CLARO": "Minha Claro",
    "COCKPIT": "Cockpit",
    "URA": "URA",
    "SISTEMA": "Sistema",
    "IA_TRANSCRICAO": "IA de transcrição",
    "IA_CONTEXTO": "IA de contexto",
}

SESSION_STATUSES = {
    "EM_ATENDIMENTO",
    "PROCESSANDO",
    "SUSPENSA",
    "RETOMADA",
    "EM_ATENDIMENTO_HUMANO",
    "RESOLVIDA",
    "EXPIRADA",
}
STATUS_LABELS = {
    "EM_ATENDIMENTO": "Em ligação",
    "PROCESSANDO": "Processando",
    "SUSPENSA": "Aguardando continuidade",
    "RETOMADA": "Retomada",
    "EM_ATENDIMENTO_HUMANO": "Com especialista",
    "RESOLVIDA": "Resolvida",
    "EXPIRADA": "Expirada",
}
CLOSED_STATUSES = {"RESOLVIDA", "EXPIRADA"}
RESUMABLE_STATUSES = {"SUSPENSA", "RETOMADA", "EM_ATENDIMENTO_HUMANO"}

INTERACTION_TYPE_LABELS = {"ABERTURA": "Novo atendimento", "RETOMADA": "Retomada de contexto"}
INTERACTION_STATUS_LABELS = {
    "EM_ANDAMENTO": "Em andamento",
    "PROCESSANDO": "Processando",
    "CONCLUIDA": "Concluído",
}
INPUT_KINDS = {"AUDIO", "CONVERSA", "FORMULARIO"}
OUTCOMES = {"RESOLVIDO", "EM_ABERTO"}
VERIFICATION_LABELS = {"SMS": "SMS", "LOGIN": "Login no app", "NENHUMA": "Primeiro contato"}

PRIORITY_LABELS = {"BAIXA": "Baixa", "NORMAL": "Normal", "ALTA": "Alta", "URGENTE": "Urgente"}


def taxonomy_payload() -> dict:
    """Taxonomia única compartilhada com o frontend."""
    return {
        "categories": [
            {
                "value": category,
                "label": CATEGORY_LABELS[category],
                "department": department,
                "departmentLabel": DESTINATION_LABELS[department],
                "area": CATEGORY_AREAS[category],
            }
            for category, department in CATEGORY_DESTINATIONS.items()
        ],
        "channels": CHANNEL_LABELS,
        "customerChannels": list(CUSTOMER_CHANNELS),
        "statuses": STATUS_LABELS,
        "interactionTypes": INTERACTION_TYPE_LABELS,
        "interactionStatuses": INTERACTION_STATUS_LABELS,
        "priorities": PRIORITY_LABELS,
        "verifications": VERIFICATION_LABELS,
    }
