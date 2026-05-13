"""
PrintBot — Main FastAPI application
Receives SMS webhooks, orchestrates Ollama parsing, prints receipts.
"""

import os
import re
import hmac
import base64
import hashlib
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from pydantic import BaseModel
from datetime import datetime
import logging
import json
from typing import Any, Dict, Optional
from dotenv import load_dotenv

from logger import setup_logger
from router import Router
from job_queue import JobQueue
from telegram_bridge import TelegramBridge
from textbee_outbound import TextBeeOutbound
from smsgate_outbound import SMSGateOutbound

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_DIR)
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Setup logging
logger = setup_logger(__name__)

app = FastAPI(title="PrintBot", version="0.1.0")

# Initialize components
router = Router()
job_queue = JobQueue()
router.set_job_queue(job_queue)
telegram = TelegramBridge()
smsgate = SMSGateOutbound()
textbee = TextBeeOutbound()
# Prefer SMS Gateway (local burner) for outbound; fall back to TextBee if it
# isn't configured. TextBee can be retired entirely once SMSGate is stable.
if smsgate.enabled:
    telegram.set_sms_sender(smsgate.send)
else:
    telegram.set_sms_sender(textbee.send)

class TextBeeWebhook(BaseModel):
    """TextBee webhook payload"""
    phone: str
    message: str
    timestamp: Optional[str] = None
    bypass_rate_limit: bool = False


def _first_non_empty(payload: Dict[str, Any], keys: list[str]) -> Optional[str]:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, (int, float)):
            return str(value)
    return None


def _normalize_textbee_payload(payload: Dict[str, Any]) -> Optional[TextBeeWebhook]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    merged = {**payload, **event, **data}

    phone = _first_non_empty(
        merged,
        ["phone", "from", "sender", "source", "phoneNumber", "from_number", "msisdn"],
    )
    message = _first_non_empty(
        merged,
        ["message", "text", "body", "content", "msg", "sms"],
    )
    timestamp = _first_non_empty(
        merged,
        ["timestamp", "time", "sentAt", "created_at", "date"],
    )

    bypass_value = merged.get("bypass_rate_limit", False)
    if isinstance(bypass_value, str):
        bypass_value = bypass_value.strip().lower() in {"1", "true", "yes", "on"}
    else:
        bypass_value = bool(bypass_value)

    if not phone or not message:
        return None

    return TextBeeWebhook(
        phone=phone,
        message=message,
        timestamp=timestamp,
        bypass_rate_limit=bypass_value,
    )


def _normalize_e164_us(phone: Optional[str]) -> str:
    """Coerce a phone number to E.164. Defaults to US country code for 10-digit input."""
    if not phone:
        return ""
    raw = str(phone).strip()
    if raw.startswith("+"):
        return raw
    digits = re.sub(r"\D", "", raw)
    if len(digits) == 10:
        return f"+1{digits}"
    if len(digits) == 11 and digits.startswith("1"):
        return f"+{digits}"
    return f"+{digits}" if digits else raw


def _truncate_for_log(obj: Any, max_str: int = 200) -> Any:
    """Recursively replace long strings with a length+prefix summary so logs stay readable."""
    if isinstance(obj, dict):
        return {k: _truncate_for_log(v, max_str) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_truncate_for_log(v, max_str) for v in obj]
    if isinstance(obj, str) and len(obj) > max_str:
        return f"<str len={len(obj)} prefix={obj[:60]!r}>"
    return obj


