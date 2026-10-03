"""Seed one synthetic M1 record only into an empty dedicated old-schema database."""

import json
import os
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import Session

from config.settings import Settings
from models import Claim, Document, ExtractionResult, ProcessingJob, Review, ValidationOutcome
from schema.claim_data import ClaimData
from scripts.generate_samples import pdf


def seed(settings):
    if not settings.synthetic_mode:
        raise ValueError("Upgrade seed requires explicit synthetic mode")
    engine = create_engine(settings.require_database_url(), hide_parameters=True)
    created_path = None
    try:
        with Session(engine) as db, db.begin():
            revision = db.scalar(text("SELECT version_num FROM alembic_version"))
            if revision != "b61ceaf00211" or db.scalar(select(func.count()).select_from(Claim)):
                raise ValueError("Upgrade seed requires an empty M1 test database")
            claim = Claim(
                current_state="READY",
                version=3,
                owner_id="api",
                source_system="synthetic-m1-upgrade-fixture",
            )
            db.add(claim)
            db.flush()
            raw = {
                "patient_name": "Synthetic Legacy",
                "provider_name": "Synthetic Clinic",
                "service_date": "2026-10-01",
                "total_amount": "42.50",
                "confidence": 0.95,
                "reasoning": "Manually seeded synthetic legacy migration fixture",
            }
            data = ClaimData.from_extracted_data(raw).model_copy(
                update={"claim_id": str(claim.claim_id)}
            )
            payload = pdf(
                [
                    "SYNTHETIC LEGACY UPGRADE FIXTURE",
                    "Patient: Synthetic Legacy",
                    "Provider: Synthetic Clinic",
                    "Service date: 2026-10-01",
                    "Amount: USD 42.50",
                ]
            )
            settings.upload_dir.mkdir(parents=True, exist_ok=True)
            created_path = settings.upload_dir / f"{uuid4().hex}.pdf"
            fd = os.open(created_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            document = Document(
                claim_id=claim.claim_id,
                file_name="synthetic-legacy.pdf",
                file_mime_type="application/pdf",
                byte_size=len(payload),
                sha256=sha256(payload).hexdigest(),
                storage_path=str(created_path.resolve()),
                document_state="EXTRACTED",
            )
            db.add(document)
            db.flush()
            job = ProcessingJob(document_id=document.document_id, state="SUCCEEDED", attempts=1)
            db.add(job)
            db.flush()
            result = ExtractionResult(
                document_id=document.document_id,
                job_id=job.job_id,
                extracted_data=raw,
                normalized_data=data.model_dump(mode="json"),
                confidence=0.95,
                outcome="READY",
                extraction_engine="SyntheticFixture",
                extraction_version="m1.1",
                provenance={"mode": "synthetic-fixture", "corpus_version": "legacy-upgrade-seed"},
            )
            result.validation = ValidationOutcome(
                is_valid=True,
                validation_score=1,
                semantic_status="completed",
                issues=[],
                recommendations=[],
            )
            db.add(result)
            snapshot = {
                "data": data.model_dump(mode="json"),
                "validation": {
                    "is_valid": True,
                    "validation_score": 1,
                    "semantic_status": "completed",
                    "issues": [],
                    "recommendations": [],
                },
            }
            db.add(
                Review(
                    claim_id=claim.claim_id,
                    actor_id="api",
                    decision="approve",
                    reason="Verified legacy synthetic source",
                    previous_version=2,
                    new_version=3,
                    before_data=snapshot,
                    after_data={**snapshot, "human_reviewed": True},
                )
            )
            claim_id = claim.claim_id
        return {"claim_id": str(claim_id)}
    except Exception:
        if created_path:
            created_path.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()


def main():
    print(json.dumps(seed(Settings())))


if __name__ == "__main__":
    main()
