from types import SimpleNamespace
from unittest.mock import mock_open, patch

import pytest

from config.settings import ConfigurationError, Settings
from extractors.azure_extractor import extract_document_from_azure


def test_extract_document_from_azure_success():
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_endpoint="https://synthetic.example.test",
        azure_document_intelligence_key="fake-key",
    )
    result = SimpleNamespace(
        content="Raw text content",
        key_value_pairs=[
            SimpleNamespace(
                key=SimpleNamespace(content="Name"),
                value=SimpleNamespace(content="Synthetic Patient"),
            )
        ],
        tables=[
            SimpleNamespace(cells=[SimpleNamespace(row_index=0, column_index=0, content="Header")])
        ],
    )
    with patch("extractors.azure_extractor.get_settings", return_value=settings):
        with patch("extractors.azure_extractor.DocumentIntelligenceClient") as client:
            client.return_value.begin_analyze_document.return_value.result.return_value = result
            with patch("builtins.open", mock_open(read_data=b"%PDF-synthetic")):
                extracted = extract_document_from_azure("dummy.pdf")
            assert extracted["raw_text"] == "Raw text content"
            assert extracted["key_value_pairs"] == {"Name": "Synthetic Patient"}
            assert extracted["tables"][0][0]["content"] == "Header"
            kwargs = client.return_value.begin_analyze_document.call_args.kwargs
            assert "body" in kwargs
            assert "analyze_request" not in kwargs


def test_extract_document_from_azure_missing_creds():
    with patch("extractors.azure_extractor.get_settings", return_value=Settings(_env_file=None)):
        with pytest.raises(ConfigurationError, match="AZURE_DOCUMENT_INTELLIGENCE"):
            extract_document_from_azure("dummy.pdf")
