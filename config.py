from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = "CLARO ONE"
    database_path: Path = Path(os.getenv("DATABASE_PATH", BASE_DIR / "data" / "claro_one.db"))
    upload_dir: Path = Path(os.getenv("UPLOAD_DIR", BASE_DIR / "uploads"))
    groq_api_key: str = os.getenv("GROQ_API_KEY", "").strip()
    groq_transcription_model: str = os.getenv(
        "GROQ_TRANSCRIPTION_MODEL", "whisper-large-v3-turbo"
    ).strip()
    groq_context_model: str = os.getenv("GROQ_CONTEXT_MODEL", "openai/gpt-oss-20b").strip()
    groq_timeout_seconds: float = float(os.getenv("GROQ_TIMEOUT_SECONDS", "60"))
    cce_ttl_hours: int = int(os.getenv("CCE_TTL_HOURS", "2"))
    demo_fallback: bool = _as_bool(os.getenv("DEMO_FALLBACK"), False)
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_MB", "25")) * 1024 * 1024
    timezone: str = "America/Sao_Paulo"
    # Acesso dos canais: token de sessão do cliente e código de verificação por SMS.
    channel_access_minutes: int = int(os.getenv("CHANNEL_ACCESS_MINUTES", "30"))
    sms_code_minutes: int = int(os.getenv("SMS_CODE_MINUTES", "5"))
    sms_max_attempts: int = int(os.getenv("SMS_MAX_ATTEMPTS", "5"))
    sms_max_sends: int = int(os.getenv("SMS_MAX_SENDS", "3"))
    # "simulado" (padrão, sem custo) ou "twilio" (opcional, exige conta própria).
    sms_provider: str = os.getenv("SMS_PROVIDER", "simulado").strip().lower()
    twilio_account_sid: str = os.getenv("TWILIO_ACCOUNT_SID", "").strip()
    twilio_auth_token: str = os.getenv("TWILIO_AUTH_TOKEN", "").strip()
    twilio_from_number: str = os.getenv("TWILIO_FROM_NUMBER", "").strip()
    sms_test_destination: str = os.getenv("SMS_TEST_DESTINATION", "").strip()
    # Premissa usada apenas na estimativa de tempo de triagem poupado (visão do gestor).
    triage_minutes_estimate: float = float(os.getenv("TRIAGE_MINUTES_ESTIMATE", "2"))
    cockpit_agent_name: str = "Atendente Demo"


settings = Settings()
settings.database_path.parent.mkdir(parents=True, exist_ok=True)
settings.upload_dir.mkdir(parents=True, exist_ok=True)
