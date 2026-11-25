"""Telegram bot handlers for Anapa Water Agent v1.1.

Text input, commands, photo recognition, anomaly confirmation, payment button.
Uses FSM + SQLite as source of truth.
"""
from __future__ import annotations

import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message
from sqlalchemy import select

from home_bills_agent.assistant.vision import VisionResult, is_confident, recognize_reading
from home_bills_agent.config import settings
from home_bills_agent.payment.links import build_payment_link
from home_bills_agent.providers.anapa_vodokanal.client import StubVodokanalClient
from home_bills_agent.storage import CycleFSM, CycleStatus, init_db
from home_bills_agent.storage.anomaly import can_detect_anomaly, median_of_whole_readings
from home_bills_agent.storage.models import ReadingsCache

router = Router()
logger = logging.getLogger(__name__)

SESSION_FACTORY = init_db()


def _get_fsm() -> CycleFSM:
    return CycleFSM(SESSION_FACTORY, dry_run=settings.DRY_RUN)


def _current_period() -> str:
    return datetime.now().strftime("%Y-%m")


async def _get_last_reading() -> int:
    """Get last whole reading from LK client (dry-run/stub aware) or fallback."""
    client = StubVodokanalClient(dry_run=settings.DRY_RUN)
    whole, _prev, _debt = await client.get_counter_readings()
    if whole is not None:
        return int(whole)
    fsm = _get_fsm()
    cycle = fsm.get_active_cycle(settings.ACCOUNT_ID, _current_period())
    if cycle is not None and cycle.previous_reading is not None:
        return int(cycle.previous_reading)
    return 0


def _load_recent_readings(account_id: str, period: str, limit: int = 12) -> list[dict[str, Any]]:
    """Load recent whole readings from cache for anomaly detection."""
    with SESSION_FACTORY() as session:
        rows = (
            session.execute(
                select(ReadingsCache)
                .where(ReadingsCache.account_id == account_id)
                .where(ReadingsCache.period == period)
                .where(ReadingsCache.is_integer == 1)
                .order_by(ReadingsCache.reading_date.desc())
                .limit(limit)
            )
            .scalars()
            .all()
        )
        return [
            {
                "reading_value": r.reading_value,
                "reading_date": r.reading_date,
                "is_integer": r.is_integer,
            }
            for r in rows
        ]


def _cache_reading(account_id: str, period: str, value: int, source: str) -> None:
    """Save accepted reading to cache (dry-run aware)."""
    with SESSION_FACTORY() as session:
        cache = ReadingsCache(
            account_id=account_id,
            period=period,
            reading_date=datetime.now(),
            reading_value=Decimal(value),
            source=source,
            is_integer=1,
        )
        session.add(cache)
        if not settings.DRY_RUN:
            session.commit()
        session.rollback()


def _validate_reading(value: str) -> tuple[int | None, str | None]:
    """Validate text input as integer reading. Returns (value, error)."""
    try:
        if "." in value or "," in value:
            return None, "Дробное показание отклонено. Счётчик принимает только целые."
        val = int(value.strip())
        if val < 0:
            return None, "Показание не может быть отрицательным."
        return val, None
    except (ValueError, InvalidOperation):
        return None, "Не удалось распознать число. Отправь целое число, например: 100"


def _check_window(period: str, day: int) -> tuple[bool, str]:
    """Check if today's day is within window (WINDOW_START..WINDOW_END)."""
    if not (settings.WINDOW_START <= day <= settings.WINDOW_END):
        return False, f"Приём закрыт. Окно передачи: {settings.WINDOW_START}–{settings.WINDOW_END} число."
    return True, ""


def _check_once_per_day(fsm: CycleFSM) -> bool:
    cycle = fsm.get_active_cycle(settings.ACCOUNT_ID, _current_period())
    return cycle is not None and cycle.status in (
        CycleStatus.READING_SENT,
        CycleStatus.AWAITING_PAYMENT,
        CycleStatus.PAID,
        CycleStatus.ACCRUAL_PENDING,
    )


async def _reply_with_menu(message: Message) -> None:
    await message.answer(
        "👋 Привет! Я бот Анапа Водоканал.\n\n"
        "Отправь целое показание счётчика, например: 100\n\n"
        "Команды: /start, /status, /help"
    )


@router.message(F.text == "/start")
async def cmd_start(message: Message) -> None:
    await _reply_with_menu(message)


@router.message(F.text == "/help")
async def cmd_help(message: Message) -> None:
    await message.answer(
        "📋 Доступные команды:\n"
        "/start — главное меню\n"
        "/status — текущий цикл\n"
        "/help — помощь\n\n"
        "Просто отправь целое число — это показание счётчика."
    )


