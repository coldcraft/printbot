"""
PrintBot — Main FastAPI application
Receives SMS webhooks, orchestrates Ollama parsing, prints receipts.
"""

import os
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from datetime import datetime
import logging
import json

from logger import setup_logger
from router import Router
from job_queue import JobQueue

# Setup logging
logger = setup_logger(__name__)

app = FastAPI(title="PrintBot", version="0.1.0")

# Initialize components
router = Router()
job_queue = JobQueue()
router.set_job_queue(job_queue)

class TextBeeWebhook(BaseModel):
    """TextBee webhook payload"""
    phone: str
    message: str
    timestamp: str = None
    bypass_rate_limit: bool = False

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
    logger.info("PrintBot ready")

@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown"""
    logger.info("PrintBot shutting down...")
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
async def textbee_webhook(payload: TextBeeWebhook, background_tasks: BackgroundTasks):
    """
    Webhook receiver from TextBee SMS gateway.
    Validates rate limits, routes to Ollama, queues print job.
    """
    try:
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

        # Route through Ollama to get intent and formatted JSON
        print_job = await router.parse_and_format(
            message=payload.message,
            sender=payload.phone,
            timestamp=payload.timestamp or datetime.utcnow().isoformat()
        )

        if not print_job:
            logger.error(f"Failed to parse message from {payload.phone}")
            return {"status": "parse_failed", "message": "Could not parse message"}

        # Queue job (add to disk queue, attempt print if printer online)
        job_id = await job_queue.add_job(print_job)
        logger.info(f"Job {job_id} queued from {payload.phone}")

        # Try to print immediately in background
        background_tasks.add_task(router.print_job, print_job)

        return {
            "status": "queued",
            "job_id": job_id,
            "message": "Your message will be printed shortly"
        }

    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "message": str(e)
        }

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
