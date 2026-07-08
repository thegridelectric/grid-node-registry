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
from urllib.parse import quote

# The harness always runs a dev universe. Set before any gnr import: Settings
# requires `universe` (no default), and `gnr.db.session` constructs Settings at
# import time.
os.environ.setdefault("GNR_UNIVERSE", "d1")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from gnr.db.models import Base


@pytest.fixture(autouse=True)
def _xdg_under_tmp(tmp_path_factory, monkeypatch):
    """Redirect XDG base dirs under tmp so the gwbase actors' per-actor loggers
    (Layer 2) never touch the real home directory."""
    base = tmp_path_factory.mktemp("xdg")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(base / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(base / "data"))
    monkeypatch.setenv("XDG_STATE_HOME", str(base / "state"))


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


@pytest.fixture(scope="session")
def rabbit_url():
    """A RabbitMQ AMQP URL for Layer 2: compose-opt-in, else testcontainers.

    Set `GNR_TEST_RABBIT_URL` to point at an already-running broker (e.g. the
    shared `gw-dev-rabbit` on its `d1__1` vhost) for a fast local loop; otherwise
    an ephemeral `testcontainers` RabbitMQ is started. Self-skips when neither an
    override nor a working Docker/testcontainers is available.
    """
    override = os.environ.get("GNR_TEST_RABBIT_URL")
    if override:
        yield override
        return

    try:
        from testcontainers.rabbitmq import RabbitMqContainer
    except ImportError:
        pytest.skip("no GNR_TEST_RABBIT_URL and testcontainers not installed")

    try:
        rabbit = RabbitMqContainer("rabbitmq:3.13")
        rabbit.start()
    except Exception as e:  # Docker not available / image pull failed
        pytest.skip(f"could not start a testcontainers RabbitMQ: {e}")

    try:
        p = rabbit.get_connection_params()
        vhost = quote(rabbit.vhost or "/", safe="")
        yield f"amqp://{rabbit.username}:{rabbit.password}@{p.host}:{p.port}/{vhost}"
    finally:
        rabbit.stop()
