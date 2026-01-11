from typing import Optional, List, Literal
from pydantic import BaseModel, Field
from langchain_openai import ChatOpenAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import PydanticOutputParser

class ExtractedData(BaseModel):
    patient_name: Optional[str] = Field(description="Name of the patient")
    patient_dob: Optional[str] = Field(description="Date of birth of the patient")
    provider_name: Optional[str] = Field(description="Name of the healthcare provider")
    service_date: Optional[str] = Field(description="Date of service")
    total_amount: Optional[str] = Field(description="Total amount charged")
    confidence: float = Field(description="Confidence score of the extraction (0.0 to 1.0)")
    reasoning: str = Field(description="Explanation of why these values were extracted")

class ExtractionAgent:
    def __init__(self, provider: Literal["openai", "google"] = "google", model_name: str = "gemini-1.5-pro"):
        """
        Initialize the extraction agent with a specific provider and model.
        
        Args:
            provider: The LLM provider ("openai" or "google"). Defaults to "google".
            model_name: The model name to use. Defaults to "gemini-1.5-pro".
        """
        if provider == "openai":
            self.llm = ChatOpenAI(model=model_name, temperature=0)
        elif provider == "google":
            self.llm = ChatGoogleGenerativeAI(model=model_name, temperature=0)
        else:
            raise ValueError(f"Unsupported provider: {provider}")
            
        self.parser = PydanticOutputParser(pydantic_object=ExtractedData)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", "You are an AI agent responsible for extracting structured data from healthcare claim documents.\n\n"
                       "Your task is to extract the following fields and return ONLY valid JSON:\n"
                       "- patient_name (string or null)\n"
                       "- patient_dob (string or null)\n"
                       "- provider_name (string or null)\n"
                       "- service_date (ISO date string or null)\n"
                       "- total_amount (number or null)\n"
                       "- confidence (number between 0 and 1)\n"
                       "- reasoning (short explanation of extraction quality)\n\n"
                       "Rules:\n"
                       "- Do NOT guess missing values.\n"
                       "- If a field is not explicitly present, return null.\n"
                       "- Base all outputs strictly on the provided text.\n"
                       "- If the document is unclear or incomplete, lower the confidence score and explain why.\n\n"
                       "Healthcare claims typically include patient details, provider information, dates of service, and billed amounts.\n\n"
                       "{format_instructions}"),
            ("user", "Document text:\n{raw_text}")
        ])

    def extract(self, document_text: str) -> dict:
        """
        Extracts structured data from raw document text using an LLM.

        Args:
            document_text: The raw text from the document.

        Returns:
            A dictionary containing the extracted fields, confidence, and reasoning.
        """
        chain = self.prompt | self.llm | self.parser
        
        try:
            result = chain.invoke({
                "raw_text": document_text,
                "format_instructions": self.parser.get_format_instructions()
            })
            return result.model_dump()
        except Exception as e:
            # Fallback or error handling
            return {
                "error": str(e),
                "confidence": 0.0,
                "reasoning": "Extraction failed due to an error."
            }
