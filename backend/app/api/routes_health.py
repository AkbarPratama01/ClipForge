"""Health endpoints.

``GET /api/health`` — readiness: probes MySQL (``SELECT 1``) and Redis
(``PING``), reporting per-service status and latency. Returns HTTP 503 when a
critical dependency is down so orchestrators can react.
"""

import time
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text

from app.core.config import settings
from app.database.session import engine

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["health"])


def check_mysql() -> tuple[bool, float | None]:
    start = time.perf_counter()
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, round((time.perf_counter() - start) * 1000, 1)
    except Exception:
        logger.exception("mysql_health_check_failed")
        return False, None


def check_redis() -> tuple[bool, float | None]:
    start = time.perf_counter()
    try:
        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        ok = client.ping()
        return bool(ok), round((time.perf_counter() - start) * 1000, 1)
    except Exception:
        logger.exception("redis_health_check_failed")
        return False, None


@router.get("/health", summary="Readiness: API, MySQL, Redis")
def health() -> JSONResponse:
    mysql_ok, mysql_ms = check_mysql()
    redis_ok, redis_ms = check_redis()

    services = {
        "api": {"status": "ok"},
        "mysql": {"status": "ok" if mysql_ok else "error", "latency_ms": mysql_ms},
        "redis": {"status": "ok" if redis_ok else "error", "latency_ms": redis_ms},
    }
    all_ok = mysql_ok and redis_ok

    payload = {
        "status": "ok" if all_ok else "degraded",
        "version": settings.app_version,
        "services": services,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(content=payload, status_code=200 if all_ok else 503)


@router.get("/healthz", include_in_schema=False)
def healthz() -> dict:
    return {"status": "ok"}
