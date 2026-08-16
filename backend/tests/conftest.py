"""Shared test fixtures. Env vars are set before the app package is imported
so that Settings reflects the test environment."""

import os

import pytest
from sqlalchemy import create_engine

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault(
    "DATABASE_URL",
    "mysql+pymysql://clipforge:clipforge@127.0.0.1:3306/clipforge?charset=utf8mb4",
)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")


def _database_reachable() -> bool:
    """True when the configured database answers."""
    url = os.environ.get("DATABASE_URL", "")
    try:
        engine = create_engine(url, connect_args={"connect_timeout": 2})
        with engine.connect():
            return True
    except Exception:
        return False


_DATABASE_REACHABLE = _database_reachable()


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Offline-degrade tests pin the 400/404/503 behavior when MySQL is
    *down* (e.g. on a dev machine without the stack). Inside the Docker
    stack the database answers, routes legitimately succeed, and these tests
    are skipped instead of failing."""
    if not _DATABASE_REACHABLE:
        return
    skip = pytest.mark.skip(
        reason="database is reachable; offline-degrade test not applicable"
    )
    for item in items:
        if "degrades" in item.name:
            item.add_marker(skip)
