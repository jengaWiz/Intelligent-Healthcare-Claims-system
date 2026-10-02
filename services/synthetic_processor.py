"""Explicit fixture mode accepts only byte-identical versioned synthetic samples."""

import json
from hashlib import sha256
from pathlib import Path

from agents.validation_agent import ValidationAgent
from services.processing import ProcessingResult, normalize_and_validate
from services.provider_errors import FailureCode, ProviderFailure


class FixtureSemanticClient:
    def invoke(self, _prompt):
        return '{"has_issues": false, "issues": [], "confidence": 1.0}'


def process_sample(path, *, settings):
    if not settings.synthetic_mode:
        raise ProviderFailure("processing", FailureCode.CONFIGURATION)
    manifest = json.loads(
        (Path(__file__).resolve().parents[1] / "samples/manifest.json").read_text()
    )
    digest = sha256(Path(path).read_bytes()).hexdigest()
    sample = next(
        (entry for entry in manifest["scenarios"].values() if entry["sha256"] == digest), None
    )
    if sample is None or sample["expected_state"] == "FAILED":
        raise ProviderFailure("ocr", FailureCode.INVALID_RESPONSE)
    raw = sample["extracted"]
    claim, validation, outcome = normalize_and_validate(
        raw,
        validator=ValidationAgent(settings=settings, client=FixtureSemanticClient()),
        settings=settings,
    )
    return ProcessingResult(
        extracted_data=raw,
        claim_data=claim,
        validation=validation,
        confidence=raw["confidence"],
        reasoning=raw["reasoning"],
        outcome=outcome,
        provenance={
            "mode": "synthetic-fixture",
            "corpus_version": manifest["version"],
            "confidence_threshold": settings.extraction_confidence_threshold,
            "azure_model": "not-called",
            "llm_model": "not-called",
        },
    )
