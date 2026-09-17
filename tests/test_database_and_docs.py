from __future__ import annotations

import re
import sqlite3
from pathlib import Path

from config import settings
from database import DEMO_CUSTOMERS, DEMO_PHONES, SCHEMA_VERSION, get_connection, initialize_database
from demo_seed import DEMO_PROTOCOL
from services import cce_service
from utils import format_cpf


ROOT = Path(__file__).resolve().parents[1]


def test_seed_has_at_least_twelve_unique_normalized_customers():
    cpfs = [cpf for cpf, _name in DEMO_CUSTOMERS]
    assert len(DEMO_CUSTOMERS) >= 12
    assert len(cpfs) == len(set(cpfs))
    assert all(len(cpf) == 11 and cpf.isdigit() for cpf in cpfs)
    assert dict(DEMO_CUSTOMERS)["12345678900"] == "Lucas de Alencar"
    assert all(len(DEMO_PHONES[cpf]) == 11 for cpf in cpfs)


def test_seed_is_idempotent():
    initialize_database()
    initialize_database()
    with get_connection() as connection:
        rows = connection.execute("SELECT cpf, name FROM customers").fetchall()
    assert len(rows) == len(DEMO_CUSTOMERS)
    assert len({row["cpf"] for row in rows}) == len(rows)


def test_demo_history_gives_every_channel_and_a_fixed_test_protocol(seeded_history):
    lucas = cce_service.find_case_by_protocol(DEMO_PROTOCOL)
    assert lucas["cpf"] == "12345678900"
    assert lucas["status"] == "SUSPENSA"
    interactions = cce_service.customer_overview("12345678900")["interactions"]
    assert {item["channel"] for item in interactions} == {"TELEFONE", "WHATSAPP", "MINHA_CLARO"}
    assert all(item["source"] == "DEMO" for item in interactions)
    assert cce_service.find_open_cases("98765432100") == []  # cliente reservado ao primeiro contato


def test_seeded_open_protocols_outlive_the_regular_context_window(seeded_history):
    """O histórico de demonstração não pode expirar com o TTL curto dos atendimentos reais."""
    from datetime import timedelta

    from utils import now_local, parse_datetime

    demo_case = cce_service.find_case_by_protocol(DEMO_PROTOCOL)
    regular_window = now_local() + timedelta(hours=settings.cce_ttl_hours)
    assert parse_datetime(demo_case["expires_at"]) > regular_window


def test_reset_recreates_history_while_clear_leaves_it_empty(seeded_history):
    cce_service.reset_demo(seed_history=False)
    with get_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM cce_sessions").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == len(DEMO_CUSTOMERS)
    cce_service.reset_demo(seed_history=True)
    assert cce_service.find_case_by_protocol(DEMO_PROTOCOL) is not None


def test_database_from_a_previous_version_is_migrated_and_seeded(tmp_path):
    legacy = tmp_path / "legacy.db"
    connection = sqlite3.connect(legacy)
    connection.executescript(
        """
        CREATE TABLE customers (cpf TEXT PRIMARY KEY, name TEXT NOT NULL);
        CREATE TABLE cce_sessions (id TEXT PRIMARY KEY, protocol TEXT, cpf TEXT, status TEXT);
        CREATE TABLE cce_events (id INTEGER PRIMARY KEY, session_id TEXT);
        INSERT INTO customers VALUES ('12345678900', 'Lucas de Alencar');
        INSERT INTO cce_sessions VALUES ('antigo', 'CCE-ABC12345', '12345678900', 'SUSPENSA');
        """
    )
    connection.commit()
    connection.close()

    original = settings.database_path
    object.__setattr__(settings, "database_path", legacy)
    try:
        initialize_database(seed_history=True)
        with get_connection() as migrated:
            assert migrated.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
            columns = {row["name"] for row in migrated.execute("PRAGMA table_info(cce_sessions)")}
            assert {"resolved_at", "assigned_agent"} <= columns
            assert migrated.execute("SELECT COUNT(*) FROM cce_sessions WHERE id = 'antigo'").fetchone()[0] == 0
            assert migrated.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == len(DEMO_CUSTOMERS)
        assert cce_service.find_case_by_protocol(DEMO_PROTOCOL) is not None
    finally:
        object.__setattr__(settings, "database_path", original)


def test_quick_guide_lists_exact_seed_customers_and_the_demo_script():
    guide = (ROOT / "LEIA_PRIMEIRO.txt").read_text(encoding="utf-8")
    for cpf, name in DEMO_CUSTOMERS:
        assert f"{format_cpf(cpf)} - {name}" in guide
    listed = re.findall(r"^\d{3}\.\d{3}\.\d{3}-\d{2} - ", guide, re.MULTILINE)
    assert len(listed) == len(DEMO_CUSTOMERS)
    assert f"protocolo {DEMO_PROTOCOL}" in guide
    assert "987.654.321-00" in guide


def test_technical_documentation_has_required_sections():
    documentation = (ROOT / "DOCUMENTACAO_TECNICA.txt").read_text(encoding="utf-8")
    for section in range(1, 17):
        assert f"{section}. " in documentation
    assert "OUTROS -> OUTROS" in documentation
    assert "TV -> SUPORTE_TV" in documentation
    assert "whisper-large-v3-turbo" in documentation
    assert "openai/gpt-oss-20b" in documentation
    assert "X-Channel-Token" in documentation


def test_readme_documents_the_security_measures():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for topic in ("SMS", "Prompt injection", "mascarad", "TRIAGE_MINUTES_ESTIMATE"):
        assert topic in readme


def test_example_environment_documents_every_setting():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    for key in ("GROQ_API_KEY", "SMS_PROVIDER", "CHANNEL_ACCESS_MINUTES", "TRIAGE_MINUTES_ESTIMATE", "CCE_TTL_HOURS"):
        assert f"{key}=" in example


def test_start_script_rejects_the_placeholder_key():
    script = (ROOT / "INICIAR_CLARO_ONE.bat").read_text(encoding="utf-8")
    placeholder = (ROOT / ".env.example").read_text(encoding="utf-8")
    token = re.search(r"GROQ_API_KEY=(\S+)", placeholder).group(1).lower()
    prefixes = re.search(r"k\.startswith\(\((.*?)\)\)", script).group(1)
    assert any(token.startswith(prefix.strip().strip("'")) for prefix in prefixes.split(","))
