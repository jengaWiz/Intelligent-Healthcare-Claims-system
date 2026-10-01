"""Configuration boundaries must stay credential-free until integration starts."""

import subprocess
import sys
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from config.settings import ConfigurationError, Settings


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for field in Settings.model_fields:
        monkeypatch.delenv(field.upper(), raising=False)


def settings(**values):
    return Settings(_env_file=None, **values)


def test_optional_credentials_and_secret_redaction():
    value = settings(google_api_key="unit-test-secret", database_url="postgresql+psycopg://secret")
    assert "unit-test-secret" not in repr(value)
    assert "postgresql+psycopg://secret" not in repr(value)
    assert settings().google_api_key is None


def test_dotenv_and_environment_precedence(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("MAX_UPLOAD_BYTES=2048\nLLM_MODEL=synthetic-model\n")
    monkeypatch.setenv("MAX_UPLOAD_BYTES", "4096")
    value = Settings(_env_file=env)
    assert value.max_upload_bytes == 4096
    assert value.llm_model == "synthetic-model"


def test_example_config_loads_without_credentials():
    value = Settings(_env_file=".env.example")
    assert value.database_url is None
    assert value.llm_model is None
    assert value.max_upload_bytes == 10485760


@pytest.mark.parametrize(
    "values",
    [
        {"extraction_confidence_threshold": 1.1},
        {"extraction_confidence_threshold": float("nan")},
        {"max_upload_bytes": 0},
        {"provider_timeout_seconds": 0},
        {"job_max_attempts": 0},
        {"job_lease_seconds": 30},
        {"allowed_origins": ["*"]},
        {"allowed_origins": ["https://example.test/path"]},
        {"azure_document_intelligence_endpoint": "http://example.test"},
        {"llm_provider": "unsupported"},
    ],
)
def test_invalid_configuration_is_rejected(values):
    with pytest.raises(ValidationError):
        settings(**values)


def test_integration_credentials_fail_at_boundary():
    value = settings()
    with pytest.raises(ConfigurationError, match="DATABASE_URL"):
        value.require_database_url()
    with pytest.raises(ConfigurationError, match="AZURE_DOCUMENT_INTELLIGENCE"):
        value.require_azure()
    with pytest.raises(ConfigurationError, match="LLM_MODEL"):
        value.require_llm()
    with pytest.raises(ConfigurationError, match="GOOGLE_API_KEY"):
        settings(llm_model="synthetic-model").require_llm()
    with pytest.raises(ConfigurationError, match="postgresql\\+psycopg"):
        settings(database_url="sqlite:///test.db").require_database_url()


def test_provider_selection_requires_only_selected_key():
    value = settings(llm_provider="openai", llm_model="synthetic-model", openai_api_key="fake")
    assert value.require_llm() == ("synthetic-model", "fake")
    with pytest.raises(ConfigurationError, match="GOOGLE_API_KEY"):
        value.require_llm("google")


def test_agents_construct_without_provider_clients():
    from agents.extraction_agent import ExtractionAgent
    from agents.validation_agent import ValidationAgent

    with patch("agents.extraction_agent.ChatGoogleGenerativeAI") as extraction_client:
        with patch("agents.validation_agent.ChatGoogleGenerativeAI") as validation_client:
            ExtractionAgent(settings=settings())
            ValidationAgent(settings=settings())
            extraction_client.assert_not_called()
            validation_client.assert_not_called()


def test_imports_do_not_create_resources(tmp_path):
    script = """
import socket
from unittest.mock import patch
with patch.object(socket.socket, 'connect', side_effect=AssertionError('network access')):
    import config.settings
    import database.session
    import services.storage_service
    import agents.graphs.extraction_graph
"""
    # A separate interpreter catches accidental side effects hidden by import caches.
    import os
    from pathlib import Path

    env = {
        k: v
        for k, v in os.environ.items()
        if k.upper() not in {name.upper() for name in Settings.model_fields}
    }
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    result = subprocess.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / "uploads").exists()
