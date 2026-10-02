"""Provider boundary contracts, using real SDK models and deterministic clients."""

import json
import traceback
from unittest.mock import Mock, patch

import httpx
import pytest
from azure.ai.documentintelligence.models import AnalyzeResult
from azure.core.exceptions import HttpResponseError
from langchain_core.messages import AIMessage, HumanMessage
from openai import APIConnectionError, APITimeoutError

from agents.extraction_agent import ExtractionAgent
from agents.graphs.extraction_graph import extraction_graph
from config.settings import Settings
from extractors.azure_extractor import DeadlinePolling, extract_document_from_azure
from services.provider_errors import FailureCode, ProviderFailure


@pytest.fixture
def document(tmp_path):
    path = tmp_path / "synthetic.pdf"
    path.write_bytes(b"%PDF-synthetic-only")
    return path


def azure_client(content="Synthetic Patient"):
    result = AnalyzeResult(
        {
            "apiVersion": "2024-11-30",
            "modelId": "prebuilt-layout",
            "content": content,
            "pages": [
                {
                    "pageNumber": 1,
                    "words": [
                        {
                            "content": "Synthetic",
                            "confidence": 0.91,
                            "span": {"offset": 0, "length": 9},
                            "polygon": [0, 0, 1, 0, 1, 1, 0, 1],
                        }
                    ],
                }
            ],
            "keyValuePairs": [
                {"key": {"content": "Name"}, "value": {"content": content}, "confidence": 0.82}
            ],
            "tables": [
                {
                    "rowCount": 1,
                    "columnCount": 1,
                    "cells": [{"rowIndex": 0, "columnIndex": 0, "content": "Header"}],
                }
            ],
        }
    )
    client = Mock()
    client.begin_analyze_document.return_value.result.return_value = result
    return client


def test_ocr_request_and_unmodified_evidence(document):
    client = azure_client()
    result = extract_document_from_azure(
        str(document), client=client, settings=Settings(_env_file=None)
    )
    args, kwargs = client.begin_analyze_document.call_args
    assert args == ("prebuilt-layout",)
    assert kwargs["body"].closed
    assert kwargs["content_type"] == "application/octet-stream"
    assert kwargs["features"] == ["keyValuePairs"]
    assert isinstance(kwargs["polling"], DeadlinePolling)
    assert kwargs["logging_enable"] is False
    assert result["key_value_pairs"] == {"Name": "Synthetic Patient"}
    assert result["tables"][0][0]["content"] == "Header"
    assert result["evidence"]["pages"][0]["words"][0]["confidence"] == 0.91
    assert result["evidence"]["keyValuePairs"][0]["confidence"] == 0.82
    assert "confidence" not in result
    client.close.assert_not_called()  # Caller owns injected clients.


def test_custom_ocr_model_does_not_request_layout_addon(document):
    client = azure_client()
    extract_document_from_azure(
        str(document),
        client=client,
        settings=Settings(_env_file=None, azure_document_model=" custom-synthetic "),
    )
    args, kwargs = client.begin_analyze_document.call_args
    assert args[0] == "custom-synthetic" and kwargs["features"] is None


@pytest.mark.parametrize("content", [None, "", "  "])
def test_empty_ocr_is_permanent_failure(document, content):
    with pytest.raises(ProviderFailure) as caught:
        extract_document_from_azure(str(document), client=azure_client(content))
    assert caught.value.code == FailureCode.EMPTY_OCR
    assert not caught.value.retryable


def test_deadline_polling_caps_sleep_and_stops_requests():
    polling = DeadlinePolling(10)
    with patch("extractors.azure_extractor.monotonic", side_effect=[9, 10]):
        with patch("azure.core.polling.base_polling.LROBasePolling._sleep") as sleep:
            with pytest.raises(TimeoutError):
                polling._sleep(3600)
    sleep.assert_called_once_with(1)
    with patch("extractors.azure_extractor.monotonic", return_value=10):
        with patch("azure.core.polling.base_polling.LROBasePolling.request_status") as request:
            with pytest.raises(TimeoutError):
                polling.request_status("https://synthetic.test/status")
            request.assert_not_called()


def test_polling_request_timeouts_follow_remaining_budget():
    polling = DeadlinePolling(10)
    with patch("extractors.azure_extractor.monotonic", return_value=6):
        with patch("azure.core.polling.base_polling.LROBasePolling.request_status"):
            polling.request_status("https://synthetic.test/status")
    assert polling._operation_config["connection_timeout"] == 2
    assert polling._operation_config["read_timeout"] == 2
    assert polling._operation_config["retry_total"] == 0


VALID = dict(
    patient_name="Synthetic Patient",
    patient_dob=None,
    provider_name=None,
    service_date="2025-01-01",
    total_amount="42.50",
    confidence=0.4,
    reasoning="Some fields are absent.",
)


