"""Alembic environment — wired to the ClipForge settings and declarative Base."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from app.core.config import settings
from app.database.base import Base

# Import models so Alembic autogenerate sees every table.
from app.modules.analysis import models as analysis_models  # noqa: F401
from app.modules.publishing import models as publishing_models  # noqa: F401
from app.modules.rendering import models as rendering_models  # noqa: F401
from app.modules.storage import models as storage_models  # noqa: F401
from app.modules.transcription import models as transcription_models  # noqa: F401
from app.modules.videos import models as videos_models  # noqa: F401

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", settings.database_url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