@router.message(F.text == "/status")
async def cmd_status(message: Message) -> None:
    fsm = _get_fsm()
    cycle = fsm.get_active_cycle(settings.ACCOUNT_ID, _current_period())
    if cycle is None:
        await message.answer("📊 Цикл не начат. Отправь показание.")
        return
    status_emoji = {
        CycleStatus.WAITING_READING: "⏳",
        CycleStatus.READING_SENT: "✅",
        CycleStatus.AWAITING_ANOMALY_CONFIRMATION: "⚠️",
        CycleStatus.AWAITING_PAYMENT: "💳",
        CycleStatus.PAID: "✅",
        CycleStatus.MANUAL_REVIEW: "🔧",
        CycleStatus.CANCELLED: "❌",
    }.get(cycle.status, "❓")
    await message.answer(f"{status_emoji} Статус: {cycle.status}")


def _check_anomaly(
    value: int, prev_reading: int, recent_readings: list[dict[str, Any]]
) -> bool:
    """Check if new reading is anomalous using median of whole readings."""
    med = median_of_whole_readings(recent_readings)
    if med is not None and med > 0:
        # Simple heuristic: if value >> median * factor, flag as anomaly
        # In full implementation, compare daily consumption
        delta = value - prev_reading
        if delta > med * settings.ANOMALY_FACTOR:
            return True
    elif med is None:
        # Not enough data — always confirm
        return True
    return False


async def _download_photo(message: Message) -> bytes | None:
    """Download largest photo from message as bytes."""
    try:
        photo = message.photo[-1]
        file = await message.bot.get_file(photo.file_id)
        bio = await file.download()
        return bio.read()
    except Exception as e:  # noqa: BLE001
        logger.warning("Failed to download photo: %s", e)
        return None


def _payment_keyboard(payment_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить", url=payment_link)],
            [InlineKeyboardButton(text="✅ Оплачено", callback_data="mark_paid")],
        ]
    )


def _cancel_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить оплату", callback_data="cancel_payment")]
        ]
    )


def _payment_text(cycle) -> str:
    link = cycle.payment_link or build_payment_link(settings.ACCOUNT_ID)
    lines = ["💳 Оплата"]
    if cycle.debt_after is not None:
        lines.append(f"Долг: {cycle.debt_after} руб.")
    lines.append("Ссылка на оплату:")
    lines.append(link)
    return "\n".join(lines)


async def _send_payment_prompt(message: Message, cycle) -> None:
    link = cycle.payment_link or build_payment_link(settings.ACCOUNT_ID)
    await message.answer(_payment_text(cycle), reply_markup=_payment_keyboard(link))


def _advance_to_awaiting_payment(fsm: CycleFSM):
    """Post-send reconciliation: READING_SENT -> AWAITING_PAYMENT."""
    return fsm.transition(
        settings.ACCOUNT_ID,
        _current_period(),
        CycleStatus.AWAITING_PAYMENT,
        event_type="accrual.done",
        event_description="Начисление прочитано, ссылка на оплату отправлена.",
    )


