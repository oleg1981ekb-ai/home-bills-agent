"""Модели данных (SQLAlchemy) — единственный источник истины.

Таблицы:
- billing_cycles — основной цикл (составной PK: account_id + period)
- readings_cache — история показаний для медианы
- events — журнал событий (ЛС маскируется)
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    Numeric,
    String,
)
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""


class BillingCycle(Base):
    """Основная таблица циклов биллинга.

    Составной PRIMARY KEY: (account_id, period).
    Period формат: YYYY-MM.
    """

    __tablename__ = "billing_cycles"

    account_id = Column(String, primary_key=True)
    period = Column(String, primary_key=True)  # YYYY-MM

    status = Column(String, index=True, nullable=False)
    reading_value = Column(Numeric, nullable=True)
    previous_reading = Column(Numeric, nullable=True)
    consumption = Column(Numeric, nullable=True)
    reading_source = Column(String, nullable=True)  # text | photo

    debt_before = Column(Numeric, nullable=True)
    debt_after = Column(Numeric, nullable=True)
    payment_link = Column(String, nullable=True)

    paid_marked_at = Column(DateTime, nullable=True)
    payment_verified_at = Column(DateTime, nullable=True)

    retry_count = Column(Integer, default=0, nullable=False)
    next_check_at = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        nullable=False,
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<BillingCycle(account_id={self.account_id!r}, "
            f"period={self.period!r}, status={self.status!r})>"
        )


class ReadingsCache(Base):
    """Кэш показаний для расчёта медианы.

    Дробные значения (начисленные водоканалом) исключаются из расчёта.
    """

    __tablename__ = "readings_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String, index=True, nullable=False)
    period = Column(String, index=True, nullable=False)
    reading_date = Column(DateTime, nullable=False)
    reading_value = Column(Numeric, nullable=False)
    source = Column(String, nullable=False)  # text | photo | calculated
    is_integer = Column(Integer, default=1, nullable=False)  # 1 = целое, 0 = дробное


class Event(Base):
    """Журнал событий для диагностики и MANUAL_REVIEW.

    Лицевой счёт маскируется.
    """

    __tablename__ = "events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String, index=True, nullable=False)
    period = Column(String, nullable=True)
    event_type = Column(String, index=True, nullable=False)
    description = Column(String, nullable=True)
    masked_account = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class SentMessage(Base):
    """Sent-message ledger for reminder de-duplication and recovery.

    Keyed by (account_id, period, message_id) is too narrow; use
    (account_id, period, sent_at) or idempotency key from event.
    For simplicity: composite key (account_id, period) for latest sent state.
    """

    __tablename__ = "sent_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    account_id = Column(String, index=True, nullable=False)
    period = Column(String, index=True, nullable=False)
    telegram_message_id = Column(String, nullable=True)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(String, nullable=False, default="sent")
    details = Column(String, nullable=True)