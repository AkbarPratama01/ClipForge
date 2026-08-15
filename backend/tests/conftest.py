"""Shared test fixtures. Env vars are set before the app package is imported
so that Settings reflects the test environment."""

import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("APP_DEBUG", "false")
os.environ.setdefault(
    "DATABASE_URL",
    "mysql+pymysql://clipforge:clipforge@127.0.0.1:3306/clipforge?charset=utf8mb4",
)
os.environ.setdefault("REDIS_URL", "redis://127.0.0.1:6379/0")
