import json
from decimal import Decimal
from functools import cached_property
from typing import Literal

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    ValidationError,
    field_serializer,
    field_validator,
)

from config.settings import Settings, get_settings
from services.provider_errors import FailureCode, ProviderFailure, classify_failure


def unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = float(value) if key == "confidence" and isinstance(value, Decimal) else value
    return result


class ExtractedData(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)

    patient_name: str | None = Field(max_length=225)
    patient_dob: str | None = Field(max_length=32)
    provider_name: str | None = Field(max_length=225)
    service_date: str | None = Field(max_length=32)
    total_amount: str | Decimal | None = Field(description="Raw amount; normalization runs later")
    confidence: StrictFloat = Field(ge=0, le=1, allow_inf_nan=False)
    reasoning: str = Field(min_length=1, max_length=2000)

    @field_validator("total_amount")
    @classmethod
    def bounded_amount(cls, value):
        if isinstance(value, str) and len(value) > 64:
            raise ValueError("Amount text is too long")
        if isinstance(value, Decimal) and not value.is_finite():
            raise ValueError("Amount must be finite")
        if isinstance(value, Decimal):
            if abs(value.adjusted()) > 64 or value.as_tuple().exponent < -64:
                raise ValueError("Amount exceeds supported precision")
            if len(format(value, "f")) > 64:
                raise ValueError("Amount text is too long")
        return value

    @field_serializer("total_amount", when_used="json")
    def decimal_amount_text(self, value):
        return format(value, "f") if isinstance(value, Decimal) else value


class ExtractionAgent:
    def __init__(
        self,
        provider: Literal["openai", "google"] | None = None,
        model_name: str | None = None,
        settings: Settings | None = None,
        client=None,
    ):
        self.settings = settings or get_settings()
        self.provider = provider or self.settings.llm_provider
        self.model_name = model_name
        self._client = client
        if self.provider not in {"openai", "google"}:
            raise ValueError(f"Unsupported provider: {self.provider}")

        self.parser = PydanticOutputParser(pydantic_object=ExtractedData)

        self.prompt = ChatPromptTemplate.from_messages(
            [
                (
                    "system",
                    "You are an AI agent responsible for extracting structured data from healthcare claim documents.\n\n"
                    "Your task is to extract the following fields and return ONLY valid JSON:\n"
                    "- patient_name (string or null)\n"
                    "- patient_dob (string or null)\n"
                    "- provider_name (string or null)\n"
                    "- service_date (ISO date string or null)\n"
                    "- total_amount (number or null)\n"
                    "- confidence (number between 0 and 1)\n"
                    "- reasoning (short explanation of extraction quality)\n\n"
                    "Rules:\n"
                    "- Do NOT guess missing values.\n"
                    "- If a field is not explicitly present, return null.\n"
                    "- Base all outputs strictly on the provided text.\n"
                    "- If the document is unclear or incomplete, lower the confidence score and explain why.\n\n"
                    "Healthcare claims typically include patient details, provider information, dates of service, and billed amounts.\n\n"
                    "{format_instructions}",
                ),
                ("user", "Document text:\n{raw_text}"),
            ]
        )

    @cached_property
    def llm(self):
        if self._client is not None:
            return self._client
        model, key = self.settings.require_llm(self.provider, self.model_name)
        options = {
            "model": model,
            "temperature": 0,
            "api_key": key,
            "timeout": self.settings.provider_timeout_seconds,
            "max_retries": 0,
            "max_tokens": 2048,
        }
        if self.provider == "openai":
            return ChatOpenAI(**options)
        return ChatGoogleGenerativeAI(**options)

    def close(self):
        """Close only adapter-owned clients; injected clients belong to the caller."""
        llm = self.__dict__.pop("llm", None)
        if llm is not None and self._client is None:
            client = llm.root_client if self.provider == "openai" else llm.client
            failure = None
            try:
                client.close()
            except Exception as exc:
                failure = classify_failure(exc, "extraction")
            if failure is not None:
                raise failure

    def extract(self, document_text: str) -> dict:
        if not isinstance(document_text, str) or not document_text.strip():
            raise ProviderFailure("extraction", FailureCode.EMPTY_INPUT)
        if len(document_text) > 200_000:
            raise ProviderFailure("extraction", FailureCode.INVALID_RESPONSE)
        failure = None
        try:
            prompt = self.prompt.invoke(
                {
                    "raw_text": document_text,
                    "format_instructions": self.parser.get_format_instructions(),
                }
            )
            response = self.llm.invoke(prompt)
        except Exception as exc:
            failure = classify_failure(exc, "extraction")
        if failure is not None:
            raise failure
        try:
            content = response if isinstance(response, str) else response.text
            # JSON must be complete. LangChain's partial-JSON parser can repair
            # truncated output, which is not a successful structured extraction.
            if not isinstance(content, str) or len(content) > 32_768:
                raise ValueError("Invalid response content")
            data = json.loads(
                content, parse_float=Decimal, parse_int=Decimal, object_pairs_hook=unique_fields
            )
            return ExtractedData.model_validate(data).model_dump(mode="json")
        except (ValueError, TypeError, AttributeError, ValidationError, RecursionError):
            failure = ProviderFailure("extraction", FailureCode.INVALID_RESPONSE)
        raise failure
