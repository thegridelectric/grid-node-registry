"""SQLAlchemy engine + session factory for the Grid Node Registry.

The engine is built from `gnr.settings.Settings` (`GNR_DB_URL` ← `.env`), so it
points at whatever Postgres the environment configures — **lazily, on first
use**: importing this module (e.g. for `gnr --help`) needs no environment; only
actually opening a session does. `SessionLocal` is the session factory the
registry's data access uses.
"""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from gnr.settings import Settings


@lru_cache(maxsize=1)
def _session_factory() -> sessionmaker[Session]:
    settings = Settings()
    engine = create_engine(
        settings.db_url.get_secret_value(),
        echo=settings.db_echo,
        future=True,
    )
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


def SessionLocal() -> Session:
    """Open a session on the env-configured engine (built on first call)."""
    return _session_factory()()
