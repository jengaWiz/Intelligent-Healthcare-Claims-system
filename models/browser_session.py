"""Only hashes of browser session credentials are stored."""

from sqlalchemy import Column, DateTime, String

from database.base import Base


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    token_hash = Column(String(64), primary_key=True)
    actor_id = Column(String(100), nullable=False)
    csrf_token = Column(String(64), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
