"""API dos canais do cliente (Telefone/URA, WhatsApp e Minha Claro).

Depois da identificação, toda chamada exige o cabeçalho X-Channel-Token.
"""
from __future__ import annotations

import logging
import uuid
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

from config import settings
from routes.api import handle_domain_error
from schemas import (
    ChannelMessage,
    FinishInteraction,
    IdentifyRequest,
    MessageCaseCreate,
    PhoneCaseCreate,
    VerifyRequest,
)
from services import cce_service, channel_service, context_service, transcription_service


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/channel")


def _channel_error(exc: Exception) -> HTTPException:
    if isinstance(exc, channel_service.AccessError):
        return HTTPException(status_code=401, detail=str(exc))
    if isinstance(exc, channel_service.VerificationError):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, context_service.ContextServiceError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, transcription_service.TranscriptionProviderError):
        return HTTPException(status_code=503, detail=str(exc))
    if isinstance(exc, transcription_service.TranscriptionError):
        return HTTPException(status_code=422, detail=str(exc))
    return handle_domain_error(exc)


def _remove_upload(path_value: str | None) -> None:
    if not path_value:
        return
    path = Path(path_value).resolve()
    if path.parent == settings.upload_dir.resolve() and path.is_file():
        path.unlink()


@router.post("/identify")
def identify(payload: IdentifyRequest):
    try:
        return channel_service.identify(payload.channel, payload.cpf, payload.protocol)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.post("/sms/resend")
def resend_code(x_channel_token: str | None = Header(default=None)):
    try:
        return channel_service.resend_code(x_channel_token)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.post("/verify")
def verify(payload: VerifyRequest, x_channel_token: str | None = Header(default=None)):
    try:
        return channel_service.verify_code(x_channel_token, payload.code)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.get("/cases")
def cases(x_channel_token: str | None = Header(default=None)):
    try:
        return channel_service.list_cases(x_channel_token)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.post("/cases/{protocol}/resume")
def resume(protocol: str, x_channel_token: str | None = Header(default=None)):
    try:
        return channel_service.resume(x_channel_token, protocol)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.post("/cases", status_code=201)
def open_message_case(payload: MessageCaseCreate, x_channel_token: str | None = Header(default=None)):
    try:
        return channel_service.open_message_case(x_channel_token, payload.message, payload.area_category)
    except Exception as exc:
        if isinstance(exc, context_service.ContextServiceError):
            logger.warning("IA de contexto indisponível ao abrir atendimento por mensagem")
        raise _channel_error(exc) from exc


@router.post("/cases/phone", status_code=201)
def open_phone_case(payload: PhoneCaseCreate, x_channel_token: str | None = Header(default=None)):
    try:
        return channel_service.open_phone_case(x_channel_token, payload.department)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.post("/interactions/{interaction_id}/messages", status_code=201)
def add_message(
    interaction_id: str,
    payload: ChannelMessage,
    x_channel_token: str | None = Header(default=None),
):
    try:
        return channel_service.add_message(x_channel_token, interaction_id, payload.text)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.post("/interactions/{interaction_id}/call/start")
def start_call(interaction_id: str, x_channel_token: str | None = Header(default=None)):
    try:
        channel_service.owned_interaction(x_channel_token, interaction_id)
        cce_service.start_call(interaction_id)
        return {"started": True}
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.post("/interactions/{interaction_id}/audio")
async def upload_audio(
    interaction_id: str,
    audio: UploadFile = File(...),
    duration_ms: int | None = Form(default=None),
    x_channel_token: str | None = Header(default=None),
):
    try:
        channel_service.owned_interaction(x_channel_token, interaction_id)
    except Exception as exc:
        await audio.close()
        raise _channel_error(exc) from exc
    suffix = Path(audio.filename or "").suffix.lower()
    if suffix not in transcription_service.SUPPORTED_EXTENSIONS:
        await audio.close()
        raise HTTPException(
            status_code=400,
            detail="Formato inválido. Envie um arquivo WAV, MP3, M4A, WEBM ou OGG.",
        )
    if duration_ms is not None and duration_ms < 1000:
        await audio.close()
        raise HTTPException(
            status_code=400,
            detail="A gravação é curta demais. Fale por pelo menos 1 segundo.",
        )
    internal_path = settings.upload_dir / f"{uuid.uuid4().hex}{suffix}"
    size = 0
    try:
        with internal_path.open("wb") as destination:
            while chunk := await audio.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"A gravação deve ter no máximo {settings.max_upload_bytes // 1024 // 1024} MB.",
                    )
                destination.write(chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="O arquivo de áudio está vazio.")
        transcription_service.validate_audio_file(internal_path)
        _interaction, previous_audio = cce_service.register_audio(interaction_id, str(internal_path))
        _remove_upload(previous_audio)
        return {"message": "Áudio recebido."}
    except HTTPException:
        internal_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        internal_path.unlink(missing_ok=True)
        raise _channel_error(exc) from exc
    finally:
        await audio.close()


@router.post("/interactions/{interaction_id}/transcribe")
def transcribe(interaction_id: str, x_channel_token: str | None = Header(default=None)):
    try:
        channel_service.owned_interaction(x_channel_token, interaction_id)
        interaction = cce_service.start_transcription(interaction_id)
        transcript = transcription_service.transcribe_audio(interaction["audio_path"], "TELEFONE")
        _updated, audio_path = cce_service.store_transcript(interaction_id, transcript)
        # Minimização: a gravação é descartada assim que a transcrição é guardada.
        _remove_upload(audio_path)
        return {"transcribed": True}
    except Exception as exc:
        if isinstance(exc, transcription_service.TranscriptionError):
            logger.warning("Falha de transcrição no contato %s", interaction_id)
        raise _channel_error(exc) from exc


@router.post("/interactions/{interaction_id}/finish")
def finish(
    interaction_id: str,
    payload: FinishInteraction | None = None,
    x_channel_token: str | None = Header(default=None),
):
    try:
        outcome = payload.outcome if payload else "EM_ABERTO"
        return channel_service.finish(x_channel_token, interaction_id, outcome)
    except Exception as exc:
        raise _channel_error(exc) from exc


@router.delete("/interactions/{interaction_id}")
def cancel_interaction(interaction_id: str, x_channel_token: str | None = Header(default=None)):
    try:
        channel_service.owned_interaction(x_channel_token, interaction_id)
        for path in cce_service.delete_interaction(interaction_id):
            _remove_upload(path)
        return {"message": "Contato cancelado."}
    except Exception as exc:
        raise _channel_error(exc) from exc
