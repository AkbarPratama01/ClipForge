"""Minimal Redis job queue (§47) with Phase 10 retry support.

Jobs are JSON dicts on a Redis list (``clipforge:jobs``): ``id``, ``type``,
``payload``, ``created_at``, ``attempts``. Failed jobs are requeued by the
worker consumer up to ``max_job_retries`` times with exponential backoff
(§63); ``attempts`` survives the round trip so retries are bounded.
"""

from __future__ import annotations

import json
import time
import uuid

from app.core.redis import get_redis

JOBS_KEY = "clipforge:jobs"

# Job types (§47) — consumed in Phase 3 (download), Phase 4 (transcribe),
# Phase 5 (analyze), Phase 6 (render), Phase 8 (publish), Phase 10 (inbox).
JOB_DOWNLOAD_VIDEO = "DOWNLOAD_VIDEO"
JOB_TRANSCRIBE = "TRANSCRIBE"
JOB_ANALYZE = "ANALYZE"
JOB_RENDER = "RENDER"
JOB_PUBLISH = "PUBLISH"
JOB_IMPORT_INBOX_FILE = "IMPORT_INBOX_FILE"

# Backoff before retrying a failed job: base * 2**attempts seconds, capped.
RETRY_BACKOFF_BASE_SECONDS = 5.0
RETRY_BACKOFF_MAX_SECONDS = 300.0


def enqueue(job_type: str, payload: dict) -> str:
    """Push a job onto the Redis list; returns its id."""
    job_id = uuid.uuid4().hex
    job = {
        "id": job_id,
        "type": job_type,
        "payload": payload,
        "created_at": time.time(),
        "attempts": 0,
    }
    get_redis().rpush(JOBS_KEY, json.dumps(job))
    return job_id


def retry_delay_seconds(attempts: int) -> float:
    """Exponential backoff for a job that already failed ``attempts`` times."""
    return min(RETRY_BACKOFF_BASE_SECONDS * (2**attempts), RETRY_BACKOFF_MAX_SECONDS)


def requeue(job: dict) -> None:
    """Re-push a failed job for another attempt (``attempts`` incremented)."""
    job["attempts"] = job.get("attempts", 0) + 1
    job["updated_at"] = time.time()
    get_redis().rpush(JOBS_KEY, json.dumps(job))


def dequeue(timeout: int = 5) -> dict | None:
    """Blocking pop (BLPOP); returns the next job dict or None on timeout."""
    result = get_redis().blpop(JOBS_KEY, timeout=timeout)
    if result is None:
        return None
    _, raw = result
    return json.loads(raw)
