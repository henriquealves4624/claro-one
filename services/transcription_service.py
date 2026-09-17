from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from groq import Groq

from config import settings
from services.telemetry import ai_run


logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".wav", ".mp3", ".m4a", ".webm", ".ogg"}
MIN_AUDIO_BYTES = 256
DEMO_TRANSCRIPT = (
    "Olá, estou entrando em contato porque vi na minha fatura uma cobrança de trinta e cinco "
    "reais referente a um pacote adicional de internet. Eu não contratei esse pacote e gostaria "
    "de contestar essa cobrança."
)


class TranscriptionError(Exception):
    pass


class TranscriptionProviderError(TranscriptionError):
    pass


def _create_client() -> Groq:
    if not settings.groq_api_key:
        raise TranscriptionProviderError(
            "A chave GROQ_API_KEY não está configurada. Adicione a chave ao arquivo .env."
        )
    return Groq(api_key=settings.groq_api_key, timeout=settings.groq_timeout_seconds)


def _matches_audio_signature(suffix: str, header: bytes) -> bool:
    if suffix == ".wav":
        return len(header) >= 12 and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
    if suffix == ".mp3":
        return header.startswith(b"ID3") or (
            len(header) >= 2 and header[0] == 0xFF and header[1] & 0xE0 == 0xE0
        )
    if suffix == ".m4a":
        return len(header) >= 12 and header[4:8] == b"ftyp"
    if suffix == ".webm":
        return header.startswith(b"\x1a\x45\xdf\xa3")
    if suffix == ".ogg":
        return header.startswith(b"OggS")
    return False


def validate_audio_file(audio_path: str | Path) -> None:
    path = Path(audio_path)
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise TranscriptionError("A gravação não foi encontrada ou possui formato inválido.")
    if path.stat().st_size < MIN_AUDIO_BYTES:
        raise TranscriptionError("A gravação está vazia ou é curta demais para processamento.")
    try:
        with path.open("rb") as audio_file:
            header = audio_file.read(32)
    except OSError as exc:
        raise TranscriptionError("A gravação não pôde ser lida.") from exc
    if not _matches_audio_signature(path.suffix.lower(), header):
        raise TranscriptionError(
            "O conteúdo não corresponde a um áudio WAV, MP3, M4A, WEBM ou OGG válido."
        )


def _friendly_api_error(exc: Exception) -> TranscriptionProviderError:
    status_code = getattr(exc, "status_code", None)
    error_name = type(exc).__name__
    if status_code in {401, 403} or error_name == "AuthenticationError":
        return TranscriptionProviderError(
            "A chave da Groq é inválida ou não possui acesso. Verifique GROQ_API_KEY no arquivo .env."
        )
    if status_code == 429 or error_name == "RateLimitError":
        return TranscriptionProviderError(
            "O limite de uso da Groq foi atingido. Aguarde alguns instantes e tente novamente."
        )
    if error_name in {"APITimeoutError", "TimeoutException", "ReadTimeout"}:
        return TranscriptionProviderError(
            "A transcrição excedeu o tempo de resposta da Groq. Tente novamente."
        )
    if error_name in {"APIConnectionError", "ConnectError", "NetworkError"}:
        return TranscriptionProviderError(
            "Não foi possível conectar à Groq. Verifique sua internet e tente novamente."
        )
    if status_code == 413:
        return TranscriptionProviderError("A gravação ultrapassa o limite aceito pela Groq.")
    return TranscriptionProviderError(
        "A Groq não conseguiu transcrever a gravação. Verifique o áudio e tente novamente."
    )


def _transcription_text(response: Any) -> str:
    if isinstance(response, str):
        return response.strip()
    return str(getattr(response, "text", "") or "").strip()


def transcribe_audio(audio_path: str | Path, channel: str | None = "TELEFONE") -> str:
    path = Path(audio_path)
    validate_audio_file(path)

    with ai_run("TRANSCRICAO", channel) as run:
        if settings.demo_fallback:
            logger.warning("DEMO_FALLBACK ativo: utilizando transcrição explícita de demonstração")
            run.success = True
            return DEMO_TRANSCRIPT

        try:
            client = _create_client()
            with path.open("rb") as audio_file:
                response = client.audio.transcriptions.create(
                    file=(path.name, audio_file.read()),
                    model=settings.groq_transcription_model,
                    language="pt",
                    response_format="json",
                    temperature=0.0,
                )
            transcript = _transcription_text(response)
        except TranscriptionError:
            raise
        except Exception as exc:
            logger.exception("Falha na transcrição pela Groq")
            raise _friendly_api_error(exc) from exc

        if not transcript:
            raise TranscriptionError("A gravação não contém fala reconhecível em português.")
        run.success = True
        return transcript
