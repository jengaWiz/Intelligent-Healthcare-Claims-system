"""Opt-in live evaluation on fixed synthetic samples; never invent provider metrics."""

import argparse
import json
import logging
import time
from importlib.metadata import version
from pathlib import Path

from config.settings import ConfigurationError, Settings
from schema.claim_data import ClaimData
from services.extraction_service import run_extraction_pipeline
from services.provider_errors import classify_failure

ROOT = Path(__file__).resolve().parents[1]


def fields(claim):
    return {
        "patient_name": claim.patient.full_name,
        "patient_dob": claim.patient.date_of_birth,
        "provider_name": claim.provider.name,
        "service_date": claim.service.service_date,
        "total_amount": claim.billing.total_amount,
    }


def configuration_report(settings):
    report = {
        "synthetic_only": True,
        "status": "not_configured",
        "sample_size": 0,
        "corpus_version": "m1-corpus-1",
        "model_ids": {
            "azure": settings.azure_document_model,
            "llm_provider": settings.llm_provider,
            "llm": settings.llm_model,
        },
        "sdk_versions": {
            name: version(name)
            for name in (
                "azure-ai-documentintelligence",
                "langchain-google-genai",
                "langchain-openai",
            )
        },
        "cases": [],
        "field_correctness": None,
        "limitations": [
            "Two fixed synthetic documents cannot establish general accuracy",
            "Model-reported confidence is not measured accuracy",
            "Failure fixture is excluded because it only simulates a provider error",
            "No payer authorization, payment decision, or production compliance evaluation",
        ],
    }
    try:
        settings.require_azure()
        settings.require_llm()
    except ConfigurationError:
        report["missing_prerequisite"] = (
            "Configure Azure endpoint/key and selected LLM model/key server-side"
        )
        return report
    report["status"] = "configured_not_evaluated"
    return report


def evaluate(settings, *, processor=run_extraction_pipeline):
    report = configuration_report(settings)
    if report["status"] == "not_configured":
        return report
    manifest = json.loads((ROOT / "samples/manifest.json").read_text())
    correct, count = 0, 0
    for name in ("valid", "review"):
        sample = manifest["scenarios"][name]
        started = time.monotonic()
        case = {"sample": name}
        report["sample_size"] += 1
        try:
            output = processor(str(ROOT / "samples" / sample["file"]), settings=settings)
            expected = fields(ClaimData.from_extracted_data(sample["extracted"]))
            actual = fields(output.claim_data)
            matches = {field: actual[field] == value for field, value in expected.items()}
            count += len(matches)
            correct += sum(matches.values())
            case.update(
                status="completed",
                field_matches=matches,
                outcome=output.outcome,
                expected_outcome=sample["expected_state"],
                provenance=output.provenance,
            )
        except Exception as exc:
            failure = classify_failure(exc, "processing")
            case.update(status="failed", failure_code=failure.code.value)
        case["latency_ms"] = round((time.monotonic() - started) * 1000, 2)
        report["cases"].append(case)
    report["status"] = (
        "completed" if all(case["status"] == "completed" for case in report["cases"]) else "failed"
    )
    report["field_correctness"] = {
        "correct_fields": correct,
        "evaluated_fields": count,
        "fraction": correct / count if count else None,
    }
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--live",
        action="store_true",
        help="Permit billable Azure/LLM calls on the two synthetic samples",
    )
    mode.add_argument(
        "--configuration-only",
        action="store_true",
        help="Inspect settings without sending data or calling providers",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    logging.disable(logging.CRITICAL)
    settings = Settings().model_copy(update={"synthetic_mode": False})
    report = configuration_report(settings) if args.configuration_only else evaluate(settings)
    text = json.dumps(report, indent=2, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    print(text, end="")
    return 0 if args.configuration_only or report["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
