"""Azure SDK 1.0.2 adapter with bounded polling and preserved evidence."""

from time import monotonic
from typing import Any

from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.core.polling.base_polling import LROBasePolling

from config.settings import Settings, get_settings
from services.provider_errors import FailureCode, ProviderFailure, classify_failure


class DeadlinePolling(LROBasePolling):
    """Stop polling, including Retry-After sleeps, at the attempt deadline."""

    def __init__(self, deadline):
        super().__init__(timeout=1, retry_total=0, logging_enable=False)
        self.deadline = deadline

    def remaining(self):
        remaining = self.deadline - monotonic()
        if remaining <= 0:
            raise TimeoutError("OCR polling deadline reached")
        return remaining

    def _sleep(self, delay):
        super()._sleep(min(delay, self.remaining()))
        self.remaining()

    def request_status(self, status_link):
        remaining = self.remaining()
        self._operation_config.update(
            connection_timeout=remaining / 2, read_timeout=remaining / 2, retry_total=0
        )
        return super().request_status(status_link)


def extract_document_from_azure(
    file_path: str, *, settings: Settings | None = None, client=None
) -> dict[str, Any]:
    settings = settings or get_settings()
    owned = client is None
    failure = None
    try:
        if owned:
            endpoint, key = settings.require_azure()
            client = DocumentIntelligenceClient(
                endpoint=endpoint,
                credential=AzureKeyCredential(key),
                connection_timeout=settings.provider_timeout_seconds / 2,
                read_timeout=settings.provider_timeout_seconds / 2,
                retry_total=0,
                logging_enable=False,
            )
        deadline = monotonic() + settings.provider_timeout_seconds
        try:
            stream = open(file_path, "rb")
        except OSError:
            raise ProviderFailure("ocr", FailureCode.DOCUMENT_READ) from None
        with stream:
            poller = client.begin_analyze_document(
                settings.azure_document_model,
                body=stream,
                content_type="application/octet-stream",
                features=["keyValuePairs"]
                if settings.azure_document_model == "prebuilt-layout"
                else None,
                polling=DeadlinePolling(deadline),
                connection_timeout=settings.provider_timeout_seconds / 2,
                read_timeout=settings.provider_timeout_seconds / 2,
                retry_total=0,
                logging_enable=False,
            )
        # The deadline polling method bounds retries/sleeps rather than abandoning
        # a default SDK polling thread with result(timeout=...).
        result = poller.result()
        if result is None or not isinstance(result.content, str) or not result.content.strip():
            raise ProviderFailure("ocr", FailureCode.EMPTY_OCR)
        evidence = result.as_dict()
        if not isinstance(evidence, dict):
            raise ProviderFailure("ocr", FailureCode.INVALID_RESPONSE)
        output = {
            "raw_text": result.content,
            "key_value_pairs": {
                kv.key.content: kv.value.content
                for kv in result.key_value_pairs or []
                if kv.key and kv.value
            },
            "tables": [
                [
                    {
                        "row_index": cell.row_index,
                        "column_index": cell.column_index,
                        "content": cell.content,
                    }
                    for cell in table.cells
                ]
                for table in result.tables or []
            ],
            "evidence": evidence,
        }
    except Exception as exc:
        failure = classify_failure(exc, "ocr")
    finally:
        if owned and client is not None:
            try:
                client.close()
            except Exception as exc:
                if failure is None:
                    failure = classify_failure(exc, "ocr")
    if failure is not None:
        raise failure  # Outside except: provider text is absent from the traceback chain.
    return output
