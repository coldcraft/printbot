"""
Router — Orchestrates Ollama calls, intent parsing, rate limiting.
Core of the TextBee → Ollama → Printer loop.
"""

import os
import json
import time
import asyncio
import httpx
from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, Optional, Tuple, TYPE_CHECKING

from logger import setup_logger
from printer import Printer
from mock_printer import MockPrinter

if TYPE_CHECKING:
    from job_queue import JobQueue

logger = setup_logger(__name__)

class Router:
    def __init__(self):
        self.ollama_host = os.getenv("OLLAMA_HOST", "http://host.docker.internal:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "mistral")
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
        
        logger.info(f"Router initialized: Ollama={self.ollama_host}, Model={self.ollama_model}")

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
            # Load system prompt
            system_prompt = self._load_system_prompt()
            
            logger.debug(f"Sending to Ollama: from={sender}, length={len(message)}")
            
            # Call Ollama with retries
            response_text = await self._call_ollama_with_retry(system_prompt, message)
            
            if not response_text:
                logger.error(f"Ollama returned empty response for message from {sender}")
                return None
            
            # Extract JSON from response
            print_job = self._extract_json_from_ollama(response_text)
            
            if not print_job:
                logger.error(f"Could not parse JSON from Ollama response: {response_text[:200]}")
                return None
            
            # Enrich with metadata
            print_job.update({
                "sender": sender,
                "received_at": timestamp,
                "created_at": datetime.utcnow().isoformat()
            })
            
            logger.info(f"Parsed job: intent={print_job.get('intent_type')}, from={sender}")
            return print_job
            
        except Exception as e:
            logger.error(f"Error in parse_and_format: {e}", exc_info=True)
            return None

    def _load_system_prompt(self) -> str:
        """Load system prompt from file"""
        try:
            prompt_file = "/app/prompts/system.txt"
            if os.path.exists(prompt_file):
                with open(prompt_file, 'r') as f:
                    return f.read()
            else:
                logger.warning(f"System prompt not found at {prompt_file}, using default")
                return self._default_system_prompt()
        except Exception as e:
            logger.error(f"Error loading system prompt: {e}")
            return self._default_system_prompt()

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

    async def _call_ollama_with_retry(self, system_prompt: str, message: str) -> Optional[str]:
        """Call Ollama with retry logic"""
        for attempt in range(self.retry_attempts):
            try:
                async with httpx.AsyncClient(timeout=self.retry_timeout) as client:
                    response = await client.post(
                        f"{self.ollama_host}/api/generate",
                        json={
                            "model": self.ollama_model,
                            "prompt": message,
                            "system": system_prompt,
                            "stream": False
                        },
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
        try:
            # Try direct parse first
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass
        
        # Look for JSON object in response
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass
        
        logger.error(f"Could not extract JSON from: {response_text[:200]}")
        return None

    async def print_job(self, job: Dict):
        """
        Print a job. On success remove from queue; on failure mark for retry.
        Attempts to reconnect printer if needed.
        """
        if not self.printer or not self.printer_connected:
            logger.warning("Printer not connected; attempting reconnect before printing")
            await self.connect_printer()
            if not self.printer_connected:
                logger.error("Printer still offline; cannot print job")
                if self.job_queue and job.get("job_id"):
                    self.job_queue.mark_retry(job["job_id"])
                return False

        try:
            await self.printer.print_receipt(job)
            logger.info(f"Printed: {job.get('intent_type')} from {job.get('sender')}")
            if self.job_queue and job.get("job_id"):
                await self.job_queue.remove_job(job["job_id"])
            return True
        except Exception as e:
            logger.error(f"Failed to print job: {e}", exc_info=True)
            if self.job_queue and job.get("job_id"):
                self.job_queue.mark_retry(job["job_id"])
            return False

    async def process_queue(self):
        """Attempt to print all printable queued jobs."""
        if not self.job_queue:
            logger.warning("No job queue attached; skipping queue processing")
            return

        printable_jobs = self.job_queue.get_printable_jobs()
        logger.info(f"Processing {len(printable_jobs)} queued jobs")

        for job in printable_jobs:
            await self.print_job(job)
