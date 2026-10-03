import json
from pathlib import Path

import pytest

from config.settings import Settings
from services.provider_errors import ProviderFailure
from services.synthetic_processor import process_sample

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("scenario", ["valid", "review", "medium", "high"])
def test_fixture_fields_and_outcomes(scenario):
    manifest = json.loads((ROOT / "samples/manifest.json").read_text())
    expected = manifest["scenarios"][scenario]
    output = process_sample(
        ROOT / "samples" / expected["file"], settings=Settings(_env_file=None, synthetic_mode=True)
    )
    assert output.outcome == expected["expected_state"]
    assert output.extracted_data == expected["extracted"]
    assert output.provenance["llm_model"] == "not-called"


def test_fixture_mode_is_explicit_and_unknown_documents_fail(tmp_path):
    with pytest.raises(ProviderFailure):
        process_sample(ROOT / "samples/valid.pdf", settings=Settings(_env_file=None))
    unknown = tmp_path / "unknown.pdf"
    unknown.write_bytes(b"%PDF-arbitrary synthetic content")
    for path in (unknown, ROOT / "samples/failure.pdf"):
        with pytest.raises(ProviderFailure):
            process_sample(path, settings=Settings(_env_file=None, synthetic_mode=True))
