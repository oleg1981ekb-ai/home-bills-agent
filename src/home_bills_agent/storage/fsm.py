from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from home_bills_agent.storage.models import BillingCycle, Event


# Статусы (SPEC §7)
class CycleStatus:
    WAITING_READING = "WAITING_READING"
    AWAITING_ANOMALY_CONFIRMATION = "AWAITING_ANOMALY_CONFIRMATION"
    READING_SENT = "READING_SENT"
    ACCRUAL_PENDING = "ACCRUAL_PENDING"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PAID = "PAID"
    CANCELLED = "CANCELLED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


# Допустимые переходы (SPEC §7)
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    CycleStatus.WAITING_READING: {
        CycleStatus.READING_SENT,
        CycleStatus.AWAITING_ANOMALY_CONFIRMATION,
        CycleStatus.CANCELLED,
    },
    CycleStatus.AWAITING_ANOMALY_CONFIRMATION: {
        CycleStatus.READING_SENT,
        CycleStatus.WAITING_READING,
        CycleStatus.CANCELLED,
    },
    CycleStatus.READING_SENT: {
        CycleStatus.AWAITING_PAYMENT,
        CycleStatus.ACCRUAL_PENDING,
    },
    CycleStatus.ACCRUAL_PENDING: {
        CycleStatus.AWAITING_PAYMENT,
        CycleStatus.MANUAL_REVIEW,
    },
    CycleStatus.AWAITING_PAYMENT: {
        CycleStatus.PAID,
    },
    CycleStatus.PAID: set(),
    CycleStatus.CANCELLED: set(),
    CycleStatus.MANUAL_REVIEW: set(),
}


class CycleFSM:
    """FSM цикла биллинга на основе SQLite.

    Использует транзакцию для атомарной проверки и обновления состояния.
    """

    def __init__(self, session_factory, *, dry_run: bool = False) -> None:
        self._session_factory = session_factory
        self._dry_run = dry_run
        self._dry_run_cache: dict[tuple[str, str], BillingCycle] = {}

    def _get_active_cycle(
        self, session: Session, account_id: str, period: str
    ) -> BillingCycle | None:
        # В dry-run режиме сначала проверяем кэш
        if self._dry_run:
            key = (account_id, period)
            if key in self._dry_run_cache:
                return self._dry_run_cache[key]
        stmt = select(BillingCycle).where(
            BillingCycle.account_id == account_id,
            BillingCycle.period == period,
        )
        return session.execute(stmt).scalar_one_or_none()

    def transition(
        self,
        account_id: str,
        period: str,
        new_status: str,
        *,
        reading_value: Decimal | None = None,
        previous_reading: Decimal | None = None,
        consumption: Decimal | None = None,
        reading_source: str | None = None,
        debt_before: Decimal | None = None,
        debt_after: Decimal | None = None,
        payment_link: str | None = None,
        paid_marked_at: datetime | None = None,
        payment_verified_at: datetime | None = None,
        next_check_at: datetime | None = None,
        event_type: str | None = None,
        event_description: str | None = None,
    ) -> BillingCycle | None:
        """Выполнить переход цикла в новое состояние.

        Возвращает BillingCycle при успехе, None при неудаче.
        Если dry_run=True — изменения не сохраняются в БД.
        """
        with self._session_factory() as session:
            cycle = self._get_active_cycle(session, account_id, period)

            if cycle is None:
                # Создаём новый цикл (только WAITING_READING)
                if new_status != CycleStatus.WAITING_READING:
                    return None
                cycle = BillingCycle(
                    account_id=account_id,
                    period=period,
                    status=new_status,
                    reading_value=reading_value,
                    previous_reading=previous_reading,
                    consumption=consumption,
                    reading_source=reading_source,
                    debt_before=debt_before,
                    debt_after=debt_after,
                    payment_link=payment_link,
                    paid_marked_at=paid_marked_at,
                    payment_verified_at=payment_verified_at,
                    next_check_at=next_check_at,
                )
                session.add(cycle)
            else:
                # Идемпотентность: повтор того же состояния не является ошибкой.
                if new_status == cycle.status:
                    pass
                else:
                    allowed = ALLOWED_TRANSITIONS.get(cycle.status, set())
                    if new_status not in allowed:
                        return None
                    cycle.status = new_status
                    if reading_value is not None:
                        cycle.reading_value = reading_value
                    if previous_reading is not None:
                        cycle.previous_reading = previous_reading
                    if consumption is not None:
                        cycle.consumption = consumption
                    if reading_source is not None:
                        cycle.reading_source = reading_source
                    if debt_before is not None:
                        cycle.debt_before = debt_before
                    if debt_after is not None:
                        cycle.debt_after = debt_after
                    if payment_link is not None:
                        cycle.payment_link = payment_link
                    if paid_marked_at is not None:
                        cycle.paid_marked_at = paid_marked_at
                    if payment_verified_at is not None:
                        cycle.payment_verified_at = payment_verified_at
                    if next_check_at is not None:
                        cycle.next_check_at = next_check_at
                    if new_status == CycleStatus.ACCRUAL_PENDING:
                        cycle.retry_count = (cycle.retry_count or 0) + 1

            # В dry-run режиме не записываем событие и не коммитим
            if not self._dry_run and event_type:
                event = Event(
                    account_id=account_id,
                    period=period,
                    event_type=event_type,
                    description=event_description,
                    masked_account=f"***{account_id[-4:]}",
                )
                session.add(event)

            if not self._dry_run:
                session.commit()
                session.refresh(cycle)
            else:
                # В dry-run режиме сохраняем в кэш и откатываем сессию
                self._dry_run_cache[(account_id, period)] = cycle
                session.rollback()

            return cycle

    def get_active_cycle(
        self, account_id: str, period: str
    ) -> BillingCycle | None:
        """Получить активный цикл (без транзакции)."""
        with self._session_factory() as session:
            return self._get_active_cycle(session, account_id, period)

    def is_idempotent(self, account_id: str, period: str) -> bool:
        """Проверить, можно ли повторить операцию без побочных эффектов."""
        with self._session_factory() as session:
            cycle = self._get_active_cycle(session, account_id, period)
            if cycle is None:
                return True
            return cycle.status in {
                CycleStatus.PAID,
                CycleStatus.CANCELLED,
                CycleStatus.MANUAL_REVIEW,
            }