"""
TextBee outbound SMS client.
Used by the Telegram bridge to send SMS replies via the user's TextBee gateway.
"""

import os
from typing import Optional

import httpx

from logger import setup_logger

logger = setup_logger(__name__)


class TextBeeOutbound:
    def __init__(self):
        self.api_key = os.getenv("TEXTBEE_API_KEY", "").strip()
        self.device_id = os.getenv("TEXTBEE_DEVICE_ID", "").strip()
        self.base_url = os.getenv("TEXTBEE_API_BASE", "https://api.textbee.dev").rstrip("/")
        self.timeout = int(os.getenv("TEXTBEE_TIMEOUT_SECONDS", 15))
        self.enabled = bool(self.api_key and self.device_id)
        if self.enabled:
            logger.info(f"TextBee outbound ready (device={self.device_id})")
        else:
            logger.info(
                "TextBee outbound disabled (TEXTBEE_API_KEY/TEXTBEE_DEVICE_ID not set)"
            )

    async def send(self, recipient: str, message: str) -> bool:
        if not self.enabled:
            logger.warning("TextBee outbound disabled; cannot send SMS")
            return False

        url = f"{self.base_url}/api/v1/gateway/devices/{self.device_id}/send-sms"
        payload = {"recipients": [recipient], "message": message}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url,
                    headers={
                        "x-api-key": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )
        except Exception as e:
            logger.error(f"TextBee outbound HTTP error: {e}")
            return False

        if 200 <= resp.status_code < 300:
            logger.info(
                f"TextBee SMS sent: recipient={recipient} chars={len(message)}"
            )
            return True

        body_preview = (resp.text or "")[:300]
        logger.warning(
            f"TextBee SMS failed: status={resp.status_code} body={body_preview!r}"
        )
        return False