def agent_for(response):
    client = Mock()
    client.invoke.return_value = response
    return ExtractionAgent(client=client, settings=Settings(_env_file=None)), client


def test_low_confidence_is_successful_typed_data_not_provider_failure():
    agent, client = agent_for(AIMessage(content=json.dumps(VALID)))
    assert agent.extract("Synthetic document") == VALID
    client.invoke.assert_called_once()


def test_text_blocks_supported():
    agent, _ = agent_for(AIMessage(content=[{"type": "text", "text": json.dumps(VALID)}]))
    assert agent.extract("Synthetic document") == VALID


@pytest.mark.parametrize(
    "output",
    [
        '{"confidence": 0.9',
        "not JSON",
        "[" * 1001 + "0" + "]" * 1001,
        "```json\n{}\n```",
        "[]",
        json.dumps({k: v for k, v in VALID.items() if k != "patient_dob"}),
        json.dumps({**VALID, "confidence": 1.1}),
        json.dumps({**VALID, "confidence": -0.1}),
        json.dumps({**VALID, "confidence": float("nan")}),
        json.dumps({**VALID, "confidence": float("inf")}),
        json.dumps({**VALID, "confidence": "0.9"}),
        json.dumps({**VALID, "confidence": True}),
        json.dumps({**VALID, "reasoning": "  "}),
        json.dumps({**VALID, "extra": "unexpected"}),
        json.dumps({**VALID, "total_amount": float("inf")}),
        json.dumps({**VALID, "patient_name": {"nested": "invalid"}}),
        json.dumps(VALID)[:-1] + ', "confidence": 0.9}',
    ],
)
def test_malformed_structured_output_is_permanent_failure(output):
    agent, _ = agent_for(output)
    with pytest.raises(ProviderFailure) as caught:
        agent.extract("Synthetic document")
    assert caught.value.code == FailureCode.INVALID_RESPONSE
    assert not caught.value.retryable
    assert caught.value.__context__ is None


@pytest.mark.parametrize("text", [None, "", " \n", "x" * 200_001])
def test_empty_or_unbounded_input_never_calls_provider(text):
    agent, client = agent_for(json.dumps(VALID))
    with pytest.raises(ProviderFailure):
        agent.extract(text)
    client.invoke.assert_not_called()


def provider_error(status):
    response = Mock(status_code=status, headers={"Retry-After": "9999"})
    return HttpResponseError(message="synthetic-private-key-and-content", response=response)


@pytest.mark.parametrize(
    "error,code,retryable",
    [
        (TimeoutError("synthetic-private-key-and-content"), FailureCode.TIMEOUT, True),
        (httpx.ReadTimeout("synthetic-private-key-and-content"), FailureCode.TIMEOUT, True),
        (
            APITimeoutError(request=httpx.Request("GET", "https://synthetic.test")),
            FailureCode.TIMEOUT,
            True,
        ),
        (
            APIConnectionError(request=httpx.Request("GET", "https://synthetic.test")),
            FailureCode.UNAVAILABLE,
            True,
        ),
        (provider_error(429), FailureCode.RATE_LIMITED, True),
        (provider_error(503), FailureCode.UNAVAILABLE, True),
        (provider_error(401), FailureCode.REJECTED, False),
    ],
)
@pytest.mark.parametrize("stage", ["ocr", "extraction"])
def test_provider_failures_safe_and_attempted_once(document, error, code, retryable, stage):
    client = azure_client() if stage == "ocr" else Mock()
    call = client.begin_analyze_document if stage == "ocr" else client.invoke
    call.side_effect = error
    with pytest.raises(ProviderFailure) as caught:
        if stage == "ocr":
            extract_document_from_azure(str(document), client=client)
        else:
            ExtractionAgent(client=client).extract("Synthetic document")
    call.assert_called_once()
    failure = caught.value
    assert failure.code == code and failure.retryable == retryable
    assert failure.retry_after == (60 if code == FailureCode.RATE_LIMITED else None)
    assert "synthetic-private" not in "".join(traceback.format_exception(failure))
    assert failure.__context__ is None


def test_wrapped_google_error_preserves_classification():
    wrapped = RuntimeError("synthetic private details")
    wrapped.__cause__ = provider_error(429)
    agent, client = agent_for("")
    client.invoke.side_effect = wrapped
    with pytest.raises(ProviderFailure) as caught:
        agent.extract("Synthetic")
    assert caught.value.code == FailureCode.RATE_LIMITED


def test_missing_configuration_is_typed_failure(document):
    with pytest.raises(ProviderFailure) as caught:
        extract_document_from_azure(str(document), settings=Settings(_env_file=None))
    assert caught.value.code == FailureCode.CONFIGURATION
    with pytest.raises(ProviderFailure) as caught:
        ExtractionAgent(settings=Settings(_env_file=None)).extract("Synthetic")
    assert caught.value.code == FailureCode.CONFIGURATION


