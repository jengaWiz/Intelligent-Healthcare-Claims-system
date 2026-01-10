import uuid
from sqlalchemy import Column, String, Integer, Boolean, DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database.base import Base

"""
Creates a claim table in the database
"""
class Claim(Base):
    _tablename_ = "claims"
    documents = relationship ("Document", backref="claim")

    claim_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4) 
    current_state = Column(String(50), nullable=False)
    version = Column(Integer, nullable=False, default=1)
    source_system = Column(String(100), nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), 
        server_default=func.now(),
        onupdate=func.now()
    )