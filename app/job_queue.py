"""
Job Queue — Persists failed jobs to disk for retry
Handles disk-based queue for reliability
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional
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

    def _safe_filename_token(self, value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("-", "_", ".", "+") else "_" for ch in value)

    def _job_file_path(self, job_id: str) -> str:
        safe_job_id = self._safe_filename_token(job_id)
        return os.path.join(self.queue_dir, f"job_{safe_job_id}.json")

    def _persist_job_file(self, job: Dict) -> Optional[str]:
        job_id = job.get("job_id")
        if not job_id:
            return None

        file_path = self._job_file_path(job_id)
        with open(file_path, 'w') as f:
            json.dump(job, f, indent=2)
        return file_path

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

                    created_at = datetime.fromisoformat(job.get("created_at", datetime.utcnow().isoformat()))
                    age_minutes = (datetime.utcnow() - created_at).total_seconds() / 60

                    if age_minutes > self.max_age_minutes:
                        logger.info(f"Discarding stale job: {filename} (age: {age_minutes:.0f}m)")
                        os.remove(file_path)
                        continue

                    if not job.get("job_id"):
                        fallback_sender = job.get("sender", "unknown")
                        job["job_id"] = f"{datetime.utcnow().isoformat()}_{fallback_sender}"
                        logger.warning(
                            f"Queue file {filename} missing job_id; generated {job['job_id']}"
                        )

                    persisted_path = self._persist_job_file(job)
                    if (
                        persisted_path
                        and os.path.abspath(persisted_path) != os.path.abspath(file_path)
                        and os.path.exists(file_path)
                    ):
                        try:
                            os.remove(file_path)
                        except FileNotFoundError:
                            pass
                        except Exception as cleanup_error:
                            logger.warning(
                                f"Could not remove legacy queue file {filename}: {cleanup_error}"
                            )

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
            for job in self.queue:
                if not job.get("job_id"):
                    job["job_id"] = f"{datetime.utcnow().isoformat()}_{job.get('sender', 'unknown')}"
                self._persist_job_file(job)

            logger.info(f"Saved {len(self.queue)} jobs to disk")
        except Exception as e:
            logger.error(f"Error saving queue to disk: {e}")

    async def add_job(self, job: Dict) -> str:
        """Add job to queue and save to disk"""
        try:
            job_id = f"{datetime.utcnow().isoformat()}_{job.get('sender')}"
            job["job_id"] = job_id

            self.queue.append(job)

            # Persist immediately using normalized naming
            self._persist_job_file(job)

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
            file_path = self._job_file_path(job_id)

            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Removed job from queue: {job_id}")
            else:
                logger.debug(
                    "Queue file already missing for %s (looked for %s)",
                    job_id,
                    file_path,
                )
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