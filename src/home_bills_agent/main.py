"""Entry point: Telegram bot + APScheduler for Anapa Water Agent v1.1.

Запуск:
    python3 -m home_bills_agent.main
или через docker-compose.
"""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from home_bills_agent.bot.handlers import router
from home_bills_agent.config import settings
from home_bills_agent.scheduler import jobs

logger = logging.getLogger(__name__)


async def _on_startup(bot: Bot) -> None:
    """При старте восстановить активный цикл и начать планировщик."""
    logger.info("Bot started. DRY_RUN=%s, ACCOUNT_ID=%s", settings.DRY_RUN, settings.ACCOUNT_ID)
    # Синхронная проверка на момент старта (без отправки сообщений).
    jobs.check_due_reminders()


async def main() -> None:
    if not settings.TELEGRAM_BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

    bot = Bot(token=settings.TELEGRAM_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    # Register bot for reminder dispatching.
    jobs.init(bot)

    scheduler = AsyncIOScheduler(timezone=settings.TZ)

    # Напоминания: утро 09:00, вечер 19:00 (с 22-го).
    scheduler.add_job(
        jobs.dispatch_due_reminders,
        "cron",
        hour=settings.REMINDER_TIME.split(":")[0],
        minute=settings.REMINDER_TIME.split(":")[1],
        id="morning_reminder",
        replace_existing=True,
    )
    scheduler.add_job(
        jobs.dispatch_due_reminders,
        "cron",
        hour=settings.EVENING_TIME.split(":")[0],
        minute=settings.EVENING_TIME.split(":")[1],
        id="evening_reminder",
        replace_existing=True,
    )

    # Повторные проверки начислений: каждые 6 часов.
    scheduler.add_job(
        jobs.dispatch_due_reminders,
        "interval",
        hours=6,
        id="accrual_recheck",
        replace_existing=True,
    )

    scheduler.start()
    try:
        await _on_startup(bot)
        await dp.start_polling(bot)
    finally:
        scheduler.shutdown()
        await bot.session.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    asyncio.run(main())