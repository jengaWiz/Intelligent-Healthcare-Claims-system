import os
from typing import Dict, Any, List
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence.models import AnalyzeResult

def extract_document_from_azure(file_path: str) -> Dict[str, Any]:
    """
    Extracts data from a document using Azure Document Intelligence (formerly Form Recognizer).
    
    Args:
        file_path: Path to the file to be extracted.
        
    Returns:
        A dictionary containing raw text, key-value pairs, and tables.
    """
    endpoint = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT")
    key = os.getenv("AZURE_DOCUMENT_INTELLIGENCE_KEY")

    if not endpoint or not key:
        raise ValueError("Azure Document Intelligence credentials not found. Please set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_DOCUMENT_INTELLIGENCE_KEY.")

    client = DocumentIntelligenceClient(
        endpoint=endpoint, 
        credential=AzureKeyCredential(key)
    )

    with open(file_path, "rb") as f:
        # Using prebuilt-document model for general extraction
        poller = client.begin_analyze_document(
            "prebuilt-document", 
            analyze_request=f,
            content_type="application/octet-stream"
        )
    
    result: AnalyzeResult = poller.result()

    # Extract content
    raw_text = result.content

    # Extract KV pairs
    key_value_pairs = {}
    if result.key_value_pairs:
        for kv in result.key_value_pairs:
            if kv.key and kv.value:
                key_value_pairs[kv.key.content] = kv.value.content

    # Extract tables
    tables = []
    if result.tables:
        for table in result.tables:
            table_data = []
            for cell in table.cells:
                table_data.append({
                    "row_index": cell.row_index,
                    "column_index": cell.column_index,
                    "content": cell.content
                })
            tables.append(table_data)

    return {
        "raw_text": raw_text,
        "key_value_pairs": key_value_pairs,
        "tables": tables,
        "confidence": 1.0 # Placeholder as Azure provides per-field confidence
    }
