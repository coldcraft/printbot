"""
Fetcher — URL scraping and content extraction
"""

import httpx
import asyncio
from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse

from logger import setup_logger

logger = setup_logger(__name__)

class Fetcher:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.max_content_length = 50000  # 50KB max per page
    
    async def fetch_and_summarize(self, url: str) -> Optional[str]:
        """
        Fetch a URL and extract main content.
        Returns cleaned text for Ollama summarization.
        """
        try:
            # Validate URL
            parsed = urlparse(url)
            if not parsed.scheme:
                url = f"https://{url}"
            
            logger.debug(f"Fetching URL: {url}")
            
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                if response.status_code != 200:
                    logger.warning(f"URL returned status {response.status_code}: {url}")
                    return None
                
                # Check content length
                content_length = len(response.content)
                if content_length > self.max_content_length:
                    logger.warning(f"Page too large ({content_length} bytes), truncating")
                    content = response.content[:self.max_content_length]
                else:
                    content = response.content
                
                # Extract text with BeautifulSoup
                text = self._extract_text(content)
                logger.info(f"Fetched {len(text)} chars from {url}")
                return text
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def _extract_text(self, html: bytes) -> str:
        """Extract main text from HTML"""
        try:
            soup = BeautifulSoup(html, 'html.parser')
            
            # Remove script and style elements
            for script in soup(["script", "style"]):
                script.decompose()
            
            # Get text
            text = soup.get_text(separator='\n', strip=True)
            
            # Clean up whitespace
            lines = [line.strip() for line in text.split('\n') if line.strip()]
            cleaned = '\n'.join(lines)
            
            return cleaned[:5000]  # Limit to 5000 chars
        except Exception as e:
            logger.error(f"Error extracting text from HTML: {e}")
            return ""

    async def fetch_title(self, url: str) -> Optional[str]:
        """Fetch just the page title"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(url)
                soup = BeautifulSoup(response.content, 'html.parser')
                title = soup.find('title')
                return title.string if title else None
        except Exception as e:
            logger.debug(f"Could not fetch title from {url}: {e}")
            return None
