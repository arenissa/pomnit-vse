"""Добавление заметок: команда /add и распознавание времени из обычного сообщения."""

from __future__ import annotations

from datetime import datetime

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import views
from ..config import Config
from ..keyboards import quick_choices, standalone
from ..models import Reminder, UserSettings
from ..options import option_deadline
from ..states import AddFlow, EditFlow
from ..storage import Database
from ..timeparse import parse_when
from ..timeutil import format_local, from_db, to_db, utcnow
from .helpers import load_user, user_tz

router = Router(name="notes")

MAX_NOTE_LENGTH = 500

ASK_TIME = (
    "⏰ <b>До какого времени?</b>\n\n"
    "Напиши одним сообщением в свободной форме:\n"
    "• сегодня 18:30\n"
    "• завтра утром\n"
    "• 05.11 в 12:00\n"
    "• через 2 часа\n"
    "• в пятницу 17:00"
)

ADD_HINT = (
    "➕ <b>Новая заметка</b>\n\n"
    "Пришли одним сообщением текст и время, например:\n"
    "<code>Оплатить интернет завтра в 10:00</code>\n"
    "<code>Сдать отчёт 05.11 18:00</code>\n"
    "<code>Позвонить маме через 2 часа</code>\n\n"
    "<i>Если время не укажешь — спрошу отдельно.</i>"
)


def parse_deadline(text: str, user: UserSettings, config: Config, now: datetime | None = None):
    """Ищет дату/время в строке с учётом часового пояса пользователя."""
    now = now or utcnow()
    return parse_when(
        text,
        now=now,
        tz=user_tz(user),
        default_hour=config.default_time.hour,
        default_minute=config.default_time.minute,
    )


async def save_reminder(
    message: Message,
    db: Database,
    config: Config,
    user: UserSettings,
    text: str,
    deadline: datetime,
) -> Reminder:
    """Создаёт заметку и показывает подтверждение с кнопками."""
    now = utcnow()
    body = (text or "").strip()[:MAX_NOTE_LENGTH]
    reminder = await db.create(user.user_id, body, deadline, user.remind_before, now=now)
    await message.answer(
        views.render_created(reminder, tz=user_tz(user), now=now, remind_before=user.remind_before),
        reply_markup=standalone(reminder.id, reminder.is_open, "r"),
    )
    return reminder


async def create_from_text(
    message: Message,
    db: Database,
    config: Config,
    state: FSMContext,
    user: UserSettings,
    raw_text: str,
) -> None:
    """Главный вход: «заметка + время» одним сообщением."""
    raw_text = raw_text.strip()
    parsed = parse_deadline(raw_text, user, config)

    if parsed and parsed.note.strip():
        await state.clear()
        await save_reminder(message, db, config, user, parsed.note, parsed.when)
        return

    if parsed:  # распознано только время — спрашиваем текст задачи
        await state.update_data(deadline=to_db(parsed.when))
        await state.set_state(AddFlow.note)
        await message.answer(
            f"⏳ Принято: <b>{format_local(parsed.when, user_tz(user))}</b>.\n\n"
            "Что нужно сделать к этому сроку? Пришли текст задачи."
        )
        return

    await state.update_data(note=raw_text[:MAX_NOTE_LENGTH])
    await state.set_state(AddFlow.time)
    await message.answer(f"Заметка: <b>{raw_text[:MAX_NOTE_LENGTH]}</b>\n\n{ASK_TIME}", reply_markup=quick_choices("add"))


@router.message(Command("add"))
async def cmd_add(message: Message, db, config, state: FSMContext, command: CommandObject) -> None:
    user = await load_user(db, config, message)
    args = (command.args or "").strip()
    if args:
        await create_from_text(message, db, config, state, user, args)
        return
    await state.clear()
    await message.answer(ADD_HINT, reply_markup=standalone(None, False))


@router.callback_query(F.data == "add")
async def cb_add(callback: CallbackQuery, db, config, state: FSMContext) -> None:
    await load_user(db, config, callback)
    await state.clear()
    await callback.message.answer(ADD_HINT, reply_markup=standalone(None, False))
    await callback.answer()


@router.message(AddFlow.note, F.text)
async def add_note_only(message: Message, db, config, state: FSMContext) -> None:
    user = await load_user(db, config, message)
    data = await state.get_data()
    deadline_raw = data.get("deadline")
    if not deadline_raw:
        await state.clear()
        await create_from_text(message, db, config, state, user, message.text or "")
        return
    await state.clear()
    await save_reminder(message, db, config, user, message.text or "", from_db(deadline_raw))


@router.message(AddFlow.time, F.text)
async def add_time_only(message: Message, db, config, state: FSMContext) -> None:
    user = await load_user(db, config, message)
    data = await state.get_data()
    note = data.get("note") or message.text or ""
    parsed = parse_deadline(message.text or "", user, config)
    if parsed is None:
        await message.answer(f"Не разобрал время 🤔\n\n{ASK_TIME}", reply_markup=quick_choices("add"))
        return
    await state.clear()
    await save_reminder(message, db, config, user, note, parsed.when)


@router.message(EditFlow.note, F.text)
async def edit_note_text(message: Message, db, config, state: FSMContext) -> None:
    """Замена текста заметки; срок можно дописать прямо в новом тексте."""
    user = await load_user(db, config, message)
    data = await state.get_data()
    reminder = await db.get(int(data.get("reminder_id", 0)), user.user_id)
    if reminder is None:
        await state.clear()
        await message.answer("Заметка уже удалена 🤷")
        return

    raw = (message.text or "").strip()
    parsed = parse_deadline(raw, user, config)
    if parsed and parsed.note.strip():
        body, deadline = parsed.note[:MAX_NOTE_LENGTH], parsed.when
    else:
        body, deadline = raw[:MAX_NOTE_LENGTH], reminder.deadline

    await state.clear()
    now = utcnow()
    updated = await db.reschedule(reminder.id, user.user_id, deadline, user.remind_before, text=body, now=now)
    if updated is None:
        await message.answer("Заметка уже удалена 🤷")
        return
    await message.answer(
        views.render_created(
            updated, tz=user_tz(user), now=now, remind_before=user.remind_before, header="✏️ <b>Заметка обновлена</b>"
        ),
        reply_markup=standalone(updated.id, updated.is_open, "r"),
    )


@router.callback_query(lambda callback: bool(callback.data) and callback.data.startswith("quick:"))
async def cb_quick(callback: CallbackQuery, db, config, state: FSMContext) -> None:
    _, key, context = (callback.data or "").split(":", 2)
    user = await load_user(db, config, callback)
    now = utcnow()
    deadline = option_deadline(key, now, user_tz(user))
    if deadline is None:
        await callback.answer("Такого варианта нет", show_alert=True)
        return

    data = await state.get_data()
    note = (data.get("note") or "").strip()
    if not note:
        await state.update_data(deadline=to_db(deadline))
        await state.set_state(AddFlow.note)
        await callback.message.edit_text(
            f"⏳ Принято: <b>{format_local(deadline, user_tz(user))}</b>.\n\nЧто нужно сделать к этому сроку?"
        )
    else:
        await state.clear()
        await save_reminder(callback.message, db, config, user, note, deadline)
    await callback.answer()
