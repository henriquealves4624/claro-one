from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, Field, field_validator, model_validator

from models import CATEGORY_DESTINATIONS, DestinationDepartment, ServiceCategory


CustomerChannel = Literal["TELEFONE", "WHATSAPP", "MINHA_CLARO"]


def _strip_text(value: Any, minimum: int, message: str) -> str:
    text = str(value or "").strip()
    if len(text) < minimum:
        raise ValueError(message)
    return text


class IdentifyRequest(BaseModel):
    channel: CustomerChannel
    cpf: str = Field(max_length=20)
    protocol: str | None = Field(default=None, max_length=20)


class VerifyRequest(BaseModel):
    code: str = Field(min_length=4, max_length=8)


class PhoneCaseCreate(BaseModel):
    department: str = Field(max_length=40)


class MessageCaseCreate(BaseModel):
    message: str = Field(min_length=3, max_length=2000)
    area_category: str | None = Field(default=None, max_length=40)

    @field_validator("message")
    @classmethod
    def message_must_have_content(cls, value: str) -> str:
        return _strip_text(value, 3, "Escreva uma mensagem com pelo menos 3 caracteres.")


class ChannelMessage(BaseModel):
    text: str = Field(min_length=1, max_length=2000)

    @field_validator("text")
    @classmethod
    def text_must_have_content(cls, value: str) -> str:
        return _strip_text(value, 1, "Escreva uma mensagem.")


class FinishInteraction(BaseModel):
    outcome: Literal["RESOLVIDO", "EM_ABERTO"] = "EM_ABERTO"


class ContextCase(BaseModel):
    intent: str | None = None
    category: ServiceCategory = ServiceCategory.OUTROS
    problem: str | None = None
    summary: str | None = None
    interaction_summary: str | None = None
    structured_context: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("structured_context", "entities"),
    )
    destination_department: DestinationDepartment = DestinationDepartment.OUTROS
    suggested_action: str | None = None
    priority: Literal["BAIXA", "NORMAL", "ALTA", "URGENTE"] = "NORMAL"

    @model_validator(mode="before")
    @classmethod
    def normalize_taxonomy(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        category = str(normalized.get("category") or "").strip().upper()
        destination = str(normalized.get("destination_department") or "").strip().upper()
        expected_destination = CATEGORY_DESTINATIONS.get(category)
        if expected_destination is None or destination != expected_destination:
            normalized["category"] = ServiceCategory.OUTROS.value
            normalized["destination_department"] = DestinationDepartment.OUTROS.value
        else:
            normalized["category"] = category
            normalized["destination_department"] = destination
        return normalized

    @field_validator("structured_context", mode="before")
    @classmethod
    def entities_must_be_object(cls, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @field_validator("priority", mode="before")
    @classmethod
    def normalize_missing_priority(cls, value: Any) -> Any:
        if value is None or str(value).strip().lower() in {"", "null", "none"}:
            return "NORMAL"
        return str(value).strip().upper()

    @model_validator(mode="after")
    def case_must_contain_actionable_context(self) -> "ContextCase":
        required = (self.problem, self.summary, self.destination_department)
        if any(not value or str(value).strip().lower() == "null" for value in required):
            raise ValueError("O case precisa conter problema, resumo e setor de destino.")
        if not self.interaction_summary or self.interaction_summary.strip().lower() == "null":
            self.interaction_summary = self.summary
        return self

    @property
    def entities(self) -> dict[str, Any]:
        """Compatibilidade com chamadas internas e testes criados antes do novo nome."""
        return self.structured_context


class ExecutiveSummary(BaseModel):
    headline: str = Field(min_length=3)
    narrative: str = Field(min_length=10)
    attention_points: list[str] = Field(default_factory=list)
    next_best_action: str | None = None

    @field_validator("attention_points", mode="before")
    @classmethod
    def points_must_be_list(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value if str(item or "").strip()][:3]