def test_graph_propagates_failure_without_review_or_approval():
    with patch(
        "agents.graphs.extraction_graph.extract_document_from_azure",
        return_value={"raw_text": "Synthetic"},
    ):
        with patch("agents.graphs.extraction_graph.ExtractionAgent") as cls:
            cls.return_value.extract.side_effect = ProviderFailure(
                "extraction", FailureCode.INVALID_RESPONSE
            )
            with pytest.raises(ProviderFailure):
                extraction_graph.invoke({"document_path": "synthetic.pdf"})


def test_pinned_google_sdk_receives_zero_retry_and_timeout_options():
    # Real request construction, fake underlying SDK: no account/network involved.
    from langchain_google_genai import ChatGoogleGenerativeAI

    with patch("langchain_google_genai.chat_models.Client"):
        client = ChatGoogleGenerativeAI(
            model="synthetic-model", api_key="fake", timeout=2, max_retries=0, max_tokens=2048
        )
        request = client._prepare_request([HumanMessage("Synthetic")])
    assert request["config"].http_options.timeout == 2000
    assert request["config"].http_options.retry_options.attempts == 0
    assert request["config"].max_output_tokens == 2048


@pytest.mark.parametrize("running", [False, True])
def test_real_pinned_azure_sdk_serializes_and_polls_document(document, monkeypatch, running):
    from azure.ai.documentintelligence import DocumentIntelligenceClient
    from azure.core.credentials import AzureKeyCredential
    from azure.core.pipeline.transport import RequestsTransport
    from requests import Response

    requests = []
    session = Mock()
    elapsed = [0.0]
    if running:
        monkeypatch.setattr("extractors.azure_extractor.monotonic", lambda: elapsed[0])
        monkeypatch.setattr(
            "azure.core.polling.base_polling.LROBasePolling._sleep",
            lambda self, delay: elapsed.__setitem__(0, elapsed[0] + delay),
        )

    def request(method, url, **kwargs):
        body = kwargs.get("data")
        requests.append((method, url, body.read() if hasattr(body, "read") else body, kwargs))
        response = Response()
        response.raw = Mock()
        response._content_consumed = True
        response.status_code = 202 if method == "POST" else 200
        response.headers["Content-Type"] = "application/json"
        if running:
            response.headers["Retry-After"] = "3600"
        if method == "POST":
            response.headers["Operation-Location"] = "https://synthetic.test/operations/one"
            response._content = b"{}"
        else:
            response._content = json.dumps(
                {
                    "status": "running" if running else "succeeded",
                    "analyzeResult": {
                        "apiVersion": "2024-11-30",
                        "modelId": "prebuilt-layout",
                        "content": "Synthetic Patient",
                        "pages": [],
                    },
                }
            ).encode()
        return response

    session.request.side_effect = request
    client = DocumentIntelligenceClient(
        "https://synthetic.test",
        AzureKeyCredential("fake"),
        transport=RequestsTransport(session=session, session_owner=False),
        retry_total=0,
    )
    try:
        if running:
            with pytest.raises(ProviderFailure) as caught:
                extract_document_from_azure(
                    str(document),
                    client=client,
                    settings=Settings(_env_file=None, provider_timeout_seconds=2),
                )
            assert caught.value.code == FailureCode.TIMEOUT
            assert elapsed[0] == 2
        else:
            result = extract_document_from_azure(
                str(document), client=client, settings=Settings(_env_file=None)
            )
            assert result["raw_text"] == "Synthetic Patient"
    finally:
        client.close()
    assert len(requests) == 2
    method, url, body, kwargs = requests[0]
    assert method == "POST" and body == b"%PDF-synthetic-only"
    assert "/documentModels/prebuilt-layout:analyze" in url
    assert "features=keyValuePairs" in url and "api-version=2024-11-30" in url
    assert kwargs["headers"]["Content-Type"] == "application/octet-stream"
    assert requests[1][0] == "GET"


def test_live_smoke_requires_explicit_opt_in(monkeypatch):
    from scripts.smoke_providers import main

    monkeypatch.setattr("sys.argv", ["smoke_providers"])
    with patch("scripts.smoke_providers.extract_document_from_azure") as azure:
        with pytest.raises(SystemExit) as caught:
            main()
    assert caught.value.code == 2
    azure.assert_not_called()


def test_injected_llm_is_not_closed_by_adapter():
    agent, client = agent_for(json.dumps(VALID))
    agent.extract("Synthetic")
    agent.close()
    client.close.assert_not_called()


def test_owned_llm_is_closed_and_can_be_recreated():
    with patch("agents.extraction_agent.ChatOpenAI") as cls:
        agent = ExtractionAgent(
            provider="openai",
            settings=Settings(_env_file=None, llm_model="synthetic", openai_api_key="fake"),
        )
        agent.llm
        agent.close()
        cls.return_value.root_client.close.assert_called_once()
        agent.llm
        assert cls.call_count == 2
