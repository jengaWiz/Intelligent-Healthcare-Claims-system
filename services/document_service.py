from hashlib import sha256
from uuid import UUID

from sqlalchemy.orm import Session

from models.document import Document
from services.document_state_service import validate_document_transition
from services.storage_service import save_file


def create_document(
    db: Session, claim_id, file_name: str, mime_type: str, file_bytes: bytes
) -> Document:

    storage_path = save_file(file_bytes, file_name)

    document = Document(
        claim_id=claim_id,
        file_name=file_name,
        file_mime_type=mime_type,
        storage_path=storage_path,
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
