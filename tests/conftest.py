"""Shared pytest fixtures for e2e/integration tests."""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from home_bills_agent.config import Settings
from home_bills_agent.payment.links import build_payment_link
from home_bills_agent.providers.anapa_vodokanal.client import StubVodokanalClient
from home_bills_agent.storage import CycleFSM, CycleStatus
from home_bills_agent.storage.models import Base


@pytest.fixture(autouse=True)
def skip_dotenv_env(monkeypatch):
    """Ensure .env is never loaded — hermetic tests."""
    monkeypatch.setenv("SKIP_DOTENV", "1")


@pytest.fixture
def engine():
    """In-memory SQLite engine with all tables created."""
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def factory(engine):
    """Per-test sessionmaker bound to in-memory SQLite."""
    return sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def fsm(factory):
    """Per-test CycleFSM instance."""
    return CycleFSM(factory)


@pytest.fixture
def settings(monkeypatch):
    """Settings with SKIP_DOTENV=1 so .env is never read."""
    monkeypatch.setenv("SKIP_DOTENV", "1")
    return Settings(skip_dotenv=True)


@pytest.fixture
def stub_client():
    """Stub Vodokanal client for dry-run (no real HTTP)."""
    return StubVodokanalClient(dry_run=True)


@pytest.fixture
def payment_link():
    """Helper to build a payment link for a test account."""
    return build_payment_link("1234567890")


@pytest.fixture
def sample_reading():
    """A sample whole-number reading value."""
    return 12345


@pytest.fixture
def current_period():
    """Current billing period string YYYY-MM."""
    return datetime.now().strftime("%Y-%m")


@pytest.fixture
def waiting_cycle(fsm, current_period):
    """Create a basic cycle in WAITING_READING status."""
    c = fsm.transition(
        "acc1",
        current_period,
        CycleStatus.WAITING_READING,
        event_type="cycle.start",
    )
    assert c is not None
    return c


@pytest.fixture
def dry_run_settings(monkeypatch):
    """Force DRY_RUN=True on settings so no real HTTP calls are made."""
    monkeypatch.setenv("SKIP_DOTENV", "1")
    monkeypatch.setenv("DRY_RUN", "true")
    monkeypatch.setenv("VODOKAN_LOGIN", "test_login")
    monkeypatch.setenv("VODOKAN_PASSWORD", "test_password")
    from home_bills_agent.config import Settings as _Settings
    return _Settings(skip_dotenv=True)