from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from database import initialize_database


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path):
    """Cada teste usa banco e uploads próprios, com IA e SMS em modo determinístico."""
    uploads = tmp_path / "uploads"
    uploads.mkdir()
    overrides = {
        "database_path": tmp_path / "test.db",
        "upload_dir": uploads,
        "demo_fallback": False,
        "sms_provider": "simulado",
    }
    originals = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        object.__setattr__(settings, key, value)
    initialize_database()
    yield
    for key, value in originals.items():
        object.__setattr__(settings, key, value)


@pytest.fixture
def seeded_history():
    from demo_seed import seed_demo_history

    seed_demo_history()