async def _handle_reading(message: Message, value: int) -> None:
    """Main reading intake flow."""
    day = datetime.now().day

    ok, err = _check_window(_current_period(), day)
    if not ok:
        await message.answer(f"🚫 {err}")
        return

    if _check_once_per_day(_get_fsm()):
        cycle = _get_fsm().get_active_cycle(settings.ACCOUNT_ID, _current_period())
        await message.answer(
            f"ℹ️ Показание уже передано сегодня: {cycle.reading_value if cycle else '?'}."
        )
        return

    # Get last reading from LK/client or fallback
    last_reading = await _get_last_reading()
    fsm = _get_fsm()

    if value < last_reading:
        await message.answer(f"❌ Показание меньше предыдущего ({last_reading}).")
        return

    if fsm.get_active_cycle(settings.ACCOUNT_ID, _current_period()) is None:
        fsm.transition(
            settings.ACCOUNT_ID,
            _current_period(),
            CycleStatus.WAITING_READING,
            event_type="cycle.start",
        )

    # Anomaly check: only when enough history (can_detect_anomaly) — else smooth happy path
    recent_readings = _load_recent_readings(settings.ACCOUNT_ID, _current_period())
    is_anomaly = can_detect_anomaly(recent_readings, settings.ANOMALY_FACTOR) and _check_anomaly(
        value, last_reading, recent_readings
    )

    if is_anomaly:
        c = fsm.transition(
            settings.ACCOUNT_ID,
            _current_period(),
            CycleStatus.AWAITING_ANOMALY_CONFIRMATION,
            reading_value=Decimal(value),
            previous_reading=Decimal(last_reading),
            reading_source="text",
            event_type="anomaly",
            event_description=f"Новое показание {value}, расход аномальный. Ждём подтверждения.",
        )
        if c:
            await message.answer(
                "⚠️ Расход аномальный. Подтвердите показание кнопкой ниже."
            )
            from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

            kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Подтвердить",
                            callback_data=f"confirm:{value}",
                        )
                    ]
                ]
            )
            await message.answer(
                f"Подтвердите показание {value}?",
                reply_markup=kb,
            )
            return
        else:
            await message.answer("❌ Не удалось начать цикл.")
            return

    # Normal flow: send reading via DRY_RUN stub
    client = StubVodokanalClient(dry_run=settings.DRY_RUN)
    success, err_msg = await client.add_counter_value(value)

    if not success:
        await message.answer(f"❌ Ошибка отправки: {err_msg}")
        fsm.transition(
            settings.ACCOUNT_ID,
            _current_period(),
            CycleStatus.MANUAL_REVIEW,
            event_type="send_failed",
            event_description=err_msg,
        )
        return

    _cache_reading(settings.ACCOUNT_ID, _current_period(), value, "text")

    # Transition to READING_SENT
    c = fsm.transition(
        settings.ACCOUNT_ID,
        _current_period(),
        CycleStatus.READING_SENT,
        reading_value=Decimal(value),
        previous_reading=Decimal(last_reading),
        consumption=Decimal(value - last_reading) if last_reading else None,
        reading_source="text",
        payment_link=build_payment_link(settings.ACCOUNT_ID),
        event_type="reading.sent",
        event_description=f"Показание {value} передано.",
    )
    if c:
        consumption = c.consumption
        consumption_str = f"{int(consumption)} м³" if consumption is not None else "—"
        await message.answer(
            f"✅ Показание {value} передано. Расход: {consumption_str}."
        )
        awaiting = _advance_to_awaiting_payment(fsm)
        if awaiting:
            await _send_payment_prompt(message, awaiting)
        else:
            await message.answer("✅ Показание передано. Ожидаем начисления.")
    else:
        await message.answer("❌ Не удалось обновить статус.")


async def _handle_photo(message: Message) -> None:
    """Photo intake flow: recognize value, ask for confirmation."""
    day = datetime.now().day

    ok, err = _check_window(_current_period(), day)
    if not ok:
        await message.answer(f"🚫 {err}")
        return

    if _check_once_per_day(_get_fsm()):
        cycle = _get_fsm().get_active_cycle(settings.ACCOUNT_ID, _current_period())
        await message.answer(
            f"ℹ️ Показание уже передано сегодня: {cycle.reading_value if cycle else '?'}."
        )
        return

    photo_bytes = await _download_photo(message)
    if photo_bytes is None:
        await message.answer("❌ Не удалось загрузить фото. Попробуйте ещё раз.")
        return

    result: VisionResult = await recognize_reading(photo_bytes)

    if result.value is None:
        await message.answer(
            "❌ Не удалось распознать показание на фото. "
            "Отправьте чёткое фото счётчика или введите число текстом."
        )
        return

    value = result.value
    last_reading = await _get_last_reading()
    fsm = _get_fsm()

    if value < last_reading:
        await message.answer(f"❌ Показание меньше предыдущего ({last_reading}).")
        return

    # Авто-принятие при высокой уверенности
    if is_confident(result):
        _cache_reading(settings.ACCOUNT_ID, _current_period(), value, "photo")
        c = fsm.transition(
            settings.ACCOUNT_ID,
            _current_period(),
            CycleStatus.READING_SENT,
            reading_value=Decimal(value),
            previous_reading=Decimal(last_reading),
            reading_source="photo",
            event_type="photo.recognized.confirmed",
            event_description=f"Фото распознано: {value}, уверенность {result.confidence:.2f}, принято автоматически.",
        )
        if c:
            consumption = c.consumption
            consumption_str = f"{int(consumption)} м³" if consumption is not None else "—"
            await message.answer(
                f"✅ Показание {value} распознано и принято. Расход: {consumption_str}."
            )
            awaiting = _advance_to_awaiting_payment(fsm)
            if awaiting:
                await _send_payment_prompt(message, awaiting)
            else:
                await message.answer("✅ Показание передано. Ожидаем начисления.")
        else:
            await message.answer("❌ Не удалось обновить статус.")
        return

    # Обычный путь: ожидание подтверждения аномалии
    last_reading = 0
    try:
        prev_cycle = fsm.get_active_cycle(settings.ACCOUNT_ID, _current_period())
        if prev_cycle and prev_cycle.previous_reading:
            last_reading = int(prev_cycle.previous_reading)
    except (AttributeError, ValueError):
        pass

    if value < last_reading:
        await message.answer(f"❌ Показание меньше предыдущего ({last_reading}).")
        return

    _cache_reading(settings.ACCOUNT_ID, _current_period(), value, "photo")

    c = fsm.transition(
        settings.ACCOUNT_ID,
        _current_period(),
        CycleStatus.AWAITING_ANOMALY_CONFIRMATION,
        reading_value=Decimal(value),
        previous_reading=Decimal(last_reading),
        reading_source="photo",
        event_type="photo.recognized",
        event_description=f"Фото распознано: {value}, уверенность {result.confidence:.2f}.",
    )
    if not c:
        await message.answer("❌ Не удалось обработать фото.")
        return

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить",
                    callback_data=f"confirm:{value}",
                )
            ]
        ]
    )
    await message.answer(
        f"📷 Распознано: {value} (уверенность {result.confidence:.2f}).\n"
        "Подтвердите показание кнопкой ниже.",
        reply_markup=kb,
    )


