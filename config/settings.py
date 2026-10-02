"""Validated configuration with credentials checked at integration boundaries."""

from functools import lru_cache
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigurationError(ValueError):
    """A safe, actionable configuration error without credential values."""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="forbid", hide_input_in_errors=True
    )

    database_timeout_seconds: int = Field(default=3, ge=1, le=10)
    database_url: SecretStr | None = None
    azure_document_intelligence_endpoint: str | None = None
    azure_document_intelligence_key: SecretStr | None = None
    azure_document_model: str = "prebuilt-layout"
    llm_provider: Literal["google", "openai"] = "google"
    llm_model: str | None = None
    google_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    api_auth_token: SecretStr | None = None
    allowed_origins: list[str] = Field(default_factory=list)
    upload_dir: Path = Path("uploads")
    max_upload_bytes: int = Field(default=10 * 1024 * 1024, ge=1, le=100 * 1024 * 1024)
    extraction_confidence_threshold: float = Field(default=0.8, ge=0, le=1, allow_inf_nan=False)
    provider_timeout_seconds: float = Field(default=30, gt=0, le=120, allow_inf_nan=False)
    job_max_attempts: int = Field(default=3, ge=1, le=10)
    job_lease_seconds: int = Field(default=120, ge=10, le=600)
    job_heartbeat_seconds: int = Field(default=20, ge=1, le=60)
    worker_poll_seconds: float = Field(default=1, gt=0, le=30, allow_inf_nan=False)

    @field_validator(
        "database_url",
        "azure_document_intelligence_endpoint",
        "azure_document_intelligence_key",
        "llm_model",
        "google_api_key",
        "openai_api_key",
        "api_auth_token",
        mode="before",
    )
    @classmethod
    def empty_as_unset(cls, value):
        return None if isinstance(value, str) and not value.strip() else value

    @field_validator("azure_document_intelligence_endpoint")
    @classmethod
    def validate_azure_endpoint(cls, value):
        if value is not None:
            parsed = urlparse(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                raise ValueError("Azure endpoint must be an HTTPS URL without embedded credentials")
        return value

    @field_validator("azure_document_model")
    @classmethod
    def nonempty_model(cls, value):
        if not value.strip():
            raise ValueError("Azure document model must not be empty")
        return value

    @field_validator("allowed_origins")
    @classmethod
    def explicit_origins(cls, values):
        for value in values:
            parsed = urlparse(value)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
                or "*" in value
            ):
                raise ValueError("Allowed origins must be explicit HTTP(S) origins")
        return values

    @model_validator(mode="after")
    def lease_bounds(self):
        if self.job_heartbeat_seconds * 2 >= self.job_lease_seconds:
            raise ValueError("Job lease must exceed two heartbeat intervals")
        if self.provider_timeout_seconds >= self.job_lease_seconds:
            raise ValueError("Provider timeout must be shorter than job lease")
        return self

    def require_database_url(self) -> str:
        if self.database_url is None:
            raise ConfigurationError("Set DATABASE_URL before starting database integrations")
        value = self.database_url.get_secret_value()
        if not value.startswith("postgresql+psycopg://"):
            raise ConfigurationError("DATABASE_URL must use the postgresql+psycopg driver")
        return value

    def require_azure(self) -> tuple[str, str]:
        if (
            not self.azure_document_intelligence_endpoint
            or not self.azure_document_intelligence_key
        ):
            raise ConfigurationError(
                "Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY"
            )
        return (
            self.azure_document_intelligence_endpoint,
            self.azure_document_intelligence_key.get_secret_value(),
        )

    def require_llm(self, provider: str | None = None, model: str | None = None) -> tuple[str, str]:
        provider = provider or self.llm_provider
        if provider not in {"google", "openai"}:
            raise ConfigurationError("LLM_PROVIDER must be google or openai")
        selected_model = model or self.llm_model
        if not selected_model or not selected_model.strip():
            raise ConfigurationError("Set LLM_MODEL to a model available to your provider account")
        key = self.google_api_key if provider == "google" else self.openai_api_key
        if key is None:
            variable = "GOOGLE_API_KEY" if provider == "google" else "OPENAI_API_KEY"
            raise ConfigurationError(f"Set {variable} before starting {provider} integrations")
        return selected_model, key.get_secret_value()


@lru_cache
def get_settings() -> Settings:
    return Settings()
