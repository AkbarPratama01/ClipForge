"""ClipForge worker entrypoint — Phase 1 stub.

Connects to Redis and keeps the container alive with a heartbeat loop. The
job-consumption loop replaces this in Phase 5 (jobs module), but the process
lifecycle (graceful shutdown on SIGTERM/SIGINT) stays as-is.
"""

import asyncio
import signal

import structlog
from redis import Redis, exceptions

from app.core.config import settings
from app.core.logging import setup_logging

logger = structlog.get_logger(__name__)

HEARTBEAT_INTERVAL = 30.0


async def worker_loop() -> None:
    client = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=3.0,
        socket_timeout=3.0,
        decode_responses=True,
    )
    logger.info("worker_online", version=settings.app_version, env=settings.app_env)

    while True:
        try:
            client.ping()
            logger.info("worker_heartbeat", redis="ok")
        except exceptions.RedisError:
            logger.warning("worker_heartbeat", redis="unreachable")
        await asyncio.sleep(HEARTBEAT_INTERVAL)


def main() -> None:
    setup_logging(debug=settings.app_debug)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    task = loop.create_task(worker_loop())
    try:
        loop.run_until_complete(stop.wait())
    finally:
        task.cancel()
        loop.run_until_complete(asyncio.gather(task, return_exceptions=True))
        logger.info("worker_stopped")
        loop.close()


if __name__ == "__main__":
    main()
