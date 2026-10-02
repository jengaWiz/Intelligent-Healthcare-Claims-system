"""Explicit opt-in live smoke using a generated synthetic PDF, never user documents."""

import argparse
import json
import logging
import tempfile
from importlib.metadata import version
from pathlib import Path

from agents.extraction_agent import ExtractionAgent
from config.settings import ConfigurationError, get_settings
from extractors.azure_extractor import extract_document_from_azure
from services.provider_errors import ProviderFailure


def synthetic_pdf() -> bytes:
    text = (
        b"BT /F1 12 Tf 50 740 Td (SYNTHETIC CLAIM - NOT A REAL PATIENT) Tj "
        b"0 -20 Td (Patient: Synthetic Example) Tj "
        b"0 -20 Td (Provider: Synthetic Clinic) Tj "
        b"0 -20 Td (Service date: 2025-01-01) Tj "
        b"0 -20 Td (Total amount: USD 42.50) Tj ET"
    )
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(text)).encode() + b" >>\nstream\n" + text + b"\nendstream",
    ]
    pdf = b"%PDF-1.4\n"
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(pdf))
        pdf += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(pdf)
    pdf += b"xref\n0 6\n0000000000 65535 f \n"
    pdf += b"".join(f"{offset:010} 00000 n \n".encode() for offset in offsets[1:])
    pdf += f"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return pdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Permit billable synthetic Azure calls")
    parser.add_argument("--with-llm", action="store_true", help="Also call the configured LLM")
    args = parser.parse_args()
    if not args.live:
        parser.error("Live calls require --live; ordinary CI never runs this script")
    # SDK errors/logs may include payloads. Output is restricted to safe codes and provenance.
    logging.disable(logging.CRITICAL)
    report = {
        "synthetic": True,
        "sdk_versions": {
            name: version(name)
            for name in (
                "azure-ai-documentintelligence",
                "langchain-google-genai",
                "langchain-openai",
            )
        },
    }
    try:
        settings = get_settings()
        settings.require_azure()
        if args.with_llm:
            settings.require_llm()
        report.update(
            azure_model=settings.azure_document_model,
            provider_timeout_seconds=settings.provider_timeout_seconds,
        )
        with tempfile.TemporaryDirectory(prefix="claims-synthetic-provider-") as directory:
            path = Path(directory) / "synthetic.pdf"
            path.write_bytes(synthetic_pdf())
            output = extract_document_from_azure(str(path), settings=settings)
            report["ocr"] = "passed"
            report["azure_api_version"] = output["evidence"].get("apiVersion")
            if args.with_llm:
                report.update(llm_provider=settings.llm_provider, llm_model=settings.llm_model)
                agent = ExtractionAgent(settings=settings)
                try:
                    agent.extract(output["raw_text"])
                finally:
                    agent.close()
                report["extraction_contract"] = "passed"
    except ProviderFailure as failure:
        report["failure"] = failure.as_dict()
    except ConfigurationError:
        report["failure"] = {"code": "provider_configuration"}
    except Exception:
        report["failure"] = {"code": "smoke_failed"}
    print(json.dumps(report, sort_keys=True))
    return 1 if "failure" in report else 0


if __name__ == "__main__":
    raise SystemExit(main())
