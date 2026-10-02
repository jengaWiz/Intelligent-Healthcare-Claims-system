from config.settings import Settings
from scripts.evaluate_providers import evaluate
from services.synthetic_processor import process_sample


def test_unconfigured_live_evaluation_never_invents_metrics():
    def forbidden(*args, **kwargs):
        raise AssertionError("Unconfigured evaluation must not invoke providers")

    report = evaluate(Settings(_env_file=None), processor=forbidden)
    assert report["status"] == "not_configured"
    assert report["sample_size"] == 0 and report["field_correctness"] is None


def test_evaluation_counts_exact_fixture_fields_without_general_accuracy_claim():
    settings = Settings(
        _env_file=None,
        synthetic_mode=True,
        azure_document_intelligence_endpoint="https://synthetic.invalid",
        azure_document_intelligence_key="synthetic-key",
        llm_model="synthetic-model",
        google_api_key="synthetic-key",
    )
    report = evaluate(settings, processor=process_sample)
    assert report["sample_size"] == 2 and report["status"] == "completed"
    assert report["field_correctness"] == {
        "correct_fields": 10,
        "evaluated_fields": 10,
        "fraction": 1.0,
    }
    assert report["cases"][1]["outcome"] == "REVIEW_REQUIRED"


def test_evaluation_failure_redacts_exception_details():
    settings = Settings(
        _env_file=None,
        azure_document_intelligence_endpoint="https://synthetic.invalid",
        azure_document_intelligence_key="synthetic-key",
        llm_model="synthetic-model",
        google_api_key="synthetic-key",
    )

    def failed(*args, **kwargs):
        raise RuntimeError("private key and document content")

    report = evaluate(settings, processor=failed)
    assert report["status"] == "failed" and report["field_correctness"]["evaluated_fields"] == 0
    assert "private key" not in str(report)
