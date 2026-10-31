"""Регистрация всех роутеров. Порядок важен: fallback-обработчик текста — последний."""

from __future__ import annotations

from aiogram import Dispatcher, Router


def setup_routers(dispatcher: Dispatcher) -> None:
    for router in collect():
        dispatcher.include_router(router)


def collect() -> list[Router]:
    from . import browse, common, notes, postpone, settings

    # common подключается последним: у него fallback на любой обычный текст.
    return [notes.router, postpone.router, browse.router, settings.router, common.router]
