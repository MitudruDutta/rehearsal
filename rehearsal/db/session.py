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
    cfg = settings()
    # pool_recycle: managed databases and their proxies drop long-idle connections; replace them before that happens
    return create_engine(cfg.database_url, pool_pre_ping=True, pool_size=cfg.db_pool_size, max_overflow=cfg.db_max_overflow, pool_recycle=1800)


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
    cfg.set_main_option("sqlalchemy.url", settings().database_url.replace("%", "%%"))
    command.upgrade(cfg, "head")
