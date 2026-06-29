"""SQLAlchemy engine + session factory for the Grid Node Registry.

The engine is built from `gnr.settings.Settings` (`GNR_DB_URL` ← `.env`), so it
points at whatever Postgres the environment configures. `SessionLocal` is the
sessionmaker the registry's data access uses.
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from gnr.settings import Settings

settings = Settings()

engine = create_engine(
    settings.db_url.get_secret_value(),
    echo=settings.db_echo,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)
