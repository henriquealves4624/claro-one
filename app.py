from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from config import BASE_DIR
from database import initialize_database
from routes import api, channel_api, pages


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize_database(seed_history=True)
    yield


app = FastAPI(
    title="Claro One",
    description="Protótipo acadêmico de continuidade de contexto entre canais.",
    version="2.0.0",
    lifespan=lifespan,
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
app.include_router(api.router)
app.include_router(channel_api.router)
app.include_router(pages.router)
