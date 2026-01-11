from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from database.session import get_db 
from services.document_service import create_document

router = APIRouter()

ALLOWED_TYPES = {
    "application/pdf",
    "image/jpeg",
    "image/png"
}

@router.post("/claim/{claim_id}/documents", status_code=201)
async def upload_document(
    claim_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail="Unsupported file type")
    
    file_type = await file.read()

    document = create_document(
        db=db,
        claim_id=claim_id,
        file_name=file.filename,
        mime_type=file.content_type,
        file_bytes=file_type
    )
    
    return document

@router.post("/documents/{document_id}/extract", status_code=202)
async def extract_document(
    document_id: str,
    db: Session = Depends(get_db)
):
    from services.document_service import mark_document_for_extraction
    from services.extraction_service import run_extraction_pipeline
    
    try:
        # Mark for extraction
        mark_document_for_extraction(db, document_id)
        
        # Run extraction (synchronously for now as per instructions, but endpoint is async)
        # In a real system, this would be a background task
        result = run_extraction_pipeline(db, document_id)
        
        return {
            "message": "Extraction completed",
            "document_id": document_id,
            "confidence": result.confidence,
            "status": result.document.claim.current_state
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))