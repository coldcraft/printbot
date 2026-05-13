"""
Telegram bridge:
- Forwards inbound SMS to a Telegram chat
- Polls Telegram for replies and routes them back as outbound SMS
"""

import asyncio
import os
import re
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

import httpx

from logger import setup_logger

logger = setup_logger(__name__)

PHONE_RE = re.compile(r"\+\d{10,15}")

SmsSender = Callable[[str, str], Awaitable[bool]]


def _escape_html(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramBridge:
    """Async Telegram Bot API client + polling worker."""

    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        chat_id_raw = os.getenv("TELEGRAM_CHAT_ID", "").strip()
        try:
            self.allowed_chat_id: Optional[int] = int(chat_id_raw) if chat_id_raw else None
        except ValueError:
            self.allowed_chat_id = None
            logger.warning(f"Invalid TELEGRAM_CHAT_ID '{chat_id_raw}'; bridge disabled")

        self.poll_long_timeout = int(os.getenv("TELEGRAM_POLL_TIMEOUT_SECONDS", 25))
        self.error_backoff = int(os.getenv("TELEGRAM_ERROR_BACKOFF_SECONDS", 5))
        self.enabled = bool(self.token and self.allowed_chat_id)

        self._offset: Optional[int] = None
        self._poll_task: Optional[asyncio.Task] = None
        self._sms_sender: Optional[SmsSender] = None

        if self.enabled:
            logger.info(f"Telegram bridge ready (chat_id={self.allowed_chat_id})")
        else:
            logger.info("Telegram bridge disabled (TELEGRAM_BOT_TOKEN/CHAT_ID not set)")

    @property
    def base_url(self) -> str:
        return f"https://api.telegram.org/bot{self.token}"

    def set_sms_sender(self, sender: SmsSender):
        """Inject the outbound SMS handler. Signature: async (recipient_phone, message_text) -> bool."""
        self._sms_sender = sender

    async def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        if not self.enabled:
            return False
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"{self.base_url}/sendMessage",
                    json={
                        "chat_id": self.allowed_chat_id,
                        "text": text,
                        "parse_mode": parse_mode,
                        "disable_web_page_preview": True,
                    },
                )
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"Telegram sendMessage failed: {e}")
            return False

    def _build_header(
        self,
        sender_phone: str,
        sender_label: str,
        timestamp: Optional[str],
        emoji: str,
    ) -> str:
        ts_display = ""
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts_display = dt.astimezone().strftime("%b %d %H:%M")
            except Exception:
                pass

        header = f"{emoji} <b>{_escape_html(sender_label)}</b>"
        if sender_label and sender_phone and sender_label != sender_phone:
            header += f" ({_escape_html(sender_phone)})"
        elif sender_phone and not sender_label:
            header = f"{emoji} {_escape_html(sender_phone)}"
        if ts_display:
            header += f"\n<i>{_escape_html(ts_display)}</i>"
        return header

    async def forward_sms(
        self,
        sender_phone: str,
        sender_label: str,
        message: str,
        timestamp: Optional[str] = None,
    ):
        """Push an inbound SMS to the authorized Telegram chat."""
        if not self.enabled:
            return

        header = self._build_header(sender_phone, sender_label, timestamp, "📱")
        body = _escape_html(message.strip())
        text = f"{header}\n\n{body}\n\n<i>Reply to this message to send SMS back.</i>"
        await self.send_message(text)

    async def forward_mms(
        self,
        sender_phone: str,
        sender_label: str,
        image_bytes: bytes,
        caption: str = "",
        image_name: str = "photo.jpg",
        image_mime: str = "image/jpeg",
        timestamp: Optional[str] = None,
    ):
        """Push an inbound MMS image (with optional caption) to Telegram via sendPhoto."""
        if not self.enabled:
            return

        header = self._build_header(sender_phone, sender_label, timestamp, "📷")
        body = _escape_html((caption or "").strip())
        if body:
            text = f"{header}\n\n{body}\n\n<i>Reply to this message to send SMS back.</i>"
        else:
            text = f"{header}\n\n<i>Reply to this message to send SMS back.</i>"
        # Telegram caption limit is 1024 chars
        if len(text) > 1024:
            text = text[:1020] + "..."

        # sendPhoto Bot API limit is 10 MB; MMS attachments are typically <1 MB
        # but guard anyway and fall back to sendDocument for the oversize case.
        endpoint = "/sendPhoto" if len(image_bytes) <= 10 * 1024 * 1024 else "/sendDocument"
        field = "photo" if endpoint == "/sendPhoto" else "document"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                files = {field: (image_name, image_bytes, image_mime)}
                data = {
                    "chat_id": str(self.allowed_chat_id),
                    "caption": text,
                    "parse_mode": "HTML",
                }
                resp = await client.post(
                    f"{self.base_url}{endpoint}",
                    data=data,
                    files=files,
                )
                resp.raise_for_status()
        except Exception as e:
            logger.warning(f"Telegram {endpoint} failed: {e}")

    def start(self):
        """Start the polling worker (no-op if disabled or already running)."""
        if not self.enabled:
            return
        if self._poll_task and not self._poll_task.done():
            return
        loop = asyncio.get_event_loop()
        self._poll_task = loop.create_task(self._poll_loop())
        logger.info("Telegram polling started")

    async def stop(self):
        if not self._poll_task:
            return
        self._poll_task.cancel()
        try:
            await self._poll_task
        except asyncio.CancelledError:
            pass
        self._poll_task = None
        logger.info("Telegram polling stopped")

    async def _poll_loop(self):
        # Routine transient errors on long-poll connections — log at debug, not warning.
        transient_types = (
            httpx.ReadTimeout,
            httpx.ConnectTimeout,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
        )
        try:
            while True:
                try:
                    await self._poll_once()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    is_transient = isinstance(e, transient_types) or (
                        isinstance(e, httpx.HTTPStatusError)
                        and 500 <= e.response.status_code < 600
                    )
                    msg = str(e) or "(no message)"
                    if is_transient:
                        logger.debug(
                            "Telegram poll transient: %s: %s",
                            type(e).__name__,
                            msg,
                        )
                    else:
                        logger.warning(
                            "Telegram poll error: %s: %s",
                            type(e).__name__,
                            msg,
                        )
                    await asyncio.sleep(self.error_backoff)
        except asyncio.CancelledError:
            raise

    async def _poll_once(self):
        body = {
            "timeout": self.poll_long_timeout,
            "allowed_updates": ["message"],
        }
        if self._offset is not None:
            body["offset"] = self._offset

        async with httpx.AsyncClient(timeout=self.poll_long_timeout + 10) as client:
            resp = await client.post(f"{self.base_url}/getUpdates", json=body)
            resp.raise_for_status()
            data = resp.json()

        if not data.get("ok"):
            logger.warning(f"Telegram getUpdates returned not OK: {data}")
            return

        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            try:
                await self._handle_update(update)
            except Exception as e:
                logger.warning(f"Telegram update handler error: {e}", exc_info=True)

    async def _handle_update(self, update: dict):
        message = update.get("message")
        if not message:
            return

        chat_id = (message.get("chat") or {}).get("id")
        if chat_id != self.allowed_chat_id:
            logger.warning(f"Telegram message from unauthorized chat_id={chat_id}; ignoring")
            return

        text = (message.get("text") or "").strip()
        if not text:
            return

        if text.startswith("/"):
            await self._handle_command(text)
            return

        reply_to = message.get("reply_to_message")
        if not reply_to:
            await self.send_message(
                "Reply directly to a forwarded SMS to send a response back. "
                "Plain messages here are ignored."
            )
            return

        quoted = reply_to.get("text") or ""
        phone_match = PHONE_RE.search(quoted)
        if not phone_match:
            await self.send_message(
                "Couldn't find a phone number in the message you replied to. "
                "Make sure you're replying to a forwarded SMS."
            )
            return

        recipient = phone_match.group(0)
        if not self._sms_sender:
            await self.send_message(
                f"⚠️ Outbound SMS isn't wired up yet. "
                f"Would have sent to <code>{_escape_html(recipient)}</code>:\n\n"
                f"{_escape_html(text)}"
            )
            return

        try:
            success = await self._sms_sender(recipient, text)
        except Exception as e:
            logger.error(f"Outbound SMS handler raised: {e}", exc_info=True)
            success = False

        if success:
            await self.send_message(
                f"✅ Sent to <code>{_escape_html(recipient)}</code>"
            )
        else:
            await self.send_message(
                f"❌ Failed to send to <code>{_escape_html(recipient)}</code>"
            )

    async def _handle_command(self, text: str):
        cmd = text.split()[0].lower()
        if cmd in ("/start", "/help"):
            await self.send_message(
                "<b>BURNR bridge</b>\n"
                "Inbound SMS show up here automatically.\n"
                "<b>Reply</b> to a forwarded SMS to send a response back.\n"
                "Plain messages and unknown commands are ignored."
            )
        elif cmd == "/ping":
            await self.send_message("pong")
        else:
            await self.send_message(f"Unknown command: <code>{_escape_html(cmd)}</code>")
