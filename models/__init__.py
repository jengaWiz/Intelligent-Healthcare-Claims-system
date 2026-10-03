"""Register all mappings for application sessions and migration metadata."""

from models.browser_session import BrowserSession
from models.claim import Claim
from models.document import Document
from models.extraction_result import ExtractionResult
from models.job import ProcessingJob
from models.job_request import JobRequest
from models.review import Review
from models.risk import RiskAcknowledgment, RiskAssessment
from models.validation import ValidationOutcome

__all__ = [
    "RiskAssessment",
    "RiskAcknowledgment",
    "BrowserSession",
    "JobRequest",
    "Claim",
    "Document",
    "ExtractionResult",
    "ProcessingJob",
    "Review",
    "ValidationOutcome",
]
