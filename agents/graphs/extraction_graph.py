from typing import TypedDict

from langgraph.graph import END, StateGraph

from agents.extraction_agent import ExtractionAgent
from agents.validation_agent import ValidationAgent
from config.settings import get_settings
from extractors.azure_extractor import extract_document_from_azure
from services.processing import normalize_and_validate


class ExtractionState(TypedDict, total=False):
    document_path: str
    azure_output: dict
    extracted_data: dict
    confidence: float
    normalized_data: dict
    validation: dict
    provenance: dict
    status: str


def build_extraction_graph(*, settings=None, ocr=None, extractor=None, validator=None):
    def azure_node(state):
        config = settings or get_settings()
        output = (ocr or extract_document_from_azure)(state["document_path"], settings=config)
        return {"azure_output": output}

    def llm_node(state):
        agent = extractor or ExtractionAgent(settings=settings or get_settings())
        try:
            extracted = agent.extract(state["azure_output"]["raw_text"])
        finally:
            if extractor is None:
                agent.close()
        return {"extracted_data": extracted, "confidence": extracted["confidence"]}

    def validation_node(state):
        config = settings or get_settings()
        agent = validator or ValidationAgent(settings=config)
        try:
            claim, result, outcome = normalize_and_validate(
                state["extracted_data"], validator=agent, settings=config
            )
        finally:
            if validator is None:
                agent.close()
        return {
            "normalized_data": claim.model_dump(mode="json"),
            "validation": result.model_dump(mode="json"),
            "status": outcome,
            "provenance": {
                "provider": config.llm_provider,
                "model": config.llm_model,
                "azure_model": config.azure_document_model,
                "prompt_version": "m1.1",
                "schema_version": "m1.1",
                "confidence_threshold": config.extraction_confidence_threshold,
                "ocr_evidence": state["azure_output"].get("evidence", {}),
            },
        }

    workflow = StateGraph(ExtractionState)
    workflow.add_node("ocr", azure_node)
    workflow.add_node("extract", llm_node)
    workflow.add_node("validate", validation_node)
    workflow.set_entry_point("ocr")
    workflow.add_edge("ocr", "extract")
    workflow.add_edge("extract", "validate")
    workflow.add_edge("validate", END)
    return workflow.compile()


extraction_graph = build_extraction_graph()
