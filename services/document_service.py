from sqlalchemy.orm import Session
from models.document import Document
from services.storage_service import save_file
from services.document_state_service import validate_document_transition

def create_document(
        db: Session,
        claim_id,
        file_name: str,
        mime_type: str,
        file_bytes: bytes
) -> Document:
    
    storage_path = save_file(file_bytes, file_name)

    document = Document(
        claim_id=claim_id,
        file_name=file_name,
        file_mime_type=mime_type,
        storage_path=storage_path,
        document_state = "UPLOADED"
    )

    db.add(document)
    db.commit()
    db.refresh(document)

    return document


def update_document_state(db, document, next_state: str):
    validate_document_transition(document.document_state, next_state)

    document.document_state = next_state
    db.commit()
    db.refresh(document)

    return document

def mark_document_for_extraction(db, document):
    return update_document_state(db, document, "EXTRACTION_PENDING")
