"""
Fetcher — URL scraping and content extraction
"""

import httpx
import asyncio
import json
from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse

try:
    import trafilatura
except ImportError:  # pragma: no cover
    trafilatura = None

from logger import setup_logger

logger = setup_logger(__name__)

class Fetcher:
    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.max_content_length = 50000  # 50KB max per page
        self.request_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        }
    
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
            
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=self.request_headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                
                if response.status_code != 200:
                    logger.warning(f"URL returned status {response.status_code}: {url}")
                    return None
                
                # Check content length
                html_text = response.text or ""
                content_length = len(html_text)
                if content_length > self.max_content_length:
                    logger.warning(f"Page too large ({content_length} bytes), truncating")
                    html_text = html_text[:self.max_content_length]
                else:
                    html_text = html_text
                
                # Extract text with BeautifulSoup
                text = self._extract_text(html_text)
                logger.info(f"Fetched {len(text)} chars from {url}")
                return text
        
        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return None

    def _extract_with_trafilatura(self, html: str) -> Optional[str]:
        """Use trafilatura for article-aware extraction. Returns None if unavailable or empty."""
        if not trafilatura:
            return None
        try:
            extracted = trafilatura.extract(
                html,
                favor_recall=True,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
            )
            if not extracted:
                return None
            cleaned = extracted.strip()
            if len(cleaned) < 200:
                return None  # Let BS4 fallback try harder for sparse pages
            return cleaned[:5000]
        except Exception as e:
            logger.debug(f"trafilatura extraction error: {e}")
            return None

    def _extract_text(self, html: str) -> str:
        """Extract main text from HTML.
        Prefers trafilatura (article-aware); falls back to BeautifulSoup heuristics."""
        traf_text = self._extract_with_trafilatura(html)
        if traf_text:
            logger.debug(f"trafilatura extracted {len(traf_text)} chars")
            return traf_text

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

            if len(cleaned) < 400:
                fallback_lines = []

                jsonld_texts = self._extract_jsonld_texts(soup)
                fallback_lines.extend(jsonld_texts)

                title_tag = soup.find('title')
                if title_tag and title_tag.get_text(strip=True):
                    fallback_lines.append(title_tag.get_text(strip=True))

                for attr in ("description", "og:description", "twitter:description"):
                    meta = soup.find("meta", attrs={"name": attr}) or soup.find("meta", attrs={"property": attr})
                    if meta and meta.get("content"):
                        fallback_lines.append(meta.get("content").strip())

                article = soup.find("article")
                paragraph_nodes = article.find_all("p") if article else soup.find_all("p")
                for node in paragraph_nodes[:15]:
                    value = node.get_text(" ", strip=True)
                    if value and len(value) > 40:
                        fallback_lines.append(value)

                fallback_cleaned = "\n".join(dict.fromkeys(fallback_lines))
                if len(fallback_cleaned) > len(cleaned):
                    cleaned = fallback_cleaned
            
            return cleaned[:5000]  # Limit to 5000 chars
        except Exception as e:
            logger.error(f"Error extracting text from HTML: {e}")
            return ""

    def _extract_jsonld_texts(self, soup: BeautifulSoup) -> list[str]:
        collected: list[str] = []

        def _collect_fields(node):
            if isinstance(node, dict):
                for key in ("headline", "description", "articleBody", "name"):
                    value = node.get(key)
                    if isinstance(value, str) and len(value.strip()) > 20:
                        collected.append(value.strip())
                for value in node.values():
                    _collect_fields(value)
            elif isinstance(node, list):
                for item in node:
                    _collect_fields(item)

        for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
            payload = script.string or script.get_text(strip=True)
            if not payload:
                continue
            try:
                data = json.loads(payload)
                _collect_fields(data)
            except Exception:
                continue

        return list(dict.fromkeys(collected))

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
