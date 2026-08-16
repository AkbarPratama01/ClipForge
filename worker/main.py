"""ClipForge worker entrypoint.

Runs three coroutines:

- heartbeat: Redis connectivity (Phase 1)
- job_loop: consume Redis jobs — Phase 3 consumes DOWNLOAD_VIDEO (yt-dlp →
  checksum → Drive upload); the full job state machine arrives in Phase 5
- DriveWatcher: polls ``01_Inbox`` when Google Drive OAuth is configured (§66)

Graceful shutdown on SIGTERM/SIGINT.
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

    tasks = [loop.create_task(worker_loop())]
    try:
        from worker.jobs import job_loop

        tasks.append(loop.create_task(job_loop()))
    except Exception:
        logger.warning("job_loop_init_failed", exc_info=True)

    try:
        from worker.watcher import watcher_enabled

        if watcher_enabled():
            from worker.watcher import DriveWatcher

            tasks.append(loop.create_task(DriveWatcher().run()))
        else:
            logger.info("drive_watcher_disabled", reason="google drive not configured")
    except Exception:
        logger.warning("drive_watcher_init_failed", exc_info=True)

    try:
        loop.run_until_complete(stop.wait())
    finally:
        for task in tasks:
            task.cancel()
        loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
        logger.info("worker_stopped")
        loop.close()


if __name__ == "__main__":
    main()