async def _handle_paid_button(callback: CallbackQuery) -> None:
    """User marks payment as done."""
    fsm = _get_fsm()
    c = fsm.transition(
        settings.ACCOUNT_ID,
        _current_period(),
        CycleStatus.PAID,
        event_type="payment.claimed",
        event_description="Пользователь отметил оплату.",
    )
    if c:
        await callback.message.edit_text("✅ Оплата отмечена. Будем проверять.")
    else:
        await callback.answer("❌ Не удалось отметить.")


@router.callback_query(F.data.startswith("confirm:"))
async def cb_confirm_anomaly(callback: CallbackQuery) -> None:
    """User confirms anomaly/photo reading via inline button."""
    value_str = callback.data.split(":", 1)[1] if callback.data else ""
    try:
        value = int(value_str)
    except ValueError:
        await callback.answer("❌ Неверное значение.")
        return

    fsm = _get_fsm()
    cycle = fsm.get_active_cycle(settings.ACCOUNT_ID, _current_period())
    source = cycle.reading_source if cycle else "text"

    c = fsm.transition(
        settings.ACCOUNT_ID,
        _current_period(),
        CycleStatus.READING_SENT,
        reading_value=Decimal(value),
        reading_source=source,
        event_type="reading.sent",
        event_description=f"Подтверждено ({source}), показание {value} передано.",
    )
    if c:
        await callback.message.edit_text(f"✅ Показание {value} подтверждено и передано.")
        awaiting = _advance_to_awaiting_payment(fsm)
        if awaiting:
            link = awaiting.payment_link or build_payment_link(settings.ACCOUNT_ID)
            await callback.message.answer(
                _payment_text(awaiting), reply_markup=_payment_keyboard(link)
            )
        else:
            await callback.answer("❌ Не удалось отправить ссылку на оплату.")
    else:
        await callback.answer("❌ Не удалось подтвердить.")


@router.callback_query(F.data == "mark_paid")
async def cb_mark_paid(callback: CallbackQuery) -> None:
    """User marks payment as done."""
    fsm = _get_fsm()
    c = fsm.transition(
        settings.ACCOUNT_ID,
        _current_period(),
        CycleStatus.PAID,
        event_type="payment.claimed",
        event_description="Пользователь отметил оплату.",
    )
    if c:
        await callback.message.edit_text(
            "✅ Оплата отмечена. Будем проверять.",
            reply_markup=_cancel_keyboard(),
        )
    else:
        await callback.answer("❌ Не удалось отметить.")


@router.callback_query(F.data == "cancel_payment")
async def cb_cancel_payment(callback: CallbackQuery) -> None:
    """User cancels the marked payment."""
    fsm = _get_fsm()
    c = fsm.transition(
        settings.ACCOUNT_ID,
        _current_period(),
        CycleStatus.CANCELLED,
        event_type="payment.cancelled",
        event_description="Пользователь отменил оплату.",
    )
    if c:
        await callback.message.edit_text(
            "❌ Оплата отменена. Цикл остановлен.",
            reply_markup=None,
        )
    else:
        await callback.answer("❌ Не удалось отменить.")


@router.message(F.photo)
async def msg_photo(message: Message) -> None:
    """Handle meter photo message."""
    await _handle_photo(message)


@router.message(F.text.regexp(r"^\d+$"))
async def msg_reading(message: Message) -> None:
    """Handle a plain integer reading message."""
    await _handle_reading(message, int(message.text.strip()))