"""/start, /help, /cancel, главное меню и распознавание заметки из обычного сообщения."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import views
from ..keyboards import main_menu
from ..states import NoState, PlainText
from .helpers import load_user
from .notes import create_from_text

router = Router(name="common")


@router.message(CommandStart())
async def cmd_start(message: Message, db, config) -> None:
    user = await load_user(db, config, message)
    await message.answer(views.welcome_text(user.remind_before), reply_markup=main_menu())


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(views.HELP)


@router.message(Command("cancel"), StateFilter("*"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Хорошо, отменил. Возвращайся, когда нужно ⏰", reply_markup=main_menu())


@router.callback_query(F.data == "menu")
async def cb_menu(callback, state: FSMContext, db, config) -> None:
    await state.clear()
    user = await load_user(db, config, callback)
    await callback.message.edit_text(views.welcome_text(user.remind_before), reply_markup=main_menu())
    await callback.answer()


@router.callback_query(F.data == "#")
async def cb_stub(callback: CallbackQuery) -> None:
    """Заглушки-счётчики («1 / 5») не должны «крутиться» на кнопке."""
    await callback.answer()


@router.message(NoState(), PlainText())
async def note_from_text(message: Message, db, config, state: FSMContext) -> None:
    """Обычное сообщение: пробуем найти время и сразу сохранить заметку."""
    user = await load_user(db, config, message)
    await create_from_text(message, db, config, state, user, message.text or "")


@router.message()
async def fallback(message: Message) -> None:
    """Всё, что не обработали выше: неизвестная команда, стикер, фото."""
    if message.text and message.text.startswith("/"):
        await message.answer("Не знаю такую команду 🤔 Список команд — /help")
        return
    await message.answer(
        "Я понимаю только текст 📝\n"
        "Пришли заметку со временем, например: <code>Купить билет завтра в 18:00</code>"
    )
