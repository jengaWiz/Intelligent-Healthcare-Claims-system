import pytest
from unittest.mock import MagicMock, patch
from agents.extraction_agent import ExtractionAgent
from agents.graphs.extraction_graph import extraction_graph, route_based_on_confidence

def test_extraction_agent_mock_google():
    """Test ExtractionAgent with mocked Google LLM (default)."""
    with patch("agents.extraction_agent.ChatGoogleGenerativeAI") as MockChat:
        mock_llm = MockChat.return_value
        mock_llm.invoke.return_value = MagicMock() 
        
        agent = ExtractionAgent() # Should use google by default
        assert agent.llm == mock_llm

def test_extraction_agent_mock_openai():
    """Test ExtractionAgent with mocked OpenAI LLM."""
    with patch("agents.extraction_agent.ChatOpenAI") as MockChat:
        mock_llm = MockChat.return_value
        mock_llm.invoke.return_value = MagicMock() 
        
        agent = ExtractionAgent(provider="openai")
        assert agent.llm == mock_llm

def test_extraction_graph_routing():
    """Test the conditional routing logic of the graph."""
    
    # Test auto-approve
    state_approve = {"status": "APPROVED"}
    assert route_based_on_confidence(state_approve) == "auto_approve"
    
    # Test flag for review
    state_review = {"status": "FLAGGED_FOR_REVIEW"}
    assert route_based_on_confidence(state_review) == "flag_review"

def test_extraction_graph_execution():
    """Test the full graph execution with mocks."""
    
    with patch("agents.graphs.extraction_graph.extract_document_from_azure") as mock_azure:
        mock_azure.return_value = {"raw_text": "test"}
        
        with patch("agents.graphs.extraction_graph.ExtractionAgent") as MockAgent:
            mock_agent_instance = MockAgent.return_value
            mock_agent_instance.extract.return_value = {
                "patient_name": "Test",
                "confidence": 0.9,
                "reasoning": "Clear"
            }
            
            initial_state = {
                "document_path": "test.pdf",
                "azure_output": {},
                "extracted_data": {},
                "confidence": 0.0,
                "status": "PENDING"
            }
            
            result = extraction_graph.invoke(initial_state)
            
            assert result["status"] == "APPROVED"
            assert result["extracted_data"]["patient_name"] == "Test"
