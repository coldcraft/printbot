"""Utilities for fetching short factual snippets to help answer questions."""

from __future__ import annotations

from typing import List, Optional, Union
from urllib.parse import unquote, urlparse

import httpx

from logger import setup_logger

logger = setup_logger(__name__)


class QuestionContextFetcher:
    """Fetch small factual blurbs for general knowledge questions."""

    DUCKDUCKGO_ENDPOINT = "https://api.duckduckgo.com/"
    WIKIPEDIA_SUMMARY_TEMPLATE = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"

    def __init__(self, timeout: int = 6, max_chars: int = 1200):
        self.timeout = timeout
        self.max_chars = max(200, max_chars)
        self.user_agent = (
            "PrintBot/1.0 (+https://github.com/jacobshavlik/printbot; info@printbot.local)"
        )

    async def fetch_context(self, question: str) -> Optional[str]:
        query = (question or "").strip()
        if len(query) < 6:
            return None

        try:
            async with httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
                follow_redirects=True,
            ) as client:
                params = {
                    "q": query,
                    "format": "json",
                    "no_html": "1",
                    "skip_disambig": "1",
                }
                response = await client.get(self.DUCKDUCKGO_ENDPOINT, params=params)
                response.raise_for_status()
                payload = response.json()

                parts: List[str] = []
                abstract = self._clean_text(payload.get("AbstractText"))
                if abstract:
                    parts.append(abstract)

                if not parts:
                    related = self._collect_related_topics(payload.get("RelatedTopics"))
                    parts.extend(related)

                wiki_summary = await self._maybe_fetch_wikipedia_summary(
                    payload.get("AbstractURL"), client
                )
                if wiki_summary:
                    parts.append(wiki_summary)

                combined = self._combine_parts(parts)
                if combined:
                    logger.debug(
                        "Question context fetched %.0f chars for query='%s'",
                        len(combined),
                        query[:80],
                    )
                return combined
        except httpx.HTTPError as exc:
            logger.debug("Question context HTTP error: %s", exc)
            return None
        except Exception as exc:  # pragma: no cover
            logger.warning("Question context fetch failed: %s", exc)
            return None

    def _collect_related_topics(self, raw_topics: Union[List, None]) -> List[str]:
        results: List[str] = []

        def _traverse(node: Union[List, dict, None]):
            if not node or len(results) >= 3:
                return
            if isinstance(node, list):
                for item in node:
                    if len(results) >= 3:
                        break
                    _traverse(item)
            elif isinstance(node, dict):
                text = self._clean_text(node.get("Text") or node.get("Result"))
                if text:
                    results.append(text)
                for key in ("Topics", "RelatedTopics"):
                    child = node.get(key)
                    if isinstance(child, list):
                        _traverse(child)

        _traverse(raw_topics)
        return results

    async def _maybe_fetch_wikipedia_summary(
        self, url: Optional[str], client: httpx.AsyncClient
    ) -> Optional[str]:
        if not url or "wikipedia.org" not in url:
            return None

        parsed = urlparse(url)
        title = parsed.path.rsplit("/", 1)[-1]
        if not title:
            return None
        summary_url = self.WIKIPEDIA_SUMMARY_TEMPLATE.format(title=unquote(title))
        try:
            response = await client.get(summary_url)
            response.raise_for_status()
            data = response.json()
            extract = self._clean_text(data.get("extract"))
            return extract
        except Exception as exc:
            logger.debug("Wikipedia summary fetch failed: %s", exc)
            return None

    def _combine_parts(self, parts: List[str]) -> Optional[str]:
        cleaned = [p.strip() for p in parts if p]
        if not cleaned:
            return None
        combined = "\n".join(dict.fromkeys(cleaned))
        if len(combined) <= self.max_chars:
            return combined
        truncated = combined[: self.max_chars]
        last_space = truncated.rfind(" ")
        if last_space > 200:
            truncated = truncated[:last_space]
        return truncated.strip() or None

    @staticmethod
    def _clean_text(value: Optional[str]) -> Optional[str]:
        if not isinstance(value, str):
            return None
        cleaned = " ".join(value.split())
        return cleaned if cleaned else None