def _normalize_smsgate_payload(
    payload: Dict[str, Any],
) -> tuple[Optional[TextBeeWebhook], str]:
    """
    Normalize a capcom6 SMS Gateway webhook into our common record shape.
    Returns (record, event_type). Record is None for unsupported events
    (e.g. mms:received, system:ping) or malformed payloads — caller decides.
    """
    event_type = str(payload.get("event") or "").strip()
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else {}

    if event_type != "sms:received":
        return None, event_type

    merged = {**payload, **inner}
    phone = _first_non_empty(merged, ["sender", "from", "phone"])
    message = _first_non_empty(merged, ["message", "text", "body"])
    timestamp = _first_non_empty(merged, ["receivedAt", "timestamp"])
    if not phone or not message:
        return None, event_type

    return (
        TextBeeWebhook(
            phone=phone,
            message=message,
            timestamp=timestamp,
            bypass_rate_limit=False,
        ),
        event_type,
    )


def _verify_smsgate_signature(
    raw_body: bytes,
    timestamp: str,
    signature: str,
    signing_key: str,
) -> bool:
    """
    Verify capcom6 SMS Gateway webhook signature.
    Per docs: HMAC-SHA256(key, raw_body || X-Timestamp), hex digest, constant-time compare.
    """
    if not signature or not timestamp:
        return False
    payload = raw_body + timestamp.encode("utf-8")
    expected = hmac.new(
        signing_key.encode("utf-8"), payload, hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _extract_incoming_key(payload: Dict[str, Any], request: Request) -> Optional[str]:
    candidates = [
        payload.get("key"),
        payload.get("webhook_key"),
        payload.get("secret"),
        request.query_params.get("key"),
        request.headers.get("x-webhook-key"),
        request.headers.get("x-textbee-key"),
        request.headers.get("authorization"),
    ]
    for value in candidates:
        if isinstance(value, str) and value.strip():
            if value.lower().startswith("bearer "):
                return value[7:].strip()
            return value.strip()
    return None

class TestPrintRequest(BaseModel):
    """Manual test print endpoint"""
    intent_type: str  # "reminder", "url", "question", etc.
    content: str
    bypass_rate_limit: bool = False

@app.on_event("startup")
async def startup():
    """Initialize on startup"""
    logger.info("PrintBot starting up...")
    await router.connect_printer()
    await job_queue.load_from_disk()
    await router.process_queue()
    router.start_queue_worker()
    telegram.start()
    logger.info("PrintBot ready")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    logger.info("PrintBot shutting down...")
    await telegram.stop()
    await router.stop_queue_worker()
    await router.disconnect_printer()
    await job_queue.save_to_disk()

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat(),
        "printer_connected": router.printer_connected
    }

