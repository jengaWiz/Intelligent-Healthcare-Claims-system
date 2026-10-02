"""
Canonical Claim Schema - Normalized representation of healthcare claim data.

This module provides a consistent, structured format for claim data that will be used
by the multi-agent system. It transforms raw extracted data into normalized fields
suitable for downstream processing, validation, and decision-making.
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ClaimStatus(str, Enum):
    """Possible statuses for a claim."""

    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    PENDING_INFO = "PENDING_INFO"


class PatientInfo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    """Normalized patient information."""

    full_name: Optional[str] = Field(None, description="Patient's full name")
    date_of_birth: Optional[date] = Field(None, description="Patient's date of birth")
    patient_id: Optional[str] = Field(None, description="Patient identifier/member ID")

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def parse_date(cls, v):
        """Parse date from various formats."""
        if isinstance(v, datetime):
            return v.date()
        if v is None or isinstance(v, date):
            return v
        if isinstance(v, str):
            # Try common date formats
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
        return None


class ProviderInfo(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    """Normalized provider information."""

    name: Optional[str] = Field(None, description="Provider or facility name")
    provider_id: Optional[str] = Field(None, description="Provider NPI or identifier")
    address: Optional[str] = Field(None, description="Provider address")
    specialty: Optional[str] = Field(None, description="Provider specialty")


class ServiceInfo(BaseModel):
    """Normalized service information."""

    service_date: Optional[date] = Field(None, description="Date of service")
    service_code: Optional[str] = Field(None, description="CPT/HCPCS code")
    service_description: Optional[str] = Field(None, description="Description of service")
    diagnosis_codes: Optional[List[str]] = Field(
        default_factory=list, description="ICD-10 diagnosis codes"
    )

    @field_validator("service_date", mode="before")
    @classmethod
    def parse_date(cls, v):
        """Parse date from various formats."""
        if isinstance(v, datetime):
            return v.date()
        if v is None or isinstance(v, date):
            return v
        if isinstance(v, str):
            for fmt in ["%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"]:
                try:
                    return datetime.strptime(v, fmt).date()
                except ValueError:
                    continue
        return None


class BillingInfo(BaseModel):
    """Normalized billing information."""

    total_amount: Optional[Decimal] = Field(None, description="Total billed amount")
    currency: str = Field("USD", description="Currency code")
    line_items: Optional[List[dict]] = Field(
        default_factory=list, description="Individual line items"
    )

    @field_validator("total_amount", mode="before")
    @classmethod
    def parse_amount(cls, v):
        """Parse amount from string, removing currency symbols."""
        if v is None or isinstance(v, bool):
            return None
        if isinstance(v, (Decimal, int, float)):
            amount = Decimal(str(v))
        elif isinstance(v, str):
            cleaned = v.strip()
            cleaned = re.sub(r"^(?:USD\s*|\$\s*)", "", cleaned, flags=re.IGNORECASE)
            if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d+)?", cleaned):
                return None
            try:
                amount = Decimal(cleaned.replace(",", ""))
            except InvalidOperation:
                return None
        else:
            return None
        return amount if amount.is_finite() else None

    @field_validator("currency", mode="before")
    @classmethod
    def normalize_currency(cls, value):
        if not isinstance(value, str) or value.strip().upper() != "USD":
            raise ValueError("M1 supports USD only")
        return "USD"


class ClaimData(BaseModel):
    """
    Canonical claim data schema.

    This represents the normalized, structured claim information extracted from
    raw documents. It serves as the single source of truth for claim data across
    the multi-agent system.
    """

    # Core identifiers
    claim_id: Optional[str] = Field(None, description="Internal claim identifier")
    external_claim_id: Optional[str] = Field(None, description="External/payer claim number")

    # Structured components
    patient: PatientInfo = Field(default_factory=PatientInfo, description="Patient information")
    provider: ProviderInfo = Field(default_factory=ProviderInfo, description="Provider information")
    service: ServiceInfo = Field(default_factory=ServiceInfo, description="Service information")
    billing: BillingInfo = Field(default_factory=BillingInfo, description="Billing information")

    # Metadata
    status: ClaimStatus = Field(ClaimStatus.DRAFT, description="Current claim status")
    submission_date: Optional[date] = Field(None, description="Date claim was submitted")

    # Extraction metadata
    extraction_confidence: Optional[float] = Field(
        None, ge=0, le=1, allow_inf_nan=False, description="Model-reported extraction confidence"
    )
    extraction_notes: Optional[str] = Field(None, description="Notes from extraction process")

    model_config = ConfigDict(use_enum_values=True)

    @classmethod
    def from_extracted_data(cls, extracted: dict) -> "ClaimData":
        """
        Create ClaimData from raw extracted data.

        Args:
            extracted: Dictionary from extraction agent (ExtractedData)

        Returns:
            ClaimData instance with normalized fields
        """
        return cls(
            patient=PatientInfo(
                full_name=extracted.get("patient_name"), date_of_birth=extracted.get("patient_dob")
            ),
            provider=ProviderInfo(name=extracted.get("provider_name")),
            service=ServiceInfo(service_date=extracted.get("service_date")),
            billing=BillingInfo(total_amount=extracted.get("total_amount")),
            extraction_confidence=extracted.get("confidence"),
            extraction_notes=extracted.get("reasoning"),
        )
