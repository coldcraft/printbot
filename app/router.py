"""
Router — Orchestrates Ollama calls, intent parsing, rate limiting.
Core of the TextBee → Ollama → Printer loop.
"""

import os
import json
import time
import asyncio
import hashlib
import re
import httpx
from datetime import datetime, timedelta
from collections import defaultdict, OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

from logger import setup_logger
from printer import Printer
from mock_printer import MockPrinter
from fetcher import Fetcher
from question_context import QuestionContextFetcher

if TYPE_CHECKING:
    from job_queue import JobQueue

logger = setup_logger(__name__)

QUESTION_META_PREFIX = re.compile(r"^\s*(?:the\s+)?user\s+is\s+asking\b[:\s-]*", re.IGNORECASE)
QUESTION_STRIP_CHARS = " :.-\n\t"


class _MessageDeduper:
    """Bounded LRU + TTL dedupe for webhook deliveries."""

    def __init__(self, ttl_seconds: int = 600, max_entries: int = 256):
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._seen: "OrderedDict[str, float]" = OrderedDict()

    def _purge(self, now: float) -> None:
        expiry = now - self.ttl_seconds
        while self._seen:
            key, ts = next(iter(self._seen.items()))
            if ts < expiry:
                self._seen.popitem(last=False)
            else:
                break
        while len(self._seen) > self.max_entries:
            self._seen.popitem(last=False)

    def seen_or_record(self, phone: str, message: str, timestamp: Optional[str]) -> bool:
        now = time.time()
        self._purge(now)
        digest = hashlib.sha256(
            f"{phone}|{message}|{timestamp or ''}".encode("utf-8")
        ).hexdigest()
        if digest in self._seen:
            return True
        self._seen[digest] = now
        return False


