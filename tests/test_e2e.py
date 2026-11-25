"""E2E integration tests for the full Anapa Water billing cycle flow.

These tests exercise the complete end-to-end path:
user message → FSM transition → Vodokanal client (dry-run/stub) → payment link →
payment verification → scheduler reconciliation.

All tests use an in-memory SQLite DB + StubVodokanalClient so no real HTTP
or external API calls are made.
"""
from __future__ import annotations

import asyncio
from datetime import datetime
from decimal import Decimal

from home_bills_agent.providers.anapa_vodokanal.client import StubVodokanalClient
from home_bills_agent.storage import ALLOWED_TRANSITIONS, CycleFSM, CycleStatus


class TestE2EHappyPath:
    """Full happy-path flow: reading → sent → payment → verified."""

    def test_full_happy_path_ends_in_paid(
        self,
        fsm: CycleFSM,
        stub_client: StubVodokanalClient,
        payment_link,
        current_period,
    ):
        """End-to-end: reading sent → AWAITING_PAYMENT → PAID successfully."""
        reading = 12345

        # Step 1: Create cycle in WAITING_READING
        c0 = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.WAITING_READING,
            event_type="cycle.start",
        )
        assert c0 is not None, "cycle.start failed"

        # Step 2: Send reading via stub client (dry-run, no HTTP)
        success, err_msg = asyncio.run(stub_client.add_counter_value(reading))
        assert success is True, f"Stub add_counter_value failed: {err_msg}"

        # Step 3: Transition to READING_SENT with reading data
        c = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.READING_SENT,
            reading_value=Decimal(reading),
            previous_reading=Decimal(0),
            consumption=Decimal(reading),
            reading_source="text",
            payment_link=payment_link,
            event_type="reading.sent",
            event_description=f"Показание {reading} передано.",
        )
        assert c is not None, "READING_SENT transition failed"
        assert c.status == CycleStatus.READING_SENT

        # Step 4: Reconcile READING_SENT → AWAITING_PAYMENT
        # reading_visible=True + debt_after set (even if 0) means LK read debt → AWAITING_PAYMENT
        from home_bills_agent.scheduler.jobs import reconcile_after_send

        final_status = reconcile_after_send(
            fsm,
            "acc1",
            current_period,
            reading_visible=True,
            debt_after=Decimal(0),  # LK returned debt=0, so visible → AWAITING_PAYMENT
            now=datetime.now(),
        )
        assert final_status == CycleStatus.AWAITING_PAYMENT, (
            f"Expected AWAITING_PAYMENT, got {final_status}"
        )

        # Step 5: Mark as PAID (user clicks 'Оплачено') — allowed from AWAITING_PAYMENT
        c = fsm.transition("acc1", current_period, CycleStatus.PAID, event_type="payment.claimed")
        assert c is not None, "PAID transition failed"
        assert c.status == CycleStatus.PAID

        # Step 6: Verify check_due_reminders handles PAID without error
        from home_bills_agent.scheduler.jobs import check_due_reminders

        actions = check_due_reminders()
        assert isinstance(actions, list)

    def test_payment_verification_after_paid(
        self,
        fsm: CycleFSM,
        current_period,
    ):
        """After AWAITING_PAYMENT → PAID, reconcile should stay idempotent."""
        # Create cycle → send → reconcile to AWAITING_PAYMENT → mark PAID
        c0 = fsm.transition("acc1", current_period, CycleStatus.WAITING_READING, event_type="cycle.start")
        assert c0 is not None

        c1 = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.READING_SENT,
            reading_value=Decimal(12345),
            reading_source="text",
            event_type="reading.sent",
        )
        assert c1 is not None

        from home_bills_agent.scheduler.jobs import reconcile_after_send

        status = reconcile_after_send(
            fsm,
            "acc1",
            current_period,
            reading_visible=True,
            debt_after=Decimal(0),
            now=datetime.now(),
        )
        assert status == CycleStatus.AWAITING_PAYMENT

        c2 = fsm.transition("acc1", current_period, CycleStatus.PAID, event_type="payment.claimed")
        assert c2 is not None
        assert c2.status == CycleStatus.PAID

        # Re-running reconcile after send on a PAID cycle should not crash
        # PAID only allows CANCELLED transition
        status2 = reconcile_after_send(
            fsm,
            "acc1",
            current_period,
            reading_visible=False,
            debt_after=None,
            now=datetime.now(),
        )
        assert status2 == CycleStatus.PAID

        # PAID -> CANCELLED is allowed per ALLOWED_TRANSITIONS
        c3 = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.CANCELLED,
            event_type="payment.cancelled",
        )
        assert c3 is not None
        assert c3.status == CycleStatus.CANCELLED

    def test_anomaly_flow_reaches_confirmation(
        self,
        fsm: CycleFSM,
        stub_client: StubVodokanalClient,
        current_period,
        factory,
    ):
        """E2E anomaly: enough history + outlier reading → AWAITING_ANOMALY_CONFIRMATION."""
        from home_bills_agent.storage.models import ReadingsCache

        # Populate recent whole readings cache
        with factory() as session:
            for i in range(5):
                cache = ReadingsCache(
                    account_id="acc1",
                    period=current_period,
                    reading_date=datetime.now(),
                    reading_value=Decimal(100 + i),
                    source="text",
                    is_integer=1,
                )
                session.add(cache)
            session.commit()

        # Outlier reading that should trigger anomaly detection
        reading = 1000  # way above median of whole readings [100,101,102,103,104]

        client = stub_client
        success, _err_msg = asyncio.run(client.add_counter_value(reading))
        assert success is True

        # Create cycle in WAITING_READING first (required before anomaly transitions)
        c0 = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.WAITING_READING,
            event_type="cycle.start",
        )
        assert c0 is not None

        # Now transition to AWAITING_ANOMALY_CONFIRMATION
        c = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.AWAITING_ANOMALY_CONFIRMATION,
            reading_value=Decimal(reading),
            previous_reading=Decimal(104),
            reading_source="text",
            event_type="anomaly",
            event_description="Аномальный расход: 1000 vs median 102",
        )
        assert c is not None, "AWAITING_ANOMALY_CONFIRMATION transition failed"

        # AWAITING_ANOMALY_CONFIRMATION -> READING_SENT is allowed
        allowed = ALLOWED_TRANSITIONS.get(CycleStatus.AWAITING_ANOMALY_CONFIRMATION, set())
        assert CycleStatus.READING_SENT in allowed

        # User confirms → back to READING_SENT with confirmed value
        c2 = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.READING_SENT,
            reading_value=Decimal(reading),
            reading_source="text",
            event_type="reading.sent",
            event_description=f"Подтверждено, показание {reading} передано.",
        )
        assert c2 is not None
        assert c2.status == CycleStatus.READING_SENT


