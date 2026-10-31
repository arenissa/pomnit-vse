"""Сборка Bot и Dispatcher."""

from __future__ import annotations

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent, Message

from .config import Config
from .handlers import setup_routers
from .middlewares import AccessMiddleware
from .storage import Database

logger = logging.getLogger(__name__)


def create_bot(config: Config) -> Bot:
    return Bot(
        token=config.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML, link_preview_is_disabled=True),
    )


def create_dispatcher(config: Config, db: Database) -> Dispatcher:
    dispatcher = Dispatcher(storage=MemoryStorage())
    # Значения доступны в хендлерах по имени аргумента.
    dispatcher["db"] = db
    dispatcher["config"] = config
    if config.allowed_users:
        access = AccessMiddleware(config.allowed_users)
        dispatcher.message.middleware(access)
        dispatcher.callback_query.middleware(access)
    setup_routers(dispatcher)

    @dispatcher.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logger.exception("Необработанная ошибка при обработке обновления", exc_info=event.exception)
        update = event.update
        target: Message | None = update.message or (update.callback_query.message if update.callback_query else None)
        if isinstance(target, Message):
            try:
                await target.answer("Что-то пошло не так 😔 Попробуй ещё раз или /cancel")
            except Exception:  # noqa: BLE001
                pass
        return True

    return dispatcher