class Router:
    def __init__(self):
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
        self.ollama_keep_alive = os.getenv("OLLAMA_KEEP_ALIVE", "30m")
        self.printer = None
        self.printer_connected = False
        self.job_queue: Optional["JobQueue"] = None
        
        # Rate limiting: {phone: (count, first_message_time)}
        self.rate_limit_state: Dict[str, Tuple[int, float]] = defaultdict(lambda: (0, 0))
        self.rate_limit_messages = int(os.getenv("RATE_LIMIT_MESSAGES", 5))
        self.rate_limit_window = int(os.getenv("RATE_LIMIT_WINDOW_MINUTES", 3)) * 60  # to seconds
        self.rate_limit_cooldown = int(os.getenv("RATE_LIMIT_COOLDOWN_MINUTES", 15)) * 60  # to seconds
        
        # Retry settings
        self.retry_attempts = int(os.getenv("RETRY_ATTEMPTS", 3))
        self.retry_delay = int(os.getenv("RETRY_DELAY_SECONDS", 2))
        self.retry_timeout = int(os.getenv("RETRY_TIMEOUT_SECONDS", 30))
        self.url_fetch_timeout = int(os.getenv("URL_FETCH_TIMEOUT_SECONDS", 12))
        self.url_summary_source_chars = int(os.getenv("URL_SUMMARY_SOURCE_CHARS", 4500))
        self.fetcher = Fetcher(timeout=self.url_fetch_timeout)
        question_context_flag = os.getenv("QUESTION_CONTEXT_ENABLED", "true").strip().lower()
        self.question_context_enabled = question_context_flag not in {"0", "false", "no", "off"}
        self.question_context_max_chars = int(os.getenv("QUESTION_CONTEXT_MAX_CHARS", 1200))
        question_context_timeout = int(os.getenv("QUESTION_CONTEXT_TIMEOUT_SECONDS", 6))
        self.question_context_fetcher = (
            QuestionContextFetcher(
                timeout=question_context_timeout,
                max_chars=self.question_context_max_chars,
            )
            if self.question_context_enabled
            else None
        )
        self.queue_worker_interval = int(os.getenv("QUEUE_WORKER_INTERVAL_SECONDS", 10))
        self._queue_worker_task: Optional[asyncio.Task] = None
        self._process_queue_lock: Optional[asyncio.Lock] = None
        self._print_lock: Optional[asyncio.Lock] = None
        self.system_prompt_override = os.getenv("SYSTEM_PROMPT_PATH", "").strip()
        self.contacts_path = os.getenv("CONTACTS_PATH", "").strip()
        self._contacts_cache: Dict[str, str] = {}
        self._contacts_mtime: Optional[float] = None
        self._load_contacts_map(force=True)

        dedupe_ttl = int(os.getenv("WEBHOOK_DEDUPE_TTL_SECONDS", 600))
        self.deduper = _MessageDeduper(ttl_seconds=dedupe_ttl)

        logger.info(f"Router initialized: Ollama={self.ollama_host}, Model={self.ollama_model}")

    def is_duplicate_message(
        self, phone: str, message: str, timestamp: Optional[str]
    ) -> bool:
        """Return True if this exact webhook delivery was already seen recently."""
        return self.deduper.seen_or_record(phone, message, timestamp)

    async def process_message(
        self, message: str, sender: str, timestamp: str
    ) -> Optional[str]:
        """Parse, enqueue, and print a single inbound message. Runs off the webhook hot path."""
        try:
            print_job = await self.parse_and_format(
                message=message, sender=sender, timestamp=timestamp
            )
            if not print_job:
                logger.error(f"Failed to parse message from {sender}")
                return None

            if not self.job_queue:
                logger.error("Cannot process message: no job queue attached")
                return None

            job_id = await self.job_queue.add_job(print_job)
            logger.info(f"Job {job_id} queued from {sender}")
            await self.print_job(print_job)
            return job_id
        except Exception as e:
            logger.error(f"process_message failed for {sender}: {e}", exc_info=True)
            return None

    def set_job_queue(self, job_queue: "JobQueue"):
        """Inject job queue to enable cleanup on successful prints."""
        self.job_queue = job_queue

    async def connect_printer(self):
        """Initialize printer connection"""
        try:
            printer_ip = os.getenv("PRINTER_IP")
            printer_port = int(os.getenv("PRINTER_PORT", 9100))
            
            if not printer_ip:
                logger.warning("PRINTER_IP not set, printer will be offline until configured")
                self.printer_connected = False
                return
            
            # Use MockPrinter for localhost (simulator), real Printer for remote IPs
            if printer_ip == "127.0.0.1" or printer_ip == "localhost":
                logger.info("Using MockPrinter (simulator mode)")
                self.printer = MockPrinter(printer_ip, printer_port)
            else:
                self.printer = Printer(printer_ip, printer_port)
            
            await self.printer.connect()
            self.printer_connected = True
            logger.info(f"Printer connected: {printer_ip}:{printer_port}")
        except Exception as e:
            logger.error(f"Failed to connect to printer: {e}")
            self.printer_connected = False

    async def disconnect_printer(self):
        """Close printer connection"""
        if self.printer:
            await self.printer.disconnect()
            self.printer_connected = False
            logger.info("Printer disconnected")

    def check_rate_limit(self, phone: str) -> Tuple[bool, int]:
        """
        Check if phone number has exceeded rate limits.
        Returns: (is_rate_limited, cooldown_seconds)
        """
        now = time.time()
        count, first_time = self.rate_limit_state[phone]
        
        # Reset counter if outside window or never set
        if first_time == 0 or now - first_time > self.rate_limit_window:
            self.rate_limit_state[phone] = (1, now)
            logger.debug(f"Rate limit reset for {phone}")
            return False, 0
        
        # Check if in cooldown after hitting limit
        cooldown_expires = first_time + self.rate_limit_window + self.rate_limit_cooldown
        if count >= self.rate_limit_messages and now < cooldown_expires:
            remaining = int(cooldown_expires - now)
            logger.warning(f"Rate limit cooldown for {phone}: {remaining}s remaining")
            return True, remaining

        # Cooldown expired; start new window
        if count >= self.rate_limit_messages and now >= cooldown_expires:
            self.rate_limit_state[phone] = (1, now)
            logger.debug(f"Rate limit window reopened for {phone}")
            return False, 0
        
        # Increment counter
        self.rate_limit_state[phone] = (count + 1, first_time)
        
        logger.debug(f"Rate limit check for {phone}: {count + 1}/{self.rate_limit_messages}")
        return False, 0

    async def parse_and_format(self, message: str, sender: str, timestamp: str) -> Optional[Dict]:
        """
        Send message to Ollama with system prompt.
        Ollama returns JSON with intent_type and formatted content.
        """
        try:
            message_url = self._extract_first_url(message)
            if message_url:
                url_job = await self._parse_url_message(message=message, sender=sender, timestamp=timestamp, url=message_url)
                if url_job:
                    logger.info(f"Parsed job: intent={url_job.get('intent_type')}, from={sender}")
                    return url_job
                logger.warning("URL-specific parsing failed; falling back to generic parser")

            # Load system prompt
            system_prompt = self._load_system_prompt()

            augmented_prompt = message
            question_context_snippet: Optional[str] = None
            if (
                self.question_context_enabled
                and self.question_context_fetcher
                and self._looks_like_question(message)
            ):
                try:
                    question_context_snippet = await self.question_context_fetcher.fetch_context(message)
                except Exception as context_error:  # pragma: no cover
                    logger.warning("Question context fetch raised error: %s", context_error)
                    question_context_snippet = None
                if question_context_snippet:
                    augmented_prompt = self._build_question_prompt(message, question_context_snippet)
                    logger.debug(
                        "Augmented question from %s with %d chars of context",
                        sender,
                        len(question_context_snippet),
                    )

            logger.debug(
                "Sending to Ollama: from=%s, length=%d, augmented=%s",
                sender,
                len(augmented_prompt),
                bool(question_context_snippet),
            )

            # Call Ollama with retries (intent parser must return JSON)
            response_text = await self._call_ollama_with_retry(
                system_prompt, augmented_prompt, force_json=True
            )

            if not response_text:
                logger.error(
                    f"Ollama unreachable for message from {sender}; using raw fallback"
                )
                return self._build_fallback_job(message=message, sender=sender, timestamp=timestamp)

            # Extract JSON from response
            print_job = self._extract_json_from_ollama(response_text)

            if not print_job:
                logger.error(
                    f"Could not parse JSON from Ollama response: {response_text[:200]}; using raw fallback"
                )
                return self._build_fallback_job(message=message, sender=sender, timestamp=timestamp)

            intent_type = str(print_job.get("intent_type", "generic")).strip().lower() or "generic"
            print_job["intent_type"] = intent_type
            print_job["content"] = self._sanitize_content(
                intent_type=intent_type,
                content=print_job.get("content", ""),
                original_message=message,
            )

            metadata = self._normalize_metadata(print_job.get("metadata"))
            if intent_type == "url":
                original_url = metadata.get("original_url") or metadata.get("url") or message_url
                if original_url:
                    if not original_url.startswith(("http://", "https://")):
                        original_url = f"https://{original_url}"
                    metadata["original_url"] = original_url
                    metadata.setdefault("url", original_url)
            elif intent_type == "question":
                question_text = message.strip()
                if question_text:
                    metadata["question_text"] = question_text
                if question_context_snippet:
                    metadata["context_augmented"] = True
                    metadata["context_chars"] = len(question_context_snippet)
            print_job["metadata"] = metadata
            
            # Enrich with metadata
            print_job.update({
                "sender": sender,
                "sender_display": self._resolve_sender_label(sender),
                "received_at": timestamp,
                "created_at": datetime.utcnow().isoformat(),
                # Preserve the raw inbound message so printers can always show the question
                "original_message": message,
            })
            
            logger.info(f"Parsed job: intent={print_job.get('intent_type')}, from={sender}")
            return print_job
            
        except Exception as e:
            logger.error(f"Error in parse_and_format: {e}", exc_info=True)
            return None

    def _build_fallback_job(self, message: str, sender: str, timestamp: str) -> Dict:
        """Build a generic-intent job from the raw message when LLM parsing fails.
        Ensures the printer always has SOMETHING to print, even when Ollama is down."""
        return {
            "intent_type": "generic",
            "content": (message or "").strip(),
            "metadata": {"ollama_failed": True},
            "sender": sender,
            "sender_display": self._resolve_sender_label(sender),
            "received_at": timestamp,
            "created_at": datetime.utcnow().isoformat(),
            "original_message": message,
        }

    async def _parse_url_message(self, message: str, sender: str, timestamp: str, url: str) -> Optional[Dict]:
        try:
            normalized_url = url if url.startswith(("http://", "https://")) else f"https://{url}"
            page_text = await self.fetcher.fetch_and_summarize(normalized_url)
            source_excerpt = (page_text or "")[:self.url_summary_source_chars]

            summary_text = await self._call_ollama_with_retry(
                self._url_system_prompt(),
                self._build_url_prompt(normalized_url, message, source_excerpt),
            )

            if not summary_text:
                return None

            summary_text = self._clean_summary_text(summary_text)
            summary_text = self._ensure_url_paragraphs(summary_text)

            metadata = {}
            metadata["original_url"] = normalized_url
            metadata.setdefault("url", normalized_url)
            metadata["source_excerpt_chars"] = len(source_excerpt)

            print_job = {
                "intent_type": "url",
                "content": summary_text,
                "metadata": metadata,
                "sender": sender,
                "sender_display": self._resolve_sender_label(sender),
                "received_at": timestamp,
                "created_at": datetime.utcnow().isoformat(),
                "original_message": message,
            }

            return print_job
        except Exception as e:
            logger.error(f"Error in URL parsing flow: {e}", exc_info=True)
            return None

    def _url_system_prompt(self) -> str:
        return """You are PrintBot's URL summarizer.
Given a URL and extracted article text, produce summary text only (no JSON).

Rules:
- Write 2 to 3 paragraphs if source details are available.
- Each paragraph should be 2-4 sentences.
- Focus on concrete, relevant facts and impact.
- Avoid fluff, clickbait language, or generic statements.
- If source text is sparse, provide the best concise summary possible.
- Do not include markdown, bullet points, or headings."""

    def _build_url_prompt(self, url: str, user_message: str, source_excerpt: str) -> str:
        excerpt = source_excerpt.strip()
        if not excerpt:
            excerpt = "SOURCE_TEXT_UNAVAILABLE"

        return (
            f"URL: {url}\n"
            f"USER_MESSAGE: {user_message}\n"
            "ARTICLE_TEXT_START\n"
            f"{excerpt}\n"
            "ARTICLE_TEXT_END"
        )

    def _ensure_url_paragraphs(self, content: str) -> str:
        text = (content or "").strip()
        if not text:
            return text

        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(paragraphs) >= 2:
            return text

        sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        if len(sentences) < 2:
            return text

        split_index = max(1, len(sentences) // 2)
        first = " ".join(sentences[:split_index]).strip()
        second = " ".join(sentences[split_index:]).strip()
        if not second:
            return text

        return f"{first}\n\n{second}"

    def _clean_summary_text(self, text: str) -> str:
        cleaned = (text or "").strip()
        cleaned = re.sub(r"^```(?:text|markdown)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        cleaned = re.sub(r"^\s*summary\s*:\s*", "", cleaned, flags=re.IGNORECASE)
        return cleaned.strip()

    def _looks_like_question(self, text: str) -> bool:
        if not isinstance(text, str):
            return False
        stripped = text.strip()
        if not stripped:
            return False
        if stripped.endswith("?"):
            return True
        lowered = stripped.casefold()
        question_starts = (
            "who ",
            "what ",
            "when ",
            "where ",
            "why ",
            "how ",
            "is ",
            "are ",
            "do ",
            "does ",
            "can ",
            "should ",
            "could ",
            "would ",
        )
        return any(lowered.startswith(prefix) for prefix in question_starts)

    def _build_question_prompt(self, question: str, context: str) -> str:
        context_block = (context or "").strip()
        question_block = (question or "").strip()
        instruction = (
            "You are answering a single SMS question for a receipt printer. "
            "Use the context below as the primary source if it contains the answer. "
            "Otherwise, answer from your own general knowledge. "
            "Keep the answer to 1-2 short sentences. "
            "Your response content MUST start with 'ANSWER: ' followed by the actual answer. "
            "Never restate or rephrase the question in the answer."
        )
        return (
            f"{instruction}\n\n"
            f"CONTEXT:\n{context_block}\n\n"
            f"SMS_QUESTION:\n{question_block}\n"
        )

    def _load_system_prompt(self) -> str:
        """Load system prompt from file"""
        try:
            candidate_paths: List[Path] = []

            if self.system_prompt_override:
                candidate_paths.append(Path(self.system_prompt_override))

            base_dir = Path(__file__).resolve().parent
            project_root = base_dir.parent

            candidate_paths.extend([
                base_dir / "prompts" / "system.txt",      # Docker image layout
                project_root / "prompts" / "system.txt",   # Local repo layout
                Path("/prompts/system.txt"),                # Legacy mount point
            ])

            for prompt_file in candidate_paths:
                if prompt_file.exists():
                    return prompt_file.read_text(encoding='utf-8')

            logger.warning(
                "System prompt not found in any known path: %s, using default",
                [str(path) for path in candidate_paths]
            )
            return self._default_system_prompt()
        except Exception as e:
            logger.error(f"Error loading system prompt: {e}")
            return self._default_system_prompt()

    def _sanitize_content(self, intent_type: str, content: str, original_message: str) -> str:
        text = str(content or "").strip()
        fallback = str(original_message or "").strip()

        if intent_type == "generic":
            # Ensure generic prints mirror the original text exactly (no model censorship)
            return fallback or text

        if intent_type == "question":
            if not text:
                return fallback

            meta_match = QUESTION_META_PREFIX.match(text)
            if meta_match:
                remainder = text[meta_match.end():].lstrip(QUESTION_STRIP_CHARS)
                if remainder:
                    text = remainder
                else:
                    logger.warning("Question content was only metadata; falling back to original message")
                    return fallback or text

            question_clean = fallback.strip()
            if question_clean:
                text_cf = text.casefold()
                question_cf = question_clean.casefold()
                if text_cf.startswith(question_cf):
                    remainder = text[len(question_clean):].lstrip(QUESTION_STRIP_CHARS)
                    if remainder:
                        text = remainder
                    else:
                        logger.warning("Question content only repeated the prompt; falling back to original message")
                        return question_clean

        if not text:
            return fallback

        return text

    def _default_system_prompt(self) -> str:
        """Default system prompt if file not available"""
        return """You are PrintBot, an intelligent SMS-to-receipts assistant.
Your job is to parse incoming SMS messages and decide what to do with them.

Respond ONLY with valid JSON in this format:
{
  "intent_type": "reminder" | "url" | "list" | "question",
  "content": "formatted content for the receipt",
  "metadata": {any additional info}
}

Intent types:
- reminder: "do X at time Y" or just "remember X"
- url: user sent a URL
- list: "shopping list: milk, eggs, bread" or similar
- question: user asking something

Keep content concise (<100 chars per line). Format clearly for a thermal receipt printer."""

    def _extract_first_url(self, text: str) -> Optional[str]:
        if not isinstance(text, str) or not text.strip():
            return None
        match = re.search(r"(https?://\S+|www\.\S+)", text)
        if not match:
            return None
        return match.group(1).rstrip(")]}>,.;\"")

    def _normalize_metadata(self, metadata_value) -> Dict:
        if isinstance(metadata_value, dict):
            return metadata_value

        if isinstance(metadata_value, str):
            raw = metadata_value.strip()
            if not raw:
                return {}

            try:
                parsed_json = json.loads(raw)
                if isinstance(parsed_json, dict):
                    return parsed_json
            except json.JSONDecodeError:
                pass

            if raw.startswith("@{") and raw.endswith("}"):
                inner = raw[2:-1].strip()
                parsed: Dict[str, str] = {}
                if inner:
                    for part in inner.split(";"):
                        if "=" in part:
                            key, value = part.split("=", 1)
                            parsed[key.strip()] = value.strip()
                return parsed

            if re.match(r"^https?://", raw) or raw.startswith("www."):
                return {"original_url": raw, "url": raw}

        return {}

    def _load_contacts_map(self, force: bool = False):
        if not self.contacts_path:
            self._contacts_cache = {}
            self._contacts_mtime = None
            return

        try:
            contact_file = Path(self.contacts_path)
            if not contact_file.exists():
                if force:
                    logger.info(f"Contacts file {contact_file} not found; using raw sender numbers")
                self._contacts_cache = {}
                self._contacts_mtime = None
                return

            mtime = contact_file.stat().st_mtime
            if not force and self._contacts_mtime == mtime:
                return

            with contact_file.open('r', encoding='utf-8') as f:
                data = json.load(f)

            if not isinstance(data, dict):
                raise ValueError("Contacts JSON must be an object map of phone to name")

            normalized: Dict[str, str] = {}
            for raw_key, value in data.items():
                if not isinstance(raw_key, str) or not isinstance(value, str):
                    continue
                normalized_key = self._normalize_contact_key(raw_key)
                if normalized_key:
                    normalized[normalized_key] = value.strip()

            self._contacts_cache = normalized
            self._contacts_mtime = mtime
            logger.info(f"Loaded {len(normalized)} contacts from {contact_file}")
        except Exception as e:
            logger.error(f"Error loading contacts map: {e}")
            self._contacts_cache = {}
            self._contacts_mtime = None

    def _normalize_contact_key(self, phone: str) -> Optional[str]:
        if not phone:
            return None
        stripped = re.sub(r"[^\d+]", "", phone)
        if not stripped:
            return None
        if not stripped.startswith("+"):
            if stripped.startswith("00"):
                stripped = stripped[2:]
            if stripped and stripped[0].isdigit():
                stripped = f"+{stripped}"
        return stripped

    def _resolve_sender_label(self, phone: Optional[str]) -> Optional[str]:
        if not phone:
            return phone
        self._load_contacts_map()
        normalized = self._normalize_contact_key(phone)
        if not normalized:
            return phone
        return self._contacts_cache.get(normalized, phone)
    async def _call_ollama_with_retry(
        self,
        system_prompt: str,
        message: str,
        force_json: bool = False,
    ) -> Optional[str]:
        """Call Ollama with retry logic. Pass force_json=True to constrain output to JSON."""
        payload = {
            "model": self.ollama_model,
            "prompt": message,
            "system": system_prompt,
            "stream": False,
            "keep_alive": self.ollama_keep_alive,
        }
        if force_json:
            payload["format"] = "json"

        for attempt in range(self.retry_attempts):
            try:
                async with httpx.AsyncClient(timeout=self.retry_timeout) as client:
                    response = await client.post(
                        f"{self.ollama_host}/api/generate",
                        json=payload,
                        timeout=self.retry_timeout
                    )
                
                if response.status_code == 200:
                    data = response.json()
                    return data.get("response", "")
                else:
                    logger.warning(f"Ollama returned status {response.status_code}, retry {attempt + 1}/{self.retry_attempts}")
            
            except httpx.TimeoutException:
                logger.warning(f"Ollama timeout, retry {attempt + 1}/{self.retry_attempts}")
            except Exception as e:
                logger.error(f"Ollama call error (attempt {attempt + 1}): {e}")
            
            if attempt < self.retry_attempts - 1:
                await asyncio.sleep(self.retry_delay)
        
        logger.error(f"Failed to get response from Ollama after {self.retry_attempts} attempts")
        return None
    
    def _extract_json_from_ollama(self, response_text: str) -> Optional[Dict]:
        """Extract JSON from Ollama response (may contain surrounding text)"""
        def _cleanup_json_text(text: str) -> str:
            cleaned = text.strip()
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
            cleaned = self._strip_invalid_json_escapes(cleaned)
            return cleaned.strip()

        try:
            # Try direct parse first
            return json.loads(_cleanup_json_text(response_text))
        except json.JSONDecodeError:
            pass
        
        # Look for JSON object in response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(_cleanup_json_text(json_match.group()))
            except json.JSONDecodeError:
                pass
        
        logger.error(f"Could not extract JSON from: {response_text[:200]}")
        return None

    def _strip_invalid_json_escapes(self, text: str) -> str:
        """Remove stray backslash escapes (e.g. \\* inserted by LLMs) so json.loads succeeds."""
        if not text:
            return text

        invalid_escape_pattern = re.compile(r"\\([^\"\\/bfnrtu])")

        if not invalid_escape_pattern.search(text):
            return text

        sanitized = invalid_escape_pattern.sub(lambda match: match.group(1), text)
        logger.debug("Stripped invalid JSON escape sequences from Ollama response")
        return sanitized

    async def print_job(self, job: Dict):
        """
        Print a job. On success remove from queue; on failure mark for retry.
        Serialized via _print_lock so process_message and the queue worker
        can't both print the same queued job; the second caller checks
        whether the job has already been removed and skips if so.
        """
        if self._print_lock is None:
            self._print_lock = asyncio.Lock()

        async with self._print_lock:
            job_id = job.get("job_id")
            if job_id and self.job_queue is not None:
                still_queued = any(
                    j.get("job_id") == job_id for j in self.job_queue.queue
                )
                if not still_queued:
                    logger.debug(
                        f"Skipping duplicate print for job {job_id}: already removed"
                    )
                    return True

            printer_socket_connected = bool(self.printer and getattr(self.printer, "connected", False))
            if not self.printer or not self.printer_connected or not printer_socket_connected:
                logger.warning("Printer not connected; attempting reconnect before printing")
                await self.connect_printer()
                if not self.printer_connected:
                    logger.error("Printer still offline; cannot print job")
                    if self.job_queue and job_id:
                        self.job_queue.mark_retry(job_id)
                    return False

            try:
                await self.printer.print_receipt(job)
                logger.info(f"Printed: {job.get('intent_type')} from {job.get('sender')}")
                if self.job_queue and job_id:
                    await self.job_queue.remove_job(job_id)
                return True
            except Exception as e:
                logger.error(f"Failed to print job: {e}", exc_info=True)
                self.printer_connected = False
                if self.job_queue and job_id:
                    self.job_queue.mark_retry(job_id)
                return False

    async def process_queue(self):
        """Attempt to print all printable queued jobs."""
        if not self.job_queue:
            logger.warning("No job queue attached; skipping queue processing")
            return

        if self._process_queue_lock is None:
            self._process_queue_lock = asyncio.Lock()

        async with self._process_queue_lock:
            printable_jobs = self.job_queue.get_printable_jobs()
            if not printable_jobs:
                logger.debug("No printable jobs ready for processing")
                return

            logger.info(f"Processing {len(printable_jobs)} queued jobs")

            for job in printable_jobs:
                await self.print_job(job)

    def start_queue_worker(self):
        """Start background queue processor if not already running."""
        if self._queue_worker_task and not self._queue_worker_task.done():
            return

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.get_event_loop()

        self._queue_worker_task = loop.create_task(self._queue_worker_loop())
        logger.info(
            f"Queue worker started with {self.queue_worker_interval}s interval"
        )

    async def stop_queue_worker(self):
        """Stop background queue processor."""
        if not self._queue_worker_task:
            return

        self._queue_worker_task.cancel()
        try:
            await self._queue_worker_task
        except asyncio.CancelledError:
            logger.debug("Queue worker cancelled")
        finally:
            self._queue_worker_task = None

    async def _queue_worker_loop(self):
        try:
            while True:
                await asyncio.sleep(self.queue_worker_interval)
                if self.job_queue and self.job_queue.queue:
                    await self.process_queue()
        except asyncio.CancelledError:
            logger.debug("Queue worker loop cancelled")
            raise
