import io
from typing import Dict, Any, Optional
import pypdf
import requests
from bs4 import BeautifulSoup

class ExtractionResult:
    def __init__(self, text: str, metadata: Dict[str, Any]):
        self.text = text
        self.metadata = metadata

class ExtractionService:
    @staticmethod
    def extract_from_text(text: str, metadata: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        if not text or not text.strip():
            raise ValueError("Empty text provided")
        return ExtractionResult(text=text, metadata=metadata or {})

    @staticmethod
    def extract_from_pdf(file_content: bytes, metadata: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        if not file_content:
            raise ValueError("Empty PDF file provided")
            
        try:
            reader = pypdf.PdfReader(io.BytesIO(file_content))
        except Exception as e:
            raise ValueError(f"Invalid PDF file: {str(e)}")
            
        full_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                full_text.append(text)
                
        if not full_text:
            raise ValueError("Could not extract any text from the PDF")
            
        final_text = "\n\n".join(full_text)
        
        meta = metadata or {}
        meta.update({
            "num_pages": len(reader.pages),
            "source_type": "pdf"
        })
        
        return ExtractionResult(text=final_text, metadata=meta)

    @staticmethod
    def extract_from_url(url: str, metadata: Optional[Dict[str, Any]] = None) -> ExtractionResult:
        if not url:
            raise ValueError("Empty URL provided")
            
        from app.core.config import settings
        from app.core.url_safety import safe_get

        try:
            # safe_get validates the URL and every redirect hop against SSRF rules
            # (UnsafeURLError is a ValueError and propagates as an ingestion failure).
            response = safe_get(url, timeout=15, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
            }, allow_private=settings.ALLOW_PRIVATE_URL_INGESTION)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise ValueError(f"Failed to fetch URL: {str(e)}")
            
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Remove script, style, header, footer, nav tags
        for element in soup(["script", "style", "header", "footer", "nav", "aside"]):
            element.decompose()
            
        text = soup.get_text(separator='\n', strip=True)
        if not text:
            raise ValueError("No text could be extracted from the URL")
            
        title = soup.title.string if soup.title else url
            
        meta = metadata or {}
        meta.update({
            "source_url": url,
            "title": title.strip() if title else url,
            "source_type": "url"
        })
        
        return ExtractionResult(text=text, metadata=meta)
