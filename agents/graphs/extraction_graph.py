from typing import Any, Dict, Literal, TypedDict

from langgraph.graph import END, StateGraph

from agents.extraction_agent import ExtractionAgent
from config.settings import get_settings
from extractors.azure_extractor import extract_document_from_azure


class ExtractionState(TypedDict):
    document_path: str
    azure_output: Dict[str, Any]
    extracted_data: Dict[str, Any]
    confidence: float
    status: str


def azure_extract_node(state: ExtractionState) -> Dict[str, Any]:
    """Node to run Azure extraction."""
    path = state["document_path"]
    azure_result = extract_document_from_azure(path)
    return {"azure_output": azure_result}


def llm_extract_node(state: ExtractionState) -> Dict[str, Any]:
    """Node to run LLM extraction agent."""
    azure_data = state["azure_output"]
    raw_text = azure_data.get("raw_text", "")

    agent = ExtractionAgent()
    try:
        extracted = agent.extract(raw_text)
    finally:
        agent.close()

    return {"extracted_data": extracted, "confidence": extracted.get("confidence", 0.0)}


def confidence_check_node(state: ExtractionState) -> Dict[str, Any]:
    """Node to check confidence and determine status."""
    confidence = state["confidence"]
    if confidence >= get_settings().extraction_confidence_threshold:
        return {"status": "APPROVED"}
    else:
        return {"status": "FLAGGED_FOR_REVIEW"}


def route_based_on_confidence(state: ExtractionState) -> Literal["auto_approve", "flag_review"]:
    """Conditional routing logic."""
    if state["status"] == "APPROVED":
        return "auto_approve"
    else:
        return "flag_review"


# Define the graph
workflow = StateGraph(ExtractionState)

# Add nodes
workflow.add_node("azure_extract", azure_extract_node)
workflow.add_node("llm_extract", llm_extract_node)
workflow.add_node("confidence_check", confidence_check_node)

# Set entry point
workflow.set_entry_point("azure_extract")

# Add edges
workflow.add_edge("azure_extract", "llm_extract")
workflow.add_edge("llm_extract", "confidence_check")

# Conditional edges
workflow.add_conditional_edges(
    "confidence_check", route_based_on_confidence, {"auto_approve": END, "flag_review": END}
)

# Compile the graph
extraction_graph = workflow.compile()
