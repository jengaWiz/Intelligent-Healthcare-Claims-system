import pytest
from datetime import date
from decimal import Decimal
from models.claim_data import (
    ClaimData, 
    PatientInfo, 
    ProviderInfo, 
    ServiceInfo, 
    BillingInfo,
    ClaimStatus
)


def test_patient_info_date_parsing():
    """Test patient date of birth parsing from various formats."""
    # ISO format
    patient1 = PatientInfo(full_name="John Doe", date_of_birth="1980-01-15")
    assert patient1.date_of_birth == date(1980, 1, 15)
    
    # US format
    patient2 = PatientInfo(full_name="Jane Doe", date_of_birth="01/15/1980")
    assert patient2.date_of_birth == date(1980, 1, 15)
    
    # Invalid format
    patient3 = PatientInfo(full_name="Bob Doe", date_of_birth="invalid")
    assert patient3.date_of_birth is None


def test_billing_info_amount_parsing():
    """Test billing amount parsing from various formats."""
    # String with dollar sign
    billing1 = BillingInfo(total_amount="$150.00")
    assert billing1.total_amount == Decimal("150.00")
    
    # String with comma
    billing2 = BillingInfo(total_amount="1,500.50")
    assert billing2.total_amount == Decimal("1500.50")
    
    # Numeric
    billing3 = BillingInfo(total_amount=250.75)
    assert billing3.total_amount == Decimal("250.75")
    
    # Invalid
    billing4 = BillingInfo(total_amount="invalid")
    assert billing4.total_amount is None


def test_claim_data_from_extracted_data():
    """Test creating ClaimData from extracted data."""
    extracted = {
        "patient_name": "John Doe",
        "patient_dob": "1980-01-15",
        "provider_name": "Dr. Smith",
        "service_date": "2023-10-27",
        "total_amount": "$150.00",
        "confidence": 0.95,
        "reasoning": "All fields clearly visible"
    }
    
    claim = ClaimData.from_extracted_data(extracted)
    
    assert claim.patient.full_name == "John Doe"
    assert claim.patient.date_of_birth == date(1980, 1, 15)
    assert claim.provider.name == "Dr. Smith"
    assert claim.service.service_date == date(2023, 10, 27)
    assert claim.billing.total_amount == Decimal("150.00")
    assert claim.extraction_confidence == 0.95
    assert claim.extraction_notes == "All fields clearly visible"


def test_claim_data_defaults():
    """Test ClaimData with default values."""
    claim = ClaimData()
    
    assert claim.status == ClaimStatus.DRAFT
    assert claim.patient is not None
    assert claim.provider is not None
    assert claim.service is not None
    assert claim.billing is not None


def test_claim_data_json_serialization():
    """Test that ClaimData can be serialized to JSON."""
    claim = ClaimData(
        claim_id="CLM-123",
        patient=PatientInfo(full_name="John Doe", date_of_birth="1980-01-15"),
        billing=BillingInfo(total_amount="150.00")
    )
    
    json_data = claim.dict()
    
    assert json_data["claim_id"] == "CLM-123"
    assert json_data["patient"]["full_name"] == "John Doe"
    assert json_data["status"] == "DRAFT"
