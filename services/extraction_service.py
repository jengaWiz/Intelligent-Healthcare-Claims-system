"""Provider processing outside transactions; lease-checked atomic result persistence."""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agents.graphs.extraction_graph import build_extraction_graph
from models.document import Document
from models.extraction_result import ExtractionResult
from models.job import ProcessingJob
from models.validation import ValidationOutcome
from services.processing import ProcessingResult
from services.risk_assessment_service import publish


class ProcessingConflict(ValueError):
    """A stale worker or ineligible resource cannot publish processing results."""


def run_extraction_pipeline(document_path: str, *, settings=None, graph=None) -> ProcessingResult:
    state = (graph or build_extraction_graph(settings=settings)).invoke(
        {"document_path": document_path}
    )
    return ProcessingResult(
        extracted_data=state["extracted_data"],
        claim_data=state["normalized_data"],
        validation=state["validation"],
        confidence=state["confidence"],
        reasoning=state["extracted_data"]["reasoning"],
        outcome=state["status"],
        provenance=state["provenance"],
    )


def persist_processing_result(
    db: Session, job_id: UUID, lease_owner: UUID, output: ProcessingResult
) -> ExtractionResult:
    """Caller owns the transaction. No provider call occurs while rows are locked."""
    if not db.in_transaction():
        raise ProcessingConflict("Result persistence requires an explicit transaction")
    job = db.scalar(
        select(ProcessingJob)
        .where(
            ProcessingJob.job_id == job_id,
            ProcessingJob.state == "RUNNING",
            ProcessingJob.lease_owner == lease_owner,
            ProcessingJob.lease_expires_at > func.clock_timestamp(),
        )
        .with_for_update(key_share=True)
    )
    if job is None:
        raise ProcessingConflict("Job lease is not active or owned")
    document = db.scalar(
        select(Document).where(Document.document_id == job.document_id).with_for_update()
    )
    if document is None:
        raise ProcessingConflict("Document is unavailable")
    claim = document.claim
    # Lock the claim before advancing its version/state.
    db.refresh(claim, with_for_update=True)
    if document.document_state != "PROCESSING" or claim.current_state != "PROCESSING":
        raise ProcessingConflict("Document and claim must be processing")
    if job.lease_expires_at <= db.scalar(select(func.clock_timestamp())):
        raise ProcessingConflict("Job lease expired while acquiring locks")
    deadline = job.lease_expires_at
    threshold = output.provenance["confidence_threshold"]
    ready = (
        output.confidence >= threshold
        and output.validation.is_valid
        and not output.validation.issues
        and output.validation.semantic_status == "completed"
    )
    if output.outcome != ("READY" if ready else "REVIEW_REQUIRED"):
        raise ProcessingConflict("Processing outcome does not match validation gates")
    normalized = output.claim_data.model_copy(update={"claim_id": str(claim.claim_id)})
    result = ExtractionResult(
        document_id=document.document_id,
        job_id=job.job_id,
        extracted_data=output.extracted_data,
        normalized_data=normalized.model_dump(mode="json"),
        confidence=output.confidence,
        reasoning=output.reasoning,
        outcome=output.outcome,
        extraction_engine="SyntheticFixture"
        if output.provenance.get("mode") == "synthetic-fixture"
        else "Azure+LangGraph",
        extraction_version="m1.1",
        provenance={
            **output.provenance,
            "claim_id": str(claim.claim_id),
            "document_id": str(document.document_id),
            "job_id": str(job.job_id),
        },
    )
    result.validation = ValidationOutcome(**output.validation.model_dump(mode="json"))
    db.add(result)
    document.document_state = "EXTRACTED"
    claim.current_state = output.outcome
    claim.version += 1
    job.state = "SUCCEEDED"
    job.completed_at = func.now()
    job.lease_owner = None
    job.lease_expires_at = None
    job.error_code = None
    job.error_message = None
    db.flush()
    publish(db, claim, result, normalized, output.validation)
    if deadline <= db.scalar(select(func.clock_timestamp())):
        raise ProcessingConflict("Job lease expired while publishing assessment")
    return result
