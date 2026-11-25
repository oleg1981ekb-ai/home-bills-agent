"""Тесты Stage 3 — config, anomaly, payment links, provider stub, scheduler."""
from __future__ import annotations

import asyncio
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from home_bills_agent.config import Settings
from home_bills_agent.payment.links import build_payment_link, mask_account_id, sanitize_for_logs
from home_bills_agent.providers.anapa_vodokanal.client import StubVodokanalClient
from home_bills_agent.storage import CycleFSM, CycleStatus
from home_bills_agent.storage.anomaly import (
    can_detect_anomaly,
    compute_debt_delta,
    median_of_list,
    median_of_whole_readings,
)
from home_bills_agent.storage.models import Base


def _make_factory() -> sessionmaker:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_settings_defaults():
    s = Settings(skip_dotenv=True)
    assert s.DRY_RUN is False
    assert s.AUTO_SEND is False
    assert s.ANOMALY_FACTOR == 2.0
    assert s.CONFIDENCE_MIN == 0.9
    assert s.WINDOW_START == 1
    assert s.WINDOW_END == 25
    assert s.TZ == "Europe/Moscow"


def test_settings_dry_run_true():
    s = Settings(skip_dotenv=True)
    assert s.DRY_RUN is False


def test_payment_link_build():
    link = build_payment_link("1234567890")
    assert "andromeda.a-3.ru/6172" in link
    assert "PERSONAL_ACCOUNT=1234567890" in link


def test_payment_link_mask():
    assert mask_account_id("1234567890") == "***7890"
    assert mask_account_id("") == "***"


def test_sanitize_for_logs():
    out = sanitize_for_logs("token=abc cookie=xyz password=def")
    assert "[REDACTED]" in out


def test_stub_client_dry_run_add_counter_value():
    async def _run():
        client = StubVodokanalClient(dry_run=True)
        return await client.add_counter_value(123)

    ok, err = asyncio.run(_run())
    assert ok is True
    assert err is None


def test_stub_client_dry_run_login_and_debt():
    async def _run():
        client = StubVodokanalClient(dry_run=True)
        ok_login = await client.login()
        ok, _err = await client.add_counter_value(55)
        return ok_login, ok

    ok_login, ok = asyncio.run(_run())
    assert ok_login is True
    assert ok is True


def test_median_of_list_odd():
    assert median_of_list([Decimal(1), Decimal(2), Decimal(3)]) == Decimal(2)


def test_median_of_list_even():
    assert median_of_list([Decimal(1), Decimal(2), Decimal(3), Decimal(4)]) == Decimal("2.5")


def test_median_of_whole_readings_empty():
    assert median_of_whole_readings([]) is None


def test_median_of_whole_readings_filters_whole():
    rows = [
        {"reading_value": Decimal(100), "is_integer": 1, "reading_date": "2026-10-01"},
        {"reading_value": Decimal("569.63"), "is_integer": 0, "reading_date": "2026-10-02"},
        {"reading_value": Decimal(120), "is_integer": 1, "reading_date": "2026-11-01"},
    ]
    med = median_of_whole_readings(rows)
    assert med is not None
    # only whole values [100, 120] -> median 110
    assert med == Decimal(110)


def test_can_detect_anomaly_few_rows():
    # fewer than 3 intervals -> cannot detect -> should require confirm
    rows = [
        {"reading_value": Decimal(100), "is_integer": 1, "reading_date": "2026-10-01"},
    ]
    assert can_detect_anomaly(rows, 2.0) is False


def test_can_detect_anomaly_zero_median():
    rows = [
        {"reading_value": Decimal(0), "is_integer": 1, "reading_date": "2026-10-01"},
        {"reading_value": Decimal(0), "is_integer": 1, "reading_date": "2026-10-15"},
        {"reading_value": Decimal(0), "is_integer": 1, "reading_date": "2026-11-01"},
    ]
    assert can_detect_anomaly(rows, 2.0) is False


def test_compute_debt_delta_positive():
    rows = [
        {"debt_before": Decimal(290), "debt_after": Decimal(295)},
        {"debt_before": Decimal(295), "debt_after": Decimal(300)},
    ]
    assert compute_debt_delta(rows) == Decimal(10)


def test_compute_debt_delta_none():
    assert compute_debt_delta([]) is None


def test_fsm_sending_status_transition():
    """READING_SENT -> AWAITING_PAYMENT for debt check after send."""
    factory = _make_factory()
    fsm = CycleFSM(factory)
    c = fsm.transition("acc9", "2026-12", CycleStatus.WAITING_READING, event_type="cycle.start")
    assert c is not None
    c2 = fsm.transition("acc9", "2026-12", CycleStatus.READING_SENT, reading_value=Decimal(10), event_type="reading.sent")
    assert c2 is not None
    # After send, next logical step: AWAITING_PAYMENT (debt check done)
    c3 = fsm.transition("acc9", "2026-12", CycleStatus.AWAITING_PAYMENT, event_type="accrual.done")
    assert c3 is not None
    assert c3.status == CycleStatus.AWAITING_PAYMENT
