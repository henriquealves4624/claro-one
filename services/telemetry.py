"""Telemetria das IAs: etapa, sucesso, latência e quantidade de dados mascarados."""
from __future__ import annotations

import logging
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterator

from database import get_connection
from utils import now_local


logger = logging.getLogger(__name__)


class RunRecorder:
    def __init__(self) -> None:
        self.redactions = 0
        self.success = False


def record_ai_run(stage: str, channel: str | None, success: bool, duration_ms: int, redactions: int = 0) -> None:
    try:
        with get_connection() as connection:
            connection.execute(
                """INSERT INTO ai_runs (stage, channel, success, duration_ms, redactions, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (stage, channel, int(success), duration_ms, redactions, now_local().isoformat()),
            )
    except sqlite3.Error:
        logger.warning("Não foi possível registrar a telemetria da IA", exc_info=True)


@contextmanager
def ai_run(stage: str, channel: str | None = None) -> Iterator[RunRecorder]:
    """Mede uma chamada de IA. Marque `recorder.success = True` quando ela terminar bem."""
    recorder = RunRecorder()
    started = time.perf_counter()
    try:
        yield recorder
    finally:
        duration_ms = int((time.perf_counter() - started) * 1000)
        record_ai_run(stage, channel, recorder.success, duration_ms, recorder.redactions)
