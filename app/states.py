"""Состояния FSM и фильтры."""

from __future__ import annotations

from aiogram.filters import BaseFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message


class AddFlow(StatesGroup):
    note = State()
    time = State()


class EditFlow(StatesGroup):
    note = State()
    time = State()


class PostponeFlow(StatesGroup):
    time = State()


class SettingsFlow(StatesGroup):
    timezone = State()


class NoState(BaseFilter):
    """True, только если у пользователя нет активного FSM-состояния."""

    async def __call__(self, event: Message | CallbackQuery, state: FSMContext) -> bool:
        return await state.get_state() is None


class PlainText(BaseFilter):
    """Обычное текстовое сообщение (не команда)."""

    async def __call__(self, message: Message) -> bool:
        return bool(message.text) and not message.text.startswith("/") and message.text.strip() != ""


class DataPrefix(BaseFilter):
    """Колбэк начинается с одного из префиксов."""

    def __init__(self, *prefixes: str) -> None:
        self.prefixes = prefixes

    async def __call__(self, callback: CallbackQuery) -> bool:
        return bool(callback.data) and callback.data.startswith(self.prefixes)
