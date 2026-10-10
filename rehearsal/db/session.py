"""Engine and session helpers."""

from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import settings


@lru_cache
def engine() -> Engine:
    return create_engine(settings().database_url, pool_pre_ping=True, pool_size=10, max_overflow=20)


@lru_cache
def _factory() -> sessionmaker[Session]:
    return sessionmaker(engine(), expire_on_commit=False)


@contextmanager
def session() -> Iterator[Session]:
    s = _factory()()
    try:
        yield s
        s.commit()
    except BaseException:
        s.rollback()
        raise
    finally:
        s.close()


def upgrade() -> None:
    """Applies Alembic migrations to head."""
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    here = Path(__file__).resolve().parent
    cfg = Config(str(here / "alembic.ini"))
    cfg.set_main_option("script_location", str(here / "migrations"))
    cfg.set_main_option("sqlalchemy.url", settings().database_url)
    command.upgrade(cfg, "head")
