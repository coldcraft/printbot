"""
SMS Gateway outbound (capcom6 android-sms-gateway).
Used by the Telegram bridge to send SMS replies via the burner phone.
"""

import os
from typing import Optional

import httpx

from logger import setup_logger

logger = setup_logger(__name__)


class SMSGateOutbound:
    def __init__(self):
        self.base_url = os.getenv("SMSGATE_BASE_URL", "").strip().rstrip("/")
        self.username = os.getenv("SMSGATE_USERNAME", "").strip()
        self.password = os.getenv("SMSGATE_PASSWORD", "").strip()
        self.timeout = int(os.getenv("SMSGATE_TIMEOUT_SECONDS", 15))
        self.enabled = bool(self.base_url and self.username and self.password)
        if self.enabled:
            logger.info(f"SMS Gateway outbound ready ({self.base_url})")
        else:
            logger.info(
                "SMS Gateway outbound disabled (SMSGATE_BASE_URL/USERNAME/PASSWORD not set)"
            )

    async def send(self, recipient: str, message: str) -> bool:
        if not self.enabled:
            logger.warning("SMS Gateway outbound disabled; cannot send SMS")
            return False

        url = f"{self.base_url}/messages"
        payload = {"message": message, "phoneNumbers": [recipient]}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url,
                    auth=(self.username, self.password),
                    headers={"Content-Type": "application/json"},
                    json=payload,
                )
        except Exception as e:
            logger.error(f"SMS Gateway outbound HTTP error: {e}")
            return False

        if 200 <= resp.status_code < 300:
            logger.info(
                f"SMS Gateway SMS sent: recipient={recipient} chars={len(message)}"
            )
            return True

        body_preview = (resp.text or "")[:300]
        logger.warning(
            f"SMS Gateway SMS failed: status={resp.status_code} body={body_preview!r}"
        )
        return False
