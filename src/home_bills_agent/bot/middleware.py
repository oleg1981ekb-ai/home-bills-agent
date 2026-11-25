"""Telegram middleware for user whitelist checking."""
from __future__ import annotations

from typing import Any

from aiogram.dispatcher.middlewares import BaseMiddleware
from aiogram.types import CallbackQuery, Message

from home_bills_agent.config import settings


class WhitelistMiddleware(BaseMiddleware):
    """Middleware that checks TELEGRAM_USER_ID / whitelist before any handler."""

    def __init__(self) -> None:
        super().__init__()

    async def __call__(
        self,
        handler,
        event: Message | CallbackQuery,
        data: dict[str, Any],
    ) -> Any:
        user_id = str(getattr(event.from_user, "id", ""))
        if settings.is_user_allowed(user_id):
            return await handler(event, data)
        # Silent reject — user not in whitelist
        return None