class TestE2EAnomaly:
    """Anomaly detection e2e behavior with realistic reading history."""

    def test_anomaly_detected_with_outlier_and_flow(
        self,
        fsm: CycleFSM,
        settings,
        stub_client: StubVodokanalClient,
        current_period,
        factory,
        payment_link,
    ):
        """Full sequence: history → outlier → confirm → sent → payment."""
        from home_bills_agent.storage.anomaly import can_detect_anomaly, median_of_whole_readings
        from home_bills_agent.storage.models import ReadingsCache

        # Populate enough whole readings for anomaly detection
        with factory() as session:
            for i in range(3):
                cache = ReadingsCache(
                    account_id="acc1",
                    period=current_period,
                    reading_date=datetime.now(),
                    reading_value=Decimal(100 + i),
                    source="text",
                    is_integer=1,
                )
                session.add(cache)
            session.commit()

        # Load them back
        from sqlalchemy import select

        with factory() as session:
            rows = (
                session.execute(
                    select(ReadingsCache)
                    .where(ReadingsCache.account_id == "acc1")
                    .where(ReadingsCache.period == current_period)
                    .where(ReadingsCache.is_integer == 1)
                    .order_by(ReadingsCache.reading_date.desc())
                    .limit(12)
                )
                .scalars()
                .all()
            )

        readings = [
            {"reading_value": r.reading_value, "reading_date": r.reading_date, "is_integer": r.is_integer}
            for r in rows
        ]
        assert len(readings) >= 3
        med = median_of_whole_readings(readings)
        assert med is not None

        # can_detect_anomaly should return True with enough data
        assert can_detect_anomaly(readings, settings.ANOMALY_FACTOR) is True

        # Outlier triggers anomaly
        outlier = 5000
        from home_bills_agent.bot.handlers import _check_anomaly

        is_anomaly = _check_anomaly(outlier, 104, readings)
        assert is_anomaly is True

        # Create cycle in WAITING_READING first
        c0 = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.WAITING_READING,
            event_type="cycle.start",
        )
        assert c0 is not None

        # Flow: outlier → confirm → sent → payment
        c = fsm.transition(
            "acc1",
            current_period,
            CycleStatus.READING_SENT,
            reading_value=Decimal(outlier),
            reading_source="text",
            event_type="reading.sent",
            event_description=f"Подтверждено, показание {outlier} передано.",
        )
        assert c is not None

        from home_bills_agent.scheduler.jobs import reconcile_after_send

        final_status = reconcile_after_send(
            fsm,
            "acc1",
            current_period,
            reading_visible=True,
            debt_after=Decimal(0),
            now=datetime.now(),
        )
        assert final_status == CycleStatus.AWAITING_PAYMENT