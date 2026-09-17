from __future__ import annotations

import httpx
import pytest

from config import settings
from services import sms_service


@pytest.fixture
def twilio_settings():
    overrides = {
        "sms_provider": "twilio",
        "twilio_account_sid": "AC123",
        "twilio_auth_token": "token",
        "twilio_from_number": "+15550000000",
        "sms_test_destination": "11999999999",
    }
    originals = {key: getattr(settings, key) for key in overrides}
    for key, value in overrides.items():
        object.__setattr__(settings, key, value)
    yield
    for key, value in originals.items():
        object.__setattr__(settings, key, value)


def test_simulated_provider_reveals_the_code_for_the_demo():
    delivery = sms_service.send_verification_code("123456")
    assert delivery.mode == "SIMULADO"
    assert delivery.reveal_code is True


def test_twilio_sends_to_the_configured_number_without_revealing_the_code(monkeypatch, twilio_settings):
    captured = {}

    def fake_post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(201, request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", fake_post)
    delivery = sms_service.send_verification_code("482913")
    assert delivery.mode == "REAL"
    assert delivery.reveal_code is False
    assert captured["url"].endswith("/Accounts/AC123/Messages.json")
    assert captured["data"]["To"] == "+5511999999999"
    assert "482913" in captured["data"]["Body"]


def test_twilio_failure_falls_back_to_the_simulated_mode(monkeypatch, twilio_settings):
    def failing_post(url, **_kwargs):
        raise httpx.ConnectError("sem rede", request=httpx.Request("POST", url))

    monkeypatch.setattr(httpx, "post", failing_post)
    delivery = sms_service.send_verification_code("482913")
    assert delivery.mode == "SIMULADO"
    assert delivery.reveal_code is True
    assert "falhou" in delivery.notice


def test_missing_twilio_configuration_falls_back(monkeypatch):
    object.__setattr__(settings, "sms_provider", "twilio")
    monkeypatch.setattr(httpx, "post", lambda *_args, **_kwargs: pytest.fail("não deveria chamar a API"))
    try:
        delivery = sms_service.send_verification_code("482913")
    finally:
        object.__setattr__(settings, "sms_provider", "simulado")
    assert delivery.mode == "SIMULADO"