@app.post("/webhook/textbee")
async def textbee_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook receiver from TextBee SMS gateway.
    Validates rate limits, routes to Ollama, queues print job.
    """
    try:
        content_type = (request.headers.get("content-type") or "").lower()
        raw_payload: Dict[str, Any] = {}

        if "application/json" in content_type:
            candidate = await request.json()
            if isinstance(candidate, dict):
                raw_payload = candidate
        else:
            form_data = await request.form()
            raw_payload = dict(form_data)

        payload = _normalize_textbee_payload(raw_payload)
        if not payload:
            logger.warning(f"Rejected webhook payload with unsupported schema. Keys={sorted(raw_payload.keys())}")
            return {
                "status": "invalid_payload",
                "message": "Webhook payload missing required phone/message fields",
            }

        expected_key = os.getenv("TEXTBEE_WEBHOOK_KEY", "").strip()
        incoming_key = _extract_incoming_key(raw_payload, request)
        if expected_key and incoming_key != expected_key:
            logger.warning(
                "Webhook rejected: %s",
                "missing key" if not incoming_key else "invalid key",
            )
            return {"status": "unauthorized", "message": "Invalid webhook key"}

        logger.info(f"Incoming webhook normalized: sender={payload.phone}, chars={len(payload.message)}")

        # Idempotency: drop duplicate deliveries (TextBee retries, double-fires)
        if router.is_duplicate_message(payload.phone, payload.message, payload.timestamp):
            logger.info(f"Duplicate webhook dropped for {payload.phone}")
            return {"status": "duplicate", "message": "Already received"}

        # Rate limit check (unless bypassed)
        if not payload.bypass_rate_limit:
            rate_limited, remaining_cooldown = router.check_rate_limit(payload.phone)
            if rate_limited:
                logger.warning(f"Rate limit hit for {payload.phone}, cooldown: {remaining_cooldown}s")
                return {
                    "status": "rate_limited",
                    "message": f"Too many messages. Try again in {remaining_cooldown} seconds."
                }
        else:
            logger.info(f"Bypassing rate limit for {payload.phone}")

        # Character limit check (soft truncate)
        max_chars = int(os.getenv("MAX_MESSAGE_CHARS", 500))
        if len(payload.message) > max_chars:
            logger.info(f"Message truncated for {payload.phone}: {len(payload.message)} -> {max_chars}")
            payload.message = payload.message[:max_chars]

        effective_timestamp = payload.timestamp or datetime.utcnow().isoformat()

        # Mirror inbound SMS to Telegram (fire-and-forget; failure must not block printing)
        sender_label = router._resolve_sender_label(payload.phone) or payload.phone
        background_tasks.add_task(
            telegram.forward_sms,
            sender_phone=payload.phone,
            sender_label=sender_label,
            message=payload.message,
            timestamp=effective_timestamp,
        )

        # Hand off Ollama parse + print to a background task so we ack the webhook
        # immediately. This prevents TextBee retries (and duplicate prints) when
        # Ollama is slow.
        background_tasks.add_task(
            router.process_message,
            message=payload.message,
            sender=payload.phone,
            timestamp=effective_timestamp,
        )

        return {
            "status": "accepted",
            "message": "Your message will be printed shortly"
        }

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }

@app.post("/webhook/sms-gate")
async def smsgate_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Webhook receiver from capcom6 SMS Gateway for Android (local mode).
    Handles sms:received now; mms:received is logged for the photo-printing wire-up.
    """
    try:
        raw = await request.body()

        signing_key = os.getenv("SMSGATE_SIGNING_KEY", "").strip()
        if signing_key:
            sig = request.headers.get("x-signature", "")
            ts = request.headers.get("x-timestamp", "")
            if not _verify_smsgate_signature(raw, ts, sig, signing_key):
                logger.warning("SMS Gateway webhook rejected: bad signature")
                return {"status": "unauthorized", "message": "Invalid signature"}

        try:
            raw_payload = json.loads(raw or b"{}")
        except json.JSONDecodeError as e:
            logger.warning(f"SMS Gateway webhook: invalid JSON ({e})")
            return {"status": "invalid_payload", "message": "Body is not JSON"}

        if not isinstance(raw_payload, dict):
            return {"status": "invalid_payload", "message": "Expected JSON object"}

        record, event_type = _normalize_smsgate_payload(raw_payload)

        if event_type == "mms:received":
            # Notification only — actual content arrives via mms:downloaded.
            inner = raw_payload.get("payload") or {}
            logger.info(
                "mms:received notification: id=%s sender=%s size=%s",
                inner.get("messageId"),
                inner.get("sender"),
                inner.get("size"),
            )
            return {"status": "accepted", "message": "MMS notification received"}

        if event_type == "mms:downloaded":
            inner = raw_payload.get("payload") or {}
            sender = _normalize_e164_us(
                inner.get("sender") or inner.get("phoneNumber")
            )
            timestamp = inner.get("receivedAt") or datetime.utcnow().isoformat()
            message_id = str(inner.get("messageId") or "")

            attachments = inner.get("attachments") or []
            image_att = next(
                (
                    a for a in attachments
                    if isinstance(a, dict)
                    and str(a.get("contentType", "")).lower().startswith("image/")
                ),
                None,
            )

            # Caption priority: payload.body (the typed message text), then any
            # text/plain attachment as a fallback for clients that put it there.
            caption = str(inner.get("body") or "").strip()
            if not caption:
                text_att = next(
                    (
                        a for a in attachments
                        if isinstance(a, dict)
                        and str(a.get("contentType", "")).lower().startswith("text/")
                    ),
                    None,
                )
                if text_att:
                    try:
                        caption = base64.b64decode(
                            text_att.get("data") or "", validate=False
                        ).decode("utf-8", errors="replace").strip()
                    except Exception as e:
                        logger.warning("Failed to decode MMS text attachment: %s", e)

            # Text-only MMS (e.g. long SMS carrier-upgraded to MMS): route to
            # the regular text-message pipeline so it prints like an SMS would.
            if not image_att:
                if caption:
                    logger.info(
                        "mms:downloaded text-only: id=%s sender=%s chars=%d (routing as SMS)",
                        message_id, sender, len(caption),
                    )
                    if router.is_duplicate_message(sender, caption, timestamp):
                        return {"status": "duplicate", "message": "Already received"}
                    rate_limited, remaining = router.check_rate_limit(sender)
                    if rate_limited:
                        return {
                            "status": "rate_limited",
                            "message": f"Too many messages. Try again in {remaining} seconds.",
                        }
                    sender_label_text = router._resolve_sender_label(sender) or sender
                    background_tasks.add_task(
                        telegram.forward_sms,
                        sender_phone=sender,
                        sender_label=sender_label_text,
                        message=caption,
                        timestamp=timestamp,
                    )
                    background_tasks.add_task(
                        router.process_message,
                        message=caption,
                        sender=sender,
                        timestamp=timestamp,
                    )
                    return {"status": "accepted", "message": "Text MMS will print shortly"}
                logger.info(
                    "mms:downloaded ignored (no image, no body): id=%s sender=%s parts=%d",
                    message_id, sender, len(attachments),
                )
                return {"status": "ignored", "message": "No printable content"}

            try:
                image_bytes = base64.b64decode(image_att.get("data") or "", validate=False)
            except Exception as e:
                logger.error("Failed to decode MMS attachment for %s: %s", message_id, e)
                return {"status": "error", "message": "Bad attachment encoding"}

            if not image_bytes:
                logger.warning("Empty image bytes for MMS %s", message_id)
                return {"status": "error", "message": "Empty attachment"}

            logger.info(
                "mms:downloaded: id=%s sender=%s name=%s bytes=%d caption=%r",
                message_id, sender, image_att.get("name"), len(image_bytes), caption,
            )

            # Dedupe on messageId (a synthetic body distinguishes from same-sender SMS)
            if router.is_duplicate_message(sender, f"mms:{message_id}", timestamp):
                logger.info("Duplicate mms:downloaded dropped for %s (id=%s)", sender, message_id)
                return {"status": "duplicate", "message": "Already processed"}

            rate_limited, remaining = router.check_rate_limit(sender)
            if rate_limited:
                logger.warning(
                    "Rate limit hit for %s on photo, cooldown: %ds", sender, remaining
                )
                return {
                    "status": "rate_limited",
                    "message": f"Too many messages. Try again in {remaining} seconds.",
                }

            sender_label = router._resolve_sender_label(sender) or sender

            background_tasks.add_task(
                telegram.forward_mms,
                sender_phone=sender,
                sender_label=sender_label,
                image_bytes=image_bytes,
                caption=caption,
                image_name=image_att.get("name") or "photo.jpg",
                image_mime=image_att.get("contentType") or "image/jpeg",
                timestamp=timestamp,
            )

            job = {
                "intent_type": "photo",
                "image_bytes": image_bytes,
                "content": caption,
                "sender": sender,
                "sender_display": sender_label,
                "received_at": timestamp,
                "metadata": {
                    "messageId": message_id,
                    "name": image_att.get("name"),
                    "contentType": image_att.get("contentType"),
                },
            }

            background_tasks.add_task(router.print_job, job)
            return {"status": "accepted", "message": "Photo will print shortly"}

        if not record:
            logger.info(
                "SMS Gateway event ignored: event=%s keys=%s",
                event_type or "(missing)",
                sorted(raw_payload.keys()),
            )
            return {"status": "ignored", "event": event_type}

        logger.info(
            f"SMS Gateway webhook normalized: sender={record.phone}, chars={len(record.message)}"
        )

        if router.is_duplicate_message(record.phone, record.message, record.timestamp):
            logger.info(f"Duplicate SMS Gateway webhook dropped for {record.phone}")
            return {"status": "duplicate", "message": "Already received"}

        rate_limited, remaining_cooldown = router.check_rate_limit(record.phone)
        if rate_limited:
            logger.warning(
                f"Rate limit hit for {record.phone}, cooldown: {remaining_cooldown}s"
            )
            return {
                "status": "rate_limited",
                "message": f"Too many messages. Try again in {remaining_cooldown} seconds.",
            }

        max_chars = int(os.getenv("MAX_MESSAGE_CHARS", 500))
        if len(record.message) > max_chars:
            logger.info(
                f"Message truncated for {record.phone}: {len(record.message)} -> {max_chars}"
            )
            record.message = record.message[:max_chars]

        effective_timestamp = record.timestamp or datetime.utcnow().isoformat()

        sender_label = router._resolve_sender_label(record.phone) or record.phone
        background_tasks.add_task(
            telegram.forward_sms,
            sender_phone=record.phone,
            sender_label=sender_label,
            message=record.message,
            timestamp=effective_timestamp,
        )

        background_tasks.add_task(
            router.process_message,
            message=record.message,
            sender=record.phone,
            timestamp=effective_timestamp,
        )

        return {"status": "accepted", "message": "Your message will be printed shortly"}

    except Exception as e:
        logger.error(f"Error processing SMS Gateway webhook: {e}", exc_info=True)
        return {"status": "error", "message": str(e)}


