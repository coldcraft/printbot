"""
Job Queue — Persists failed jobs to disk for retry
Handles disk-based queue for reliability
"""

import json
import os
from datetime import datetime, timedelta
from typing import List, Dict
from pathlib import Path
import asyncio

from logger import setup_logger

logger = setup_logger(__name__)


class JobQueue:
    def __init__(self):
        self.queue_dir = os.path.join(os.getenv("LOG_DIR", "/logs"), "queue")
        Path(self.queue_dir).mkdir(parents=True, exist_ok=True)
        self.queue: List[Dict] = []
        self.max_age_minutes = int(os.getenv("JOB_QUEUE_MAX_AGE_MINUTES", 1440))
        self.stale_age_minutes = max(0, int(os.getenv("JOB_QUEUE_STALE_AGE_MINUTES", 0)))
        logger.info(f"Job queue initialized at {self.queue_dir}")

    async def load_from_disk(self):
        """Load persisted jobs from disk on startup"""
        try:
            for filename in os.listdir(self.queue_dir):
                if not filename.endswith(".json"):
                    continue

                file_path = os.path.join(self.queue_dir, filename)
                try:
                    with open(file_path, 'r') as f:
                        job = json.load(f)

                        # Check if job is too old
                        created_at = datetime.fromisoformat(job.get("created_at", datetime.utcnow().isoformat()))
                        age_minutes = (datetime.utcnow() - created_at).total_seconds() / 60

                        if age_minutes > self.max_age_minutes:
                            logger.info(f"Discarding stale job: {filename} (age: {age_minutes:.0f}m)")
                            os.remove(file_path)
                        else:
                            self.queue.append(job)
                            logger.info(f"Loaded job from queue: {filename}")
                except Exception as e:
                    logger.error(f"Error loading queue job {filename}: {e}")

            logger.info(f"Loaded {len(self.queue)} jobs from disk queue")
        except Exception as e:
            logger.error(f"Error loading queue from disk: {e}")

    async def save_to_disk(self):
        """Persist queue to disk on shutdown"""
        try:
            for i, job in enumerate(self.queue):
                filename = f"job_{datetime.utcnow().isoformat()}_{i}.json"
                file_path = os.path.join(self.queue_dir, filename)

                with open(file_path, 'w') as f:
                    json.dump(job, f, indent=2)

            logger.info(f"Saved {len(self.queue)} jobs to disk")
        except Exception as e:
            logger.error(f"Error saving queue to disk: {e}")

    async def add_job(self, job: Dict) -> str:
        """Add job to queue and save to disk"""
        try:
            job_id = f"{datetime.utcnow().isoformat()}_{job.get('sender')}"
            job["job_id"] = job_id

            self.queue.append(job)

            # Persist immediately
            filename = f"job_{job_id}.json"
            file_path = os.path.join(self.queue_dir, filename)
            with open(file_path, 'w') as f:
                json.dump(job, f, indent=2)

            logger.info(f"Added job to queue: {job_id}")
            return job_id
        except Exception as e:
            logger.error(f"Error adding job to queue: {e}")
            return None

    async def remove_job(self, job_id: str):
        """Remove job from queue after successful print"""
        try:
            self.queue = [j for j in self.queue if j.get("job_id") != job_id]

            # Remove from disk
            for filename in os.listdir(self.queue_dir):
                if job_id in filename:
                    os.remove(os.path.join(self.queue_dir, filename))
                    logger.info(f"Removed job from queue: {job_id}")
        except Exception as e:
            logger.error(f"Error removing job {job_id}: {e}")

    async def retry_all(self):
        """Retry all queued jobs (called when printer comes back online)"""
        logger.info(f"Retrying {len(self.queue)} queued jobs")

        # Mark all as ready for retry
        for job in self.queue:
            job["retry_count"] = job.get("retry_count", 0) + 1

        # Caller should attempt to print each job

    def get_printable_jobs(self) -> List[Dict]:
        """Get jobs that are old enough to retry (not received recently)"""
        printable = []

        for job in self.queue:
            created_at = datetime.fromisoformat(job.get("created_at", datetime.utcnow().isoformat()))
            age_minutes = (datetime.utcnow() - created_at).total_seconds() / 60

            # Only retry if past stale threshold (default 0 for immediate retry)
            if age_minutes >= self.stale_age_minutes:
                printable.append(job)

        return printable

    def mark_retry(self, job_id: str):
        """Mark job as failed and increment retry count"""
        for job in self.queue:
            if job.get("job_id") == job_id:
                job["retry_count"] = job.get("retry_count", 0) + 1
                logger.info(f"Marked job for retry: {job_id} (attempt {job['retry_count']})")
                break