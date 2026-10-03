"""Duplicate evidence is an explicit ownership-scoped committed snapshot."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import text

from config.settings import Settings
from models import Document
from schema.risk import RiskRefreshCreate
from services import risk_storage
from services.extraction_service import persist_processing_result
from services.job_lifecycle import acquire
from services.job_service import enqueue
from services.risk_assessment_service import refresh
from services.risk_context import context_for, peer_query
from tests.integration.test_jobs import jobs_db as _jobs_db
from tests.integration.test_jobs import processing_output

jobs_db = _jobs_db
pytestmark = pytest.mark.integration


def owned_doc(factory, document, owner, *, sha="a" * 64, active=True, state="RECEIVED"):
    doc_id = document()
    with factory.begin() as db:
        doc = db.get(Document, doc_id)
        doc.sha256 = sha
        doc.claim.owner_id = owner
        doc.claim.is_active = active
        doc.claim.current_state = state
    return doc_id


def test_duplicate_context_excludes_other_owner_self_rejected_and_inactive(jobs_db):
    factory, document = jobs_db
    owner = str(uuid4())
    own = owned_doc(factory, document, owner)
    owned_doc(factory, document, str(uuid4()))
    owned_doc(factory, document, owner, state="REJECTED")
    owned_doc(factory, document, owner, active=False)
    owned_doc(factory, document, owner, sha="b" * 64)
    with factory() as db:
        doc = db.get(Document, own)
        first = context_for(db, doc.claim, own)
        assert first.complete and first.duplicate_count == 0
    owned_doc(factory, document, owner)
    with factory() as db:
        # Independent worker session has no actor_id: persisted ownership wins.
        assert "actor_id" not in db.info
        doc = db.get(Document, own)
        second = context_for(db, doc.claim, own)
        assert second.duplicate_count == 1 and second.fingerprint != first.fingerprint


def test_later_peer_arrival_and_rejection_require_new_refresh_revision(jobs_db):
    factory, document = jobs_db
    owner = str(uuid4())
    own = owned_doc(factory, document, owner)
    with factory.begin() as db:
        enqueue(db, own, Settings(_env_file=None))
    with factory.begin() as db:
        lease = acquire(db, Settings(_env_file=None))
    with factory.begin() as db:
        result = persist_processing_result(db, lease.job_id, lease.owner, processing_output())
        claim_id = db.get(Document, result.document_id).claim_id
        first = risk_storage.current(db, claim_id)
        assert first.level == "LOW"
    peer = owned_doc(factory, document, owner)
    with factory.begin() as db:
        assert risk_storage.current(db, claim_id).assessment_id == first.assessment_id
        second = refresh(db, claim_id, RiskRefreshCreate(expected_version=first.claim_version))
        assert second.level == "HIGH" and second.revision == 2
        assert [item["code"] for item in second.signals] == ["possible_duplicate_document"]
    with factory.begin() as db:
        db.get(Document, peer).claim.current_state = "REJECTED"
    with factory.begin() as db:
        third = refresh(db, claim_id, RiskRefreshCreate(expected_version=first.claim_version))
        assert third.level == "LOW" and third.revision == 3
        assert third.assessment_id != first.assessment_id
        assert len(risk_storage.history(db, claim_id)) == 3


def test_concurrent_completions_do_not_lock_peer_claims(jobs_db):
    factory, document = jobs_db
    owner = str(uuid4())
    docs = [owned_doc(factory, document, owner) for _ in range(2)]
    for doc in docs:
        with factory.begin() as db:
            enqueue(db, doc, Settings(_env_file=None))
    leases = []
    for _ in docs:
        with factory.begin() as db:
            leases.append(acquire(db, Settings(_env_file=None)))
    barrier = Barrier(2)

    def finish(lease):
        barrier.wait(timeout=5)
        with factory.begin() as db:
            result = persist_processing_result(db, lease.job_id, lease.owner, processing_output())
            claim_id = db.get(Document, result.document_id).claim_id
            return risk_storage.current(db, claim_id).level

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(finish, lease) for lease in leases]
        assert [item.result(timeout=15) for item in futures] == ["HIGH", "HIGH"]


def test_duplicate_query_uses_indexable_scoped_predicates(jobs_db):
    factory, document = jobs_db
    own = owned_doc(factory, document, str(uuid4()))
    with factory.begin() as db:
        doc = db.get(Document, own)
        statement = peer_query(doc.claim, doc).compile(
            db.bind, compile_kwargs={"literal_binds": True}
        )
        plan = db.execute(text("EXPLAIN " + str(statement))).scalars().all()
        assert plan
        definition = db.scalar(
            text(
                "SELECT indexdef FROM pg_indexes WHERE tablename='documents' AND indexname='ix_document_sha_claim'"
            )
        )
        assert "sha256, claim_id" in definition
        assert "owner_id" in str(statement) and "sha256" in str(statement)