@app.post("/test/print")
async def test_print(request: TestPrintRequest, background_tasks: BackgroundTasks):
    """
    Manual test endpoint — send JSON directly without TextBee.
    Useful for development and debugging.
    """
    try:
        print_job = {
            "intent_type": request.intent_type,
            "content": request.content,
            "sender": "test_endpoint",
            "timestamp": datetime.utcnow().isoformat(),
            "test_mode": True
        }

        logger.info(f"Test print job: {request.intent_type}")
        background_tasks.add_task(router.print_job, print_job)

        return {
            "status": "sent_to_printer",
            "intent_type": request.intent_type,
            "message": "Check the printer"
        }

    except Exception as e:
        logger.error(f"Error in test print: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/test/photo")
async def test_photo(background_tasks: BackgroundTasks):
    """
    Print the procedural ski-mask fixture. No params — generates fresh
    PNG bytes in-process and pipes to the photo intent.
    """
    try:
        from photo_fixtures import make_skimask
        image_bytes = make_skimask()
        job = {
            "intent_type": "photo",
            "image_bytes": image_bytes,
            "sender": "test_endpoint",
            "received_at": datetime.utcnow().isoformat(),
            "test_mode": True,
        }
        logger.info(f"Test photo job: {len(image_bytes)} bytes")
        background_tasks.add_task(router.print_job, job)
        return {
            "status": "sent_to_printer",
            "intent_type": "photo",
            "image_bytes": len(image_bytes),
        }
    except Exception as e:
        logger.error(f"Error in test photo: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue/status")
async def queue_status():
    """Get current job queue status"""
    return {
        "pending_jobs": len(job_queue.queue),
        "jobs": [j for j in job_queue.queue]
    }

@app.post("/queue/retry")
async def retry_queued_jobs(background_tasks: BackgroundTasks):
    """Manually trigger retry of failed jobs"""
    logger.info("Manual retry triggered for queued jobs")
    background_tasks.add_task(router.process_queue)
    return {"status": "retry_started"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
