from sqlalchemy.orm import Session
from models.document import Document
from models.extraction_result import ExtractionResult
from agents.graphs.extraction_graph import extraction_graph


def run_extraction_pipeline(
    db: Session,
    document_id: int
) -> ExtractionResult:
    document = (
        db.query(Document)
        .filter(Document.id == document_id)
        .first()
    )

    if not document:
        raise ValueError("Document not found")

    if document.document_state != "EXTRACTION_PENDING":
        raise ValueError("Document not ready for extraction")

    # Run extraction graph
    initial_state = {
        "document_path": document.storage_path,
        "azure_output": {},
        "extracted_data": {},
        "confidence": 0.0,
        "status": "PENDING"
    }
    
    final_state = extraction_graph.invoke(initial_state)
    
    extracted = final_state["extracted_data"]
    confidence = final_state["confidence"]
    status = final_state["status"]

    # Persist result
    result = ExtractionResult(
        document_id=document.documents_id,
        extracted_data=extracted,
        confidence=confidence,
        reasoning=extracted.get("reasoning", ""),
        extraction_engine="Azure+LangGraph",
        extraction_version="1.0"
    )

    db.add(result)

    # Update states
    document.document_state = "EXTRACTED"
    if status == "APPROVED":
        document.claim.current_state = "EXTRACTED"
    else:
        document.claim.current_state = "RISK_CLASSIFIED" # Or some other state indicating review needed

    db.commit()
    db.refresh(result)

    return result
