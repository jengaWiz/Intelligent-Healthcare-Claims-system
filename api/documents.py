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
            
    )