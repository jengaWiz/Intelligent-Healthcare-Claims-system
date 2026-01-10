ALLOWED_DOCUMENT_TRANSITIONS = {
    "UPLOADED": {"EXTRACTION_PENDING"},
    "EXTRACTION_PENDING": {"EXTRACTED", "FAILED"},
    "FAILED": {"EXTRACTION_PENDING"},
}


def validate_document_transition(current_state: str, next_state: str):
    allowed = ALLOWED_DOCUMENT_TRANSITIONS.get(current_state, set())
    if next_state not in allowed:
        raise ValueError(
            f"Invalid document state transition: {current_state} → {next_state}"
        )
