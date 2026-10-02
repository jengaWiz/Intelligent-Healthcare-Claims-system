from sqlalchemy.orm import configure_mappers

from database.base import Base
from models import Document


def test_all_mappings_register_and_identifiers_match():
    configure_mappers()
    assert set(Base.metadata.tables) == {
        "claims",
        "browser_sessions",
        "documents",
        "processing_jobs",
        "job_requests",
        "extraction_results",
        "validation_outcomes",
        "reviews",
    }
    assert Document.__table__.c.document_id.primary_key
    assert not hasattr(Document, "id")
    assert not hasattr(Document, "documents_id")
    for table in Base.metadata.tables.values():
        for foreign_key in table.foreign_keys:
            assert foreign_key.column.table.name in Base.metadata.tables
