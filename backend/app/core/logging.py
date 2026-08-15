"""Structured logging via structlog.

JSON output in production (machine-parseable, secrets never logged), a
readable console renderer in development. Standard-library loggers (uvicorn,
SQLAlchemy, ...) are routed through structlog's stdlib integration.
"""

import logging
import sys

import structlog


def setup_logging(*, debug: bool = False) -> None:
    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if debug:
        renderer: structlog.types.Processor = structlog.dev.ConsoleRenderer()
        level = logging.DEBUG
    else:
        renderer = structlog.processors.JSONRenderer(ensure_ascii=False)
        level = logging.INFO

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)
