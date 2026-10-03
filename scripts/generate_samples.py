"""Rebuild the fixed synthetic corpus; no network or patient data."""

import json
from hashlib import sha256
from pathlib import Path


def pdf(lines):
    content = "BT /F1 12 Tf 50 740 Td "
    for index, line in enumerate(lines):
        safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        content += ("0 -24 Td " if index else "") + f"({safe}) Tj "
    content += "ET"
    stream = content.encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
    ]
    output = b"%PDF-1.4\n"
    offsets = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(output))
        output += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(output)
    output += b"xref\n0 6\n0000000000 65535 f \n"
    output += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets)
    output += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return output


def main():
    root = Path(__file__).resolve().parents[1] / "samples"
    scenarios = {}
    for name, outcome, amount, confidence, risk in [
        ("valid", "READY", "42.50", 0.95, "LOW"),
        ("review", "REVIEW_REQUIRED", None, 0.55, "INSUFFICIENT_DATA"),
        ("failure", "FAILED", None, None, None),
        ("medium", "READY", "10001", 0.95, "MEDIUM"),
        ("high", "REVIEW_REQUIRED", "100001", 0.95, "HIGH"),
    ]:
        raw = {
            "patient_name": "Synthetic Example",
            "patient_dob": "1980-01-01",
            "provider_name": "Synthetic Clinic",
            "service_date": "2026-10-01",
            "total_amount": amount,
            "confidence": confidence,
            "reasoning": "Deterministic synthetic fixture; no live OCR or model evaluation",
        }
        lines = [
            "SYNTHETIC CLAIM - NOT A REAL PATIENT",
            f"Scenario: {name.upper()} / expected {outcome}",
            "Patient: Synthetic Example",
            "Date of birth: 1980-01-01",
            "Provider: Synthetic Clinic",
            "Service date: 2026-10-01",
            f"Total amount: USD {amount or 'MISSING'}",
            "Fixture mode only: failure simulates a permanent provider error."
            if name == "failure"
            else "Document-data review only; no insurance/payment decision.",
        ]
        data = pdf(lines)
        (root / f"{name}.pdf").write_bytes(data)
        scenarios[name] = {
            "file": f"{name}.pdf",
            "sha256": sha256(data).hexdigest(),
            "expected_state": outcome,
            "expected_risk": risk,
            "extracted": raw,
        }
    scenarios["duplicate"] = {
        **scenarios["valid"],
        "expected_risk": "HIGH",
        "requires_prior": "valid",
        "note": "Upload identical valid.pdf bytes again in the same workspace; possible duplicate document only.",
    }
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "version": "risk-corpus-1",
                "reference_date": "2026-10-03",
                "synthetic_only": True,
                "scenarios": scenarios,
            },
            indent=2,
        )
        + "\n"
    )


if __name__ == "__main__":
    main()
