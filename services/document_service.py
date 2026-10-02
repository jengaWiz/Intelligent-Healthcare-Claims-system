from hashlib import sha256
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import Claim, Document
from services.access_service import scoped
from services.document_state_service import validate_document_transition


class DocumentConflict(ValueError):
    pass


class ClaimNotFound(ValueError):
    pass


def verify_upload_claim(db: Session, claim_id: UUID, *, lock=False):
    statement = select(Claim).where(Claim.claim_id == claim_id)
    statement = scoped(statement, db)
    if lock:
        statement = statement.with_for_update()
    claim = db.scalar(statement)
    if claim is None:
        raise ClaimNotFound("Claim not found")
    if (
        claim.current_state != "RECEIVED"
        or db.scalar(select(Document.document_id).where(Document.claim_id == claim_id)) is not None
    ):
        raise DocumentConflict("Claim already has a document or is processing")
    return claim


def create_document(
    db: Session, claim_id: UUID, file_name: str, mime_type: str, file_bytes: bytes, stored_path: str
) -> Document:
    # Caller owns file creation/cleanup and the transaction including commit.
    document = Document(
        claim_id=claim_id,
        file_name=file_name,
        file_mime_type=mime_type,
        storage_path=stored_path,
        byte_size=len(file_bytes),
        sha256=sha256(file_bytes).hexdigest(),
        document_state="UPLOADED",
    )
    db.add(document)
    db.flush()
    return document


def update_document_state(db, document, next_state: str):
    validate_document_transition(document.document_state, next_state)

    document.document_state = next_state
    db.flush()

    return document


def mark_document_for_extraction(db: Session, document_id: UUID) -> Document:

    document = db.query(Document).filter(Document.document_id == document_id).first()

    if not document:
        raise ValueError("Document not found")

    if document.document_state != "UPLOADED":
        raise ValueError(f"Document cannot be extracted from state {document.document_state}")

    # Update document state
    document.document_state = "QUEUED"

    # Update claim state if needed
    claim = document.claim
    if claim.current_state == "RECEIVED":
        claim.current_state = "PROCESSING"
        claim.version += 1

    db.flush()

    return document
