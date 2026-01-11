import pytest
from unittest.mock import MagicMock, patch
from extractors.azure_extractor import extract_document_from_azure

def test_extract_document_from_azure_success():
    """Test successful extraction with mocked Azure client."""
    with patch("extractors.azure_extractor.DocumentIntelligenceClient") as MockClient:
        with patch("extractors.azure_extractor.AzureKeyCredential") as MockCred:
            with patch("builtins.open", new_callable=MagicMock) as mock_open:
                with patch("os.getenv") as mock_getenv:
                    # Setup mocks
                    mock_getenv.side_effect = lambda k: "fake_val" if k in ["AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", "AZURE_DOCUMENT_INTELLIGENCE_KEY"] else None
                    
                    mock_client_instance = MockClient.return_value
                    mock_poller = MagicMock()
                    mock_result = MagicMock()
                    
                    mock_client_instance.begin_analyze_document.return_value = mock_poller
                    mock_poller.result.return_value = mock_result
                    
                    # Mock result content
                    mock_result.content = "Raw text content"
                    
                    # Mock KV pairs
                    kv1 = MagicMock()
                    kv1.key.content = "Name"
                    kv1.value.content = "John"
                    mock_result.key_value_pairs = [kv1]
                    
                    # Mock tables
                    table1 = MagicMock()
                    cell1 = MagicMock()
                    cell1.row_index = 0
                    cell1.column_index = 0
                    cell1.content = "Header"
                    table1.cells = [cell1]
                    mock_result.tables = [table1]
                    
                    # Run extraction
                    result = extract_document_from_azure("dummy.pdf")
                    
                    # Assertions
                    assert result["raw_text"] == "Raw text content"
                    assert result["key_value_pairs"] == {"Name": "John"}
                    assert len(result["tables"]) == 1
                    assert result["tables"][0][0]["content"] == "Header"

def test_extract_document_from_azure_missing_creds():
    """Test extraction fails when credentials are missing."""
    with patch("os.getenv", return_value=None):
        with pytest.raises(ValueError, match="credentials not found"):
            extract_document_from_azure("dummy.pdf")
