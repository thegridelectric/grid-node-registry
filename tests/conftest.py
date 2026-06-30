"""Shared fixtures for the dev-universe layered harness.

The integration layers need a real Postgres (the registry is Postgres-backed; no
sqlite stand-in). By default we spin up an ephemeral one with `testcontainers`
(hermetic, CI-friendly). Set `GNR_TEST_PG_URL` to point the suite at an
already-running Postgres instead — e.g. the dev docker-compose on
`localhost:5435` — for a faster local loop. When neither an override nor a
working Docker/testcontainers is available, the integration layers self-skip.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from gnr.db.models import Base


@pytest.fixture(scope="session")
def pg_url():
    """A Postgres URL for the integration layers: compose-opt-in, else testcontainers."""
    override = os.environ.get("GNR_TEST_PG_URL")
    if override:
        yield override
        return

    try:
        from testcontainers.postgres import PostgresContainer
    except ImportError:
        pytest.skip("no GNR_TEST_PG_URL and testcontainers not installed")

    try:
        pg = PostgresContainer("postgres:16", driver="psycopg")
        pg.start()
    except Exception as e:  # Docker not available / image pull failed
        pytest.skip(f"could not start a testcontainers Postgres: {e}")

    # The yield is outside the start try/except so a *test* failure thrown back
    # in here is never mistaken for an infra-unavailable skip.
    try:
        yield pg.get_connection_url()
    finally:
        pg.stop()


@pytest.fixture(scope="session")
def engine(pg_url):
    """A SQLAlchemy engine on the harness Postgres, with the schema created."""
    eng = create_engine(pg_url, future=True)
    Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session_factory(engine):
    """A sessionmaker bound to the harness engine — hand this to PostgresAuthority."""
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False)


@pytest.fixture
def db_session(session_factory):
    """A single session for direct fixture/test use (seeding, assertions)."""
    with session_factory() as s:
        yield s
