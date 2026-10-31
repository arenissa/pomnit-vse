"""Middleware ограничения доступа по списку Telegram ID."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = logging.getLogger(__name__)


class AccessMiddleware(BaseMiddleware):
    """Если ALLOWED_USER_IDS задан, пускает только перечисленных пользователей."""

    def __init__(self, allowed: frozenset[int]) -> None:
        self._allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if not self._allowed or (user is not None and user.id in self._allowed):
            return await handler(event, data)

        logger.info("Отказ в доступе пользователю %s", getattr(user, "id", "?"))
        if isinstance(event, Message):
            await event.answer("🔒 Бот приватный. Попроси владельца добавить твой ID в ALLOWED_USER_IDS.")
        elif isinstance(event, CallbackQuery):
            await event.answer("🔒 Нет доступа", show_alert=True)
        return None
