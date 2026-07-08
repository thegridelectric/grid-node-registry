"""Layer 0 — the universe guard-rails on `Settings` (no infra).

A registry instance is scoped to exactly one universe, declared by the
deployer with no default; a production (`w…`) universe refuses to boot while
its trust machinery is still stubs. See executor *Universes* and the
populate-and-deploy spoke.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from gnr.settings import Settings


def _settings(universe: str) -> Settings:
    # _env_file=None: exercise the validators, not whatever .env is lying around.
    return Settings(universe=universe, _env_file=None)


def test_universe_is_required(monkeypatch):
    monkeypatch.delenv("GNR_UNIVERSE", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_dev_and_hybrid_universes_boot():
    assert _settings("d1").universe == "d1"
    assert _settings("hw1").universe == "hw1"


def test_universe_must_be_single_lowercase_word():
    for bad in ("D1", "d1.isone", "d 1", "1d", ""):
        with pytest.raises(ValidationError):
            _settings(bad)


def test_universe_kind_letter_enforced():
    with pytest.raises(ValidationError, match="kind letter"):
        _settings("x1")


def test_production_universe_refuses_to_boot():
    """The prod boot refusal: `w…` cannot be stood up while the trust
    machinery (Proof verification, validation certs, encrypted positions) is
    stubbed. Remove stubs from `gnr.settings.PROD_STUBS` as each lands."""
    with pytest.raises(ValidationError, match="cannot boot yet"):
        _settings("w")
    with pytest.raises(ValidationError, match="cannot boot yet"):
        _settings("w1")
