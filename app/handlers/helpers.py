"""Общие вспомогательные функции для хендлеров."""

from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from ..config import Config
from ..models import UserSettings
from ..storage import Database
from ..timeutil import get_tz, local_day_bounds

logger = logging.getLogger(__name__)


async def load_user(db: Database, config: Config, event: Message | CallbackQuery) -> UserSettings:
    """Гарантирует, что пользователь и его чат есть в базе, и возвращает настройки."""
    user = event.from_user
    if user is None:  # сообщение от анонимного админа/канала
        raise ValueError("Не удалось определить пользователя")
    if isinstance(event, Message):
        chat_id = event.chat.id
    elif event.message is not None:
        chat_id = event.message.chat.id
    else:
        chat_id = user.id
    return await db.ensure_user(user.id, chat_id, config.timezone, config.remind_before)


def user_tz(user: UserSettings) -> ZoneInfo:
    return get_tz(user.timezone)


def day_bounds(user: UserSettings, now: datetime) -> tuple[datetime, datetime]:
    local_now = now.astimezone(user_tz(user))
    return local_day_bounds(local_now.date(), user_tz(user))


async def safe_edit(message: Message, text: str, reply_markup: InlineKeyboardMarkup | None = None) -> None:
    """Редактирует сообщение, игнорируя «message is not modified» и сетевые ошибки."""
    try:
        await message.edit_text(text, reply_markup=reply_markup)
    except TelegramAPIError as exc:
        if "not modified" in str(exc):
            return
        logger.warning("Не удалось отредактировать сообщение %s: %s", message.message_id, exc)
