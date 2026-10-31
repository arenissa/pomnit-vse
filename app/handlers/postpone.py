"""Перенос срока: кнопки «Отложить» и ввод своего времени."""

from __future__ import annotations

from html import escape

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from .. import views
from ..keyboards import postpone_menu, standalone
from ..models import UserSettings
from ..options import option_deadline
from ..states import DataPrefix, PostponeFlow
from ..timeutil import format_local, utcnow
from .browse import show_in_place
from .helpers import day_bounds, load_user, safe_edit, user_tz
from .notes import parse_deadline

router = Router(name="postpone")


async def apply_new_deadline(
    callback: CallbackQuery,
    db,
    config,
    user: UserSettings,
    reminder_id: int,
    deadline,
    source: str,
) -> None:
    """Меняет срок и обновляет сообщение: карточку в списке или отдельное напоминание."""
    now = utcnow()
    updated = await db.reschedule(reminder_id, user.user_id, deadline, user.remind_before, postpone=True, now=now)
    if updated is None:
        await callback.answer("Заметка удалена", show_alert=True)
        return

    if source == "c":
        # Остаёмся в списке: перерисовываем карточку на её же странице.
        day_start, day_end = day_bounds(user, now)
        page = await db.position(user.user_id, updated.id, "open", now=now, day_start=day_start, day_end=day_end) or 1
        await show_in_place(callback, db, config, user, "open", page)
    else:
        text = views.render_rescheduled(updated, tz=user_tz(user), now=now, remind_before=user.remind_before)
        await safe_edit(callback.message, text, standalone(updated.id, updated.is_open, source))


@router.callback_query(DataPrefix("pos:"))
async def cb_postpone(callback: CallbackQuery, db, config, state: FSMContext) -> None:
    _, raw_id, key, source = (callback.data or "").split(":")
    user = await load_user(db, config, callback)
    reminder = await db.get(int(raw_id), user.user_id)
    if reminder is None:
        await callback.answer("Такой заметки нет", show_alert=True)
        return

    if key == "custom":
        await state.set_state(PostponeFlow.time)
        await state.update_data(reminder_id=reminder.id, source=source)
        await safe_edit(
            callback.message,
            "🗓 <b>Свой срок</b>\n\n"
            f"<b>{escape(reminder.text)}</b>\n"
            "Напиши новое время: <code>завтра в 15:00</code>, <code>05.11 18:30</code>, <code>через 2 часа</code>",
        )
        await callback.answer()
        return

    deadline = option_deadline(key, utcnow(), user_tz(user))
    if deadline is None:
        await callback.answer("Неизвестный вариант переноса", show_alert=True)
        return
    await apply_new_deadline(callback, db, config, user, reminder.id, deadline, source)
    await callback.answer(f"Перенёс на {format_local(deadline, user_tz(user))}")


@router.message(PostponeFlow.time, F.text)
async def postpone_by_text(message: Message, db, config, state: FSMContext) -> None:
    user = await load_user(db, config, message)
    data = await state.get_data()
    reminder = await db.get(int(data.get("reminder_id", 0)), user.user_id)
    if reminder is None:
        await state.clear()
        await message.answer("Заметка уже удалена 🤷")
        return

    parsed = parse_deadline(message.text or "", user, config)
    if parsed is None:
        await message.answer(
            "Не разобрал время 🤔 Попробуй <code>завтра 15:00</code> или нажми кнопку варианта срока.\n\n"
            f"<b>{escape(reminder.text)}</b>",
            reply_markup=postpone_menu(reminder.id, data.get("source", "r")),
        )
        return

    await state.clear()
    now = utcnow()
    updated = await db.reschedule(reminder.id, user.user_id, parsed.when, user.remind_before, postpone=True, now=now)
    if updated is None:
        await message.answer("Заметка уже удалена 🤷")
        return
    await message.answer(
        views.render_rescheduled(updated, tz=user_tz(user), now=now, remind_before=user.remind_before),
        reply_markup=standalone(updated.id, updated.is_open, "r"),
    )
