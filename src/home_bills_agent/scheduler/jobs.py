"""APScheduler jobs for billing cycle reminders and checks."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from home_bills_agent.config import settings
from home_bills_agent.storage import CycleFSM, CycleStatus, init_db
from home_bills_agent.storage.anomaly import compute_debt_delta

SESSION_FACTORY = init_db()
FSM = CycleFSM(SESSION_FACTORY, dry_run=settings.DRY_RUN)


def _period_now() -> str:
    return datetime.now().strftime("%Y-%m")


def _sent_message_key(account_id: str, period: str) -> tuple[str, str]:
    """Key for sent-message dedup."""
    return (account_id, period)


def check_due_reminders() -> list[str]:
    """Check due reminders for current period. Returns list of actions."""
    period = _period_now()
    cycle = FSM.get_active_cycle(settings.ACCOUNT_ID, period)
    actions: list[str] = []
    if cycle is None:
        # No cycle yet -> no reminder needed
        return actions

    if cycle.status in (CycleStatus.WAITING_READING, CycleStatus.ACCRUAL_PENDING):
        day = int(period.split("-")[1])
        today = datetime.now()
        if cycle.status == CycleStatus.WAITING_READING:
            # Morning reminder from REMINDER_START_DAY to WINDOW_END
            if settings.REMINDER_START_DAY <= day <= settings.WINDOW_END:
                actions.append(
                    f"morning_reminder:{cycle.account_id}:{period}"
                )
        elif cycle.status == CycleStatus.ACCRUAL_PENDING and (
            cycle.next_check_at and today > cycle.next_check_at
        ):
            # Recheck via ACCRUAL_PENDING checks (1,3,6 days)
            actions.append(f"accrual_recheck:{cycle.account_id}:{period}")
    elif cycle.status == CycleStatus.READING_SENT:
        # Verify after sending; if debt not yet changed -> schedule accrual recheck
        compute_debt_delta([cycle.__dict__] if hasattr(cycle, "__dict__") else [])
        actions.append(f"accrual_check:{cycle.account_id}:{period}")

    return actions


def next_accrual_check_at(status_cycle, days: list[int]) -> datetime | None:
    """Return the next accrual check datetime for ACCRUAL_PENDING."""
    if status_cycle is None:
        return None
    base = status_cycle.next_check_at or datetime.now()
    candidates = sorted(
        [base + __import__("datetime").timedelta(days=d) for d in days if d > 0]
    )
    if not candidates:
        return None
    return candidates[0]


def reconcile_after_send(
    fsm: CycleFSM,
    account_id: str,
    period: str,
    *,
    reading_visible: bool,
    debt_after: Decimal | None,
    now: datetime,
) -> str | None:
    """Post-send reconciliation after LK re-read.

    READING_SENT -> AWAITING_PAYMENT when reading visible and debt read;
    otherwise READING_SENT -> ACCRUAL_PENDING with recheck in 1 day.
    """
    cycle = fsm.get_active_cycle(account_id, period)
    if cycle is None:
        return None
    if cycle.status != CycleStatus.READING_SENT:
        return cycle.status

    if reading_visible and debt_after is not None:
        c = fsm.transition(
            account_id,
            period,
            CycleStatus.AWAITING_PAYMENT,
            debt_after=debt_after,
            next_check_at=now + timedelta(days=1),
            event_type="accrual.seen",
            event_description=f"Начисление появилось, долг после: {debt_after}.",
        )
        return c.status if c else None

    c = fsm.transition(
        account_id,
        period,
        CycleStatus.ACCRUAL_PENDING,
        next_check_at=now + timedelta(days=1),
        event_type="accrual.pending",
        event_description="Долг не изменился, повторная проверка через 1 день.",
    )
    return c.status if c else None


def check_payment(
    fsm: CycleFSM,
    account_id: str,
    period: str,
    *,
    debt_before: Decimal | None,
    debt_now: Decimal | None,
    now: datetime,
) -> str | None:
    """Verify payment after user pressed 'Оплачено'.

    PAID stays PAID; payment_verified_at set when debt decreased.
    Returns final status.
    """
    cycle = fsm.get_active_cycle(account_id, period)
    if cycle is None:
        return None
    if cycle.status != CycleStatus.PAID:
        return cycle.status

    if debt_before is not None and debt_now is not None and debt_now < debt_before:
        fsm.update(
            account_id,
            period,
            payment_verified_at=now,
            debt_after=debt_now,
        )
        fsm.transition(
            account_id,
            period,
            CycleStatus.PAID,
            event_type="payment.verified",
            event_description=f"Оплата подтверждена, долг снизился с {debt_before} до {debt_now}.",
        )
        return CycleStatus.PAID

    # Not yet confirmed; schedule recheck via update (stay PAID).
    fsm.update(
        account_id,
        period,
        next_check_at=now + timedelta(days=1),
        retry_count=(cycle.retry_count or 0) + 1,
        last_checked_at=now,
    )
    return CycleStatus.PAID
