"""Unit tests never invoke external services or inherit real integration credentials."""

import socket

import pytest

from config.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_configuration(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def block_python_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("External Python network calls are forbidden in ordinary tests")

    # PostgreSQL integration uses psycopg/libpq and TEST_DATABASE_URL, not Python sockets.
    # Live provider tests must be explicitly opt-in and use a separate test configuration.
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
