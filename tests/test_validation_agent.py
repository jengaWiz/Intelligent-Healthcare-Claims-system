import pytest
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import MagicMock, patch

from schema.claim_data import ClaimData, PatientInfo, ProviderInfo, ServiceInfo, BillingInfo
from schema.validation_result import ValidationResult, ValidationIssue
from agents.validation_agent import ValidationAgent


def test_validation_agent_missing_fields():
    """Test detection of missing required fields."""
    # Create claim with missing fields
    claim = ClaimData(
        patient=PatientInfo(full_name=None),  # Missing
        service=ServiceInfo(service_date=None),  # Missing
        billing=BillingInfo(total_amount=None)  # Missing
    )
    
    agent = ValidationAgent()
    
    # Mock LLM to avoid actual calls
    with patch.object(agent, '_check_semantic_consistency', return_value=[]):
        result = agent.validate(claim)
    
    assert not result.is_valid
    assert result.has_critical_issues
    
    # Check for specific missing field issues
    critical_fields = [issue.field for issue in result.critical_issues]
    assert "patient.full_name" in critical_fields
    assert "service.service_date" in critical_fields
    assert "billing.total_amount" in critical_fields


def test_validation_agent_date_logic():
    """Test date logic validation."""
    today = date.today()
    future_date = today + timedelta(days=30)
    
    # Service date in future
    claim = ClaimData(
        patient=PatientInfo(full_name="John Doe"),
        service=ServiceInfo(service_date=future_date),
        billing=BillingInfo(total_amount=Decimal("100"))
    )
    
    agent = ValidationAgent()
    
    with patch.object(agent, '_check_semantic_consistency', return_value=[]):
        result = agent.validate(claim)
    
    assert not result.is_valid
    date_issues = [i for i in result.issues if "service.service_date" in i.field]
    assert len(date_issues) > 0
    assert any("future" in i.description.lower() for i in date_issues)


def test_validation_agent_dob_after_service():
    """Test DOB after service date detection."""
    claim = ClaimData(
        patient=PatientInfo(
            full_name="John Doe",
            date_of_birth=date(2020, 1, 1)
        ),
        service=ServiceInfo(service_date=date(2019, 1, 1)),  # Before DOB
        billing=BillingInfo(total_amount=Decimal("100"))
    )
    
    agent = ValidationAgent()
    
    with patch.object(agent, '_check_semantic_consistency', return_value=[]):
        result = agent.validate(claim)
    
    assert not result.is_valid
    dob_issues = [i for i in result.issues if "date_of_birth" in i.field]
    assert len(dob_issues) > 0


def test_validation_agent_negative_amount():
    """Test negative amount detection."""
    claim = ClaimData(
        patient=PatientInfo(full_name="John Doe"),
        service=ServiceInfo(service_date=date.today()),
        billing=BillingInfo(total_amount=Decimal("-100"))
    )
    
    agent = ValidationAgent()
    
    with patch.object(agent, '_check_semantic_consistency', return_value=[]):
        result = agent.validate(claim)
    
    assert not result.is_valid
    amount_issues = [i for i in result.issues if "total_amount" in i.field]
    assert len(amount_issues) > 0
    assert any("positive" in i.description.lower() for i in amount_issues)


def test_validation_agent_high_amount_warning():
    """Test warning for unusually high amounts."""
    claim = ClaimData(
        patient=PatientInfo(full_name="John Doe"),
        service=ServiceInfo(service_date=date.today()),
        billing=BillingInfo(total_amount=Decimal("150000"))
    )
    
    agent = ValidationAgent()
    
    with patch.object(agent, '_check_semantic_consistency', return_value=[]):
        result = agent.validate(claim)
    
    # Should be valid but have warnings
    assert result.is_valid  # No critical issues
    warning_issues = result.warning_issues
    assert len(warning_issues) > 0


def test_validation_agent_perfect_claim():
    """Test validation of a perfect claim."""
    claim = ClaimData(
        patient=PatientInfo(
            full_name="John Doe",
            date_of_birth=date(1980, 1, 1)
        ),
        provider=ProviderInfo(name="Dr. Smith"),
        service=ServiceInfo(service_date=date.today() - timedelta(days=7)),
        billing=BillingInfo(total_amount=Decimal("150.00"))
    )
    
    agent = ValidationAgent()
    
    with patch.object(agent, '_check_semantic_consistency', return_value=[]):
        result = agent.validate(claim)
    
    assert result.is_valid
    assert result.validation_score == 1.0
    assert len(result.issues) == 0


def test_validation_score_calculation():
    """Test validation score calculation."""
    agent = ValidationAgent()
    
    # No issues = 1.0
    issues = []
    score = agent._calculate_score(issues)
    assert score == 1.0
    
    # One critical issue
    issues = [
        ValidationIssue(
            severity="critical",
            field="test",
            issue_type="missing",
            description="Test"
        )
    ]
    score = agent._calculate_score(issues)
    assert score == 0.7  # 1.0 - 0.3
    
    # Multiple issues
    issues = [
        ValidationIssue(severity="critical", field="test1", issue_type="missing", description="Test"),
        ValidationIssue(severity="warning", field="test2", issue_type="missing", description="Test"),
        ValidationIssue(severity="info", field="test3", issue_type="missing", description="Test"),
    ]
    score = agent._calculate_score(issues)
    assert score == 0.55  # 1.0 - 0.3 - 0.1 - 0.05


def test_validation_recommendations():
    """Test recommendation generation."""
    agent = ValidationAgent()
    
    issues = [
        ValidationIssue(severity="critical", field="test1", issue_type="missing", description="Test"),
        ValidationIssue(severity="warning", field="test2", issue_type="missing", description="Test"),
    ]
    
    recommendations = agent._generate_recommendations(issues)
    
    assert len(recommendations) > 0
    assert any("critical" in rec.lower() for rec in recommendations)
