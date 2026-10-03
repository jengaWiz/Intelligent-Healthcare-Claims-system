"""Export reproducible synthetic rule conformance, never predictive accuracy."""

import json
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path

from config.settings import Settings
from services.provider_errors import ProviderFailure
from services.risk_engine import RiskContext, assess, load_policy
from services.synthetic_processor import process_sample


def verify_corpus():
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "samples/manifest.json").read_text())
    reference = datetime.fromisoformat(manifest["reference_date"]).replace(tzinfo=UTC)
    cases = []
    for name, entry in manifest["scenarios"].items():
        path = root / "samples" / entry["file"]
        if sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError("Synthetic corpus hash mismatch")
        try:
            output = process_sample(path, settings=Settings(_env_file=None, synthetic_mode=True))
        except ProviderFailure:
            if entry["expected_state"] != "FAILED":
                raise
            cases.append(
                {
                    "scenario": name,
                    "expected_level": None,
                    "actual_level": None,
                    "matched": True,
                    "document_state": "FAILED",
                }
            )
            continue
        context = RiskContext(
            duplicate_count=1 if entry.get("requires_prior") else 0,
            fingerprint="b" * 64,
            captured_at=reference,
        )
        evaluation = assess(
            output.claim_data,
            output.validation,
            human_verified=False,
            context=context,
            assessed_at=reference,
            policy=load_policy(),
        )
        cases.append(
            {
                "scenario": name,
                "expected_level": entry["expected_risk"],
                "actual_level": evaluation.level,
                "matched": evaluation.level == entry["expected_risk"]
                and output.outcome == entry["expected_state"],
                "document_state": output.outcome,
                "reason_codes": [item.code for item in evaluation.signals],
                "requires_prior": entry.get("requires_prior"),
            }
        )
    return {
        "synthetic_only": True,
        "live_provider_calls": 0,
        "method": "synthetic_rule_conformance",
        "policy_version": load_policy().version,
        "corpus_version": manifest["version"],
        "reference_date": manifest["reference_date"],
        "context_mode": "declared fixture sequence; real database context verified separately",
        "cases": cases,
        "all_matched": all(item["matched"] for item in cases),
        "limitations": [
            "Illustrative rules, not fraud probabilities or predictive accuracy",
            "Synthetic cases do not establish real-world detection performance",
        ],
    }


def main():
    report = verify_corpus()
    target = Path(__file__).resolve().parents[1] / "docs/verification/risk.json"
    target.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))
    return 0 if report["all_matched"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
