"""Тесты FSM переходов и идемпотентности для billing_cycles."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from home_bills_agent.storage.fsm import CycleFSM, CycleStatus
from home_bills_agent.storage.models import Base, BillingCycle, ReadingsCache


def _make_session_factory() -> sessionmaker:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def test_waiting_reading_period_starts():
    """WAITING_READING создаётся при начале окна (SPEC §7)."""
    session_factory = _make_session_factory()
    fsm = CycleFSM(session_factory)
    cycle = fsm.transition(
        "acc1",
        "2026-11",
        CycleStatus.WAITING_READING,
        event_type="cycle.start",
        event_description="Наступил период 2026-11",
    )
    assert cycle is not None
    assert cycle.status == CycleStatus.WAITING_READING


def test_reading_sent_after_valid_checks():
    """WAITING_READING -> READING_SENT после прохождения проверок."""
    session_factory = _make_session_factory()
    fsm = CycleFSM(session_factory)
    fsm.transition("acc2", "2026-11", CycleStatus.WAITING_READING, event_type="cycle.start")
    cycle = fsm.transition(
        "acc2",
        "2026-11",
        CycleStatus.READING_SENT,
        reading_value=Decimal(100),
        previous_reading=Decimal(95),
        consumption=Decimal(5),
        reading_source="text",
        debt_before=Decimal(300),
        debt_after=Decimal(295),
        event_type="reading.sent",
        event_description="Показание передано",
    )
    assert cycle is not None
    assert cycle.status == CycleStatus.READING_SENT
    assert cycle.reading_value == Decimal(100)


def test_anomaly_goes_to_awaiting_confirmation():
    """Аномалия -> AWAITING_ANOMALY_CONFIRMATION."""
    session_factory = _make_session_factory()
    fsm = CycleFSM(session_factory)
    fsm.transition("acc3", "2026-11", CycleStatus.WAITING_READING, event_type="cycle.start")
    cycle = fsm.transition(
        "acc3",
        "2026-11",
        CycleStatus.AWAITING_ANOMALY_CONFIRMATION,
        event_type="anomaly",
        event_description="Аномалия расхода, ждём подтверждения",
    )
    assert cycle is not None
    assert cycle.status == CycleStatus.AWAITING_ANOMALY_CONFIRMATION


def test_confirm_anomaly_allows_reading_sent():
    """AWAITING_ANOMALY_CONFIRMATION -> READING_SENT по подтверждению."""
    session_factory = _make_session_factory()
    fsm = CycleFSM(session_factory)
    fsm.transition("acc4", "2026-11", CycleStatus.WAITING_READING, event_type="cycle.start")
    fsm.transition(
        "acc4",
        "2026-11",
        CycleStatus.AWAITING_ANOMALY_CONFIRMATION,
        event_type="anomaly",
    )
    cycle = fsm.transition(
        "acc4",
        "2026-11",
        CycleStatus.READING_SENT,
        reading_value=Decimal(150),
        event_type="reading.sent",
        event_description="Подтверждено, передано",
    )
    assert cycle is not None
    assert cycle.status == CycleStatus.READING_SENT


def test_invalid_transition_rejected():
    """Запрещённый переход должен быть отклонён."""
    session_factory = _make_session_factory()
    fsm = CycleFSM(session_factory)
    fsm.transition("acc5", "2026-11", CycleStatus.WAITING_READING, event_type="cycle.start")
    fsm.transition(
        "acc5",
        "2026-11",
        CycleStatus.READING_SENT,
        reading_value=Decimal(10),
        event_type="reading.sent",
    )
    # Из READING_SENT невозможно перейти сразу в PAID (нужен AWAITING_PAYMENT)
    result = fsm.transition("acc5", "2026-11", CycleStatus.PAID, event_type="payment.claimed")
    assert result is None


def test_idempotent_replay_returns_existing():
    """Идемпотентный replay возвращает существующий результат, не создаёт новый."""
    session_factory = _make_session_factory()
    fsm = CycleFSM(session_factory)
    first = fsm.transition("acc6", "2026-11", CycleStatus.WAITING_READING, event_type="cycle.start")
    second = fsm.transition("acc6", "2026-11", CycleStatus.WAITING_READING, event_type="cycle.start")
    assert first is not None
    assert second is not None


def test_readings_cache_filters_integers():
    """readings_cache фильтруется по целочисленным значениям (SPEC §6.2, ADR-005)."""
    session_factory = _make_session_factory()

    with session_factory() as session:
        session.add(
            ReadingsCache(
                account_id="acc7",
                period="2026-11",
                reading_date=datetime(2026, 11, 1),
                reading_value=Decimal(100),
                source="text",
                is_integer=1,
            )
        )
        session.add(
            ReadingsCache(
                account_id="acc7",
                period="2026-11",
                reading_date=datetime(2026, 11, 1),
                reading_value=Decimal("569.63"),
                source="calculated",
                is_integer=0,
            )
        )
        session.commit()
        rows = session.execute(select(ReadingsCache)).scalars().all()
        ints = [r for r in rows if r.is_integer == 1]
        assert len(ints) == 1
        assert ints[0].reading_value == Decimal(100)


def test_dry_run_mode_does_not_persist():
    """В DRY_RUN режиме изменения не сохраняются в БД."""
    session_factory = _make_session_factory()
    fsm = CycleFSM(session_factory, dry_run=True)

    c = fsm.transition("acc8", "2026-11", CycleStatus.WAITING_READING, event_type="cycle.start")
    assert c is not None
    assert c.status == CycleStatus.WAITING_READING

    # Проверяем, что в БД ничего не сохранено
    with session_factory() as session:
        rows = session.execute(select(BillingCycle)).scalars().all()
        assert len(rows) == 0
