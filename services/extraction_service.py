"""Provider processing outside transactions; lease-checked atomic result persistence."""

from agents.graphs.extraction_graph import build_extraction_graph
from services.processing import ProcessingResult


class ProcessingConflict(ValueError):
    """A stale worker or ineligible resource cannot publish processing results."""


def run_extraction_pipeline(document_path: str, *, settings=None, graph=None) -> ProcessingResult:
    state = (graph or build_extraction_graph(settings=settings)).invoke(
        {"document_path": document_path}
    )
    return ProcessingResult(
        extracted_data=state["extracted_data"],
        claim_data=state["normalized_data"],
        validation=state["validation"],
        confidence=state["confidence"],
        reasoning=state["extracted_data"]["reasoning"],
        outcome=state["status"],
        provenance=state["provenance"],
    )
