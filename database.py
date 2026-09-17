from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from config import settings


SCHEMA_VERSION = 2

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS customers (
    cpf TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL DEFAULT ''
);

-- Protocolo: um atendimento sobre um tema. O mesmo CPF pode ter vários.
CREATE TABLE IF NOT EXISTS cce_sessions (
    id TEXT PRIMARY KEY,
    protocol TEXT NOT NULL UNIQUE,
    cpf TEXT NOT NULL,
    customer_name TEXT NOT NULL,
    status TEXT NOT NULL,
    channel_origin TEXT NOT NULL,
    current_channel TEXT NOT NULL,
    initial_department TEXT NOT NULL,
    transcript TEXT,
    intent TEXT,
    category TEXT,
    problem TEXT,
    summary TEXT,
    structured_context TEXT NOT NULL DEFAULT '{}',
    destination_department TEXT,
    suggested_action TEXT,
    priority TEXT,
    assigned_agent TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    resolved_at TEXT,
    FOREIGN KEY (cpf) REFERENCES customers(cpf)
);

CREATE INDEX IF NOT EXISTS idx_sessions_cpf_updated
ON cce_sessions(cpf, updated_at DESC);

-- Contato: cada passagem do cliente por um canal dentro de um protocolo.
CREATE TABLE IF NOT EXISTS cce_interactions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    cpf TEXT NOT NULL,
    channel TEXT NOT NULL,
    interaction_type TEXT NOT NULL,
    status TEXT NOT NULL,
    verification TEXT NOT NULL DEFAULT 'NENHUMA',
    input_kind TEXT NOT NULL,
    agent TEXT,
    audio_path TEXT,
    transcript TEXT,
    intent TEXT,
    problem TEXT,
    summary TEXT,
    category TEXT,
    destination_department TEXT,
    structured_context TEXT NOT NULL DEFAULT '{}',
    outcome TEXT,
    source TEXT NOT NULL DEFAULT 'IA',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    FOREIGN KEY (session_id) REFERENCES cce_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_interactions_cpf_started
ON cce_interactions(cpf, started_at ASC);

CREATE INDEX IF NOT EXISTS idx_interactions_session
ON cce_interactions(session_id, started_at ASC);

CREATE TABLE IF NOT EXISTS cce_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    interaction_id TEXT NOT NULL,
    author TEXT NOT NULL,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (interaction_id) REFERENCES cce_interactions(id) ON DELETE CASCADE
);

-- Auditoria técnica (Debug): eventos do sistema e das IAs.
CREATE TABLE IF NOT EXISTS cce_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES cce_sessions(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_events_session_created
ON cce_events(session_id, created_at ASC);

-- Acesso do cliente a um canal: token opaco e código de verificação (hash).
CREATE TABLE IF NOT EXISTS channel_access (
    token TEXT PRIMARY KEY,
    cpf TEXT NOT NULL,
    channel TEXT NOT NULL,
    focus_session_id TEXT,
    verification TEXT NOT NULL,
    code_hash TEXT,
    code_expires_at TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    sends INTEGER NOT NULL DEFAULT 0,
    verified_at TEXT,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- Telemetria das IAs para a visão do gestor. Não guarda conteúdo.
CREATE TABLE IF NOT EXISTS ai_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    stage TEXT NOT NULL,
    channel TEXT,
    success INTEGER NOT NULL,
    duration_ms INTEGER NOT NULL,
    redactions INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

-- Resumo executivo por CPF, reaproveitado enquanto a jornada não muda.
CREATE TABLE IF NOT EXISTS customer_insights (
    cpf TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    payload TEXT NOT NULL,
    source TEXT NOT NULL,
    generated_at TEXT NOT NULL
);
"""

# Tabelas de dados de atendimento, da mais dependente para a menos dependente.
DATA_TABLES = (
    "cce_messages",
    "cce_interactions",
    "cce_events",
    "channel_access",
    "customer_insights",
    "ai_runs",
    "cce_sessions",
)


DEMO_CUSTOMERS = (
    ("12345678900", "Lucas de Alencar"),
    ("98765432100", "Marina Costa"),
    ("11122233344", "Rafael Nogueira"),
    ("22233344455", "Ana Beatriz Moura"),
    ("33344455566", "Bruno Tavares Lima"),
    ("44455566677", "Camila Ribeiro Nunes"),
    ("55566677788", "Diego Martins Rocha"),
    ("66677788899", "Elisa Fernandes Prado"),
    ("77788899900", "Felipe Andrade Melo"),
    ("88899900011", "Gabriela Souza Pires"),
    ("99900011122", "Henrique Barros Dias"),
    ("10120230344", "Isabela Monteiro Luz"),
)

# Celulares fictícios, usados apenas para exibir o destino mascarado do SMS simulado.
DEMO_PHONES = {cpf: f"1190000{index:04d}" for index, (cpf, _name) in enumerate(DEMO_CUSTOMERS, start=1)}


def connect() -> sqlite3.Connection:
    connection = sqlite3.connect(settings.database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = connect()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def seed_customers(connection: sqlite3.Connection) -> None:
    connection.executemany(
        """INSERT INTO customers (cpf, name, phone) VALUES (?, ?, ?)
           ON CONFLICT(cpf) DO UPDATE SET phone = excluded.phone WHERE customers.phone = ''""",
        [(cpf, name, DEMO_PHONES[cpf]) for cpf, name in DEMO_CUSTOMERS],
    )


def clear_data(connection: sqlite3.Connection) -> None:
    for table in DATA_TABLES:
        connection.execute(f"DELETE FROM {table}")


def initialize_database(seed_history: bool = False) -> None:
    """Cria o schema. Bancos de versões anteriores são recriados (dados de demonstração apenas).

    Com seed_history=True, um banco novo ou migrado recebe o histórico fictício de demonstração.
    """
    with get_connection() as connection:
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        outdated = version < SCHEMA_VERSION
        if outdated:
            for table in DATA_TABLES:
                connection.execute(f"DROP TABLE IF EXISTS {table}")
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(customers)")}
            if columns and "phone" not in columns:
                connection.execute("ALTER TABLE customers ADD COLUMN phone TEXT NOT NULL DEFAULT ''")
        connection.executescript(SCHEMA)
        seed_customers(connection)
        if outdated:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    if outdated and seed_history:
        from demo_seed import seed_demo_history

        seed_demo_history()


def database_health() -> bool:
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        return False
