from models.browser_session import BrowserSession

"""Register all mappings for application sessions and migration metadata."""

from models.claim import Claim
from models.document import Document
from models.extraction_result import ExtractionResult
from models.job import ProcessingJob
from models.job_request import JobRequest
from models.review import Review
from models.validation import ValidationOutcome

__all__ = [
    "BrowserSession",
    "JobRequest",
    "Claim",
    "Document",
    "ExtractionResult",
    "ProcessingJob",
    "Review",
    "ValidationOutcome",
]
