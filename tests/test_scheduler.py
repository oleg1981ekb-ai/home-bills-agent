"""Тесты сверки после отправки и проверки оплаты (scheduler/jobs.py)."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from home_bills_agent.scheduler.jobs import check_payment, reconcile_after_send
from home_bills_agent.storage import CycleFSM, CycleStatus
from home_bills_agent.storage.models import Base


def _make_factory() -> sessionmaker:
    engine = create_engine("sqlite://", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _now() -> datetime:
    return datetime(2026, 12, 15, 10, 0, 0)


def _sent_cycle(fsm: CycleFSM, account_id: str, period: str = "2026-12"):
    fsm.transition(account_id, period, CycleStatus.WAITING_READING, event_type="cycle.start")
    fsm.transition(
        account_id,
        period,
        CycleStatus.READING_SENT,
        reading_value=Decimal(100),
        event_type="reading.sent",
    )


def test_reconcile_after_send_debt_seen():
    factory = _make_factory()
    fsm = CycleFSM(factory)
    _sent_cycle(fsm, "acc1")

    status = reconcile_after_send(
        fsm,
        "acc1",
        "2026-12",
        reading_visible=True,
        debt_after=Decimal(125),
        now=_now(),
    )
    assert status == CycleStatus.AWAITING_PAYMENT

    cycle = fsm.get_active_cycle("acc1", "2026-12")
    assert cycle is not None
    assert cycle.status == CycleStatus.AWAITING_PAYMENT
    assert cycle.debt_after == Decimal(125)
    assert cycle.next_check_at == _now() + timedelta(days=1)


def test_reconcile_after_send_accrual_pending():
    factory = _make_factory()
    fsm = CycleFSM(factory)
    _sent_cycle(fsm, "acc2")

    status = reconcile_after_send(
        fsm,
        "acc2",
        "2026-12",
        reading_visible=False,
        debt_after=None,
        now=_now(),
    )
    assert status == CycleStatus.ACCRUAL_PENDING

    cycle = fsm.get_active_cycle("acc2", "2026-12")
    assert cycle.status == CycleStatus.ACCRUAL_PENDING
    assert cycle.next_check_at == _now() + timedelta(days=1)


def test_reconcile_after_send_idempotent_when_not_sent():
    factory = _make_factory()
    fsm = CycleFSM(factory)
    _sent_cycle(fsm, "acc3")
    # Move out of READING_SENT
    fsm.transition("acc3", "2026-12", CycleStatus.AWAITING_PAYMENT, event_type="accrual.done")

    status = reconcile_after_send(
        fsm,
        "acc3",
        "2026-12",
        reading_visible=True,
        debt_after=Decimal(50),
        now=_now(),
    )
    assert status == CycleStatus.AWAITING_PAYMENT


def test_reconcile_after_send_no_cycle():
    factory = _make_factory()
    fsm = CycleFSM(factory)
    assert reconcile_after_send(fsm, "ghost", "2026-12", reading_visible=True, debt_after=Decimal(1), now=_now()) is None


def test_check_payment_confirmed():
    factory = _make_factory()
    fsm = CycleFSM(factory)
    _sent_cycle(fsm, "acc4")
    fsm.transition(
        "acc4",
        "2026-12",
        CycleStatus.AWAITING_PAYMENT,
        event_type="accrual.done",
    )
    fsm.transition(
        "acc4",
        "2026-12",
        CycleStatus.PAID,
        paid_marked_at=_now(),
        event_type="payment.claimed",
    )

    status = check_payment(
        fsm,
        "acc4",
        "2026-12",
        debt_before=Decimal(125),
        debt_now=Decimal(100),
        now=_now(),
    )
    assert status == CycleStatus.PAID

    cycle = fsm.get_active_cycle("acc4", "2026-12")
    assert cycle.payment_verified_at == _now()
    assert cycle.debt_after == Decimal(100)


def test_check_payment_not_confirmed_schedules_recheck():
    factory = _make_factory()
    fsm = CycleFSM(factory)
    _sent_cycle(fsm, "acc5")
    fsm.transition("acc5", "2026-12", CycleStatus.AWAITING_PAYMENT, event_type="accrual.done")
    fsm.transition(
        "acc5",
        "2026-12",
        CycleStatus.PAID,
        paid_marked_at=_now(),
        event_type="payment.claimed",
    )

    status = check_payment(
        fsm,
        "acc5",
        "2026-12",
        debt_before=Decimal(125),
        debt_now=Decimal(125),
        now=_now(),
    )
    assert status == CycleStatus.PAID

    cycle = fsm.get_active_cycle("acc5", "2026-12")
    assert cycle.payment_verified_at is None
    assert cycle.next_check_at == _now() + timedelta(days=1)
    assert cycle.retry_count == 1


def test_check_payment_no_cycle():
    factory = _make_factory()
    fsm = CycleFSM(factory)
    assert (
        check_payment(fsm, "ghost", "2026-12", debt_before=Decimal(1), debt_now=Decimal(1), now=_now())
        is None
    )
