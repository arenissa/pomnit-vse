"""Просмотр заметок карточками с листанием и действиями над ними."""

from __future__ import annotations

from html import escape

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from .. import views
from ..keyboards import (
    delete_confirm,
    done_note,
    edit_menu,
    list_card,
    postpone_menu,
    standalone,
)
from ..models import Reminder, ReminderStatus, UserSettings
from ..states import EditFlow, PostponeFlow
from ..storage import GROUPS
from ..timeutil import format_local, utcnow
from .helpers import day_bounds, load_user, safe_edit, user_tz

router = Router(name="browse")

DEFAULT_GROUP = "open"


async def build_view(db, config, user: UserSettings, group: str, page: int) -> tuple[str, InlineKeyboardMarkup]:
    """Текст и клавиатура одной карточки (страницы) списка."""
    now = utcnow()
    day_start, day_end = day_bounds(user, now)
    total = await db.count(user.user_id, group, now=now, day_start=day_start, day_end=day_end)
    pages = max(total, 1)
    page = min(max(page, 1), pages)

    if total == 0:
        return views.render_empty(group), list_card(group, 1, 1, None)

    items = await db.list(
        user.user_id, group, now=now, day_start=day_start, day_end=day_end, limit=1, offset=page - 1
    )
    reminder = items[0]
    text = views.render_card(
        reminder,
        index=page,
        total=total,
        group=group,
        tz=user_tz(user),
        now=now,
        remind_before=user.remind_before,
    )
    return text, list_card(group, page, pages, reminder)


async def show_as_message(message: Message, db, config, group: str, page: int = 1) -> None:
    user = await load_user(db, config, message)
    text, markup = await build_view(db, config, user, group, page)
    await message.answer(text, reply_markup=markup)


async def show_in_place(callback: CallbackQuery, db, config, user: UserSettings, group: str, page: int) -> None:
    text, markup = await build_view(db, config, user, group, page)
    await safe_edit(callback.message, text, markup)


def parse_group(raw: str) -> str:
    return raw if raw in GROUPS else DEFAULT_GROUP


@router.message(Command("list", "notes", "заметки"))
async def cmd_list(message: Message, db, config) -> None:
    await show_as_message(message, db, config, DEFAULT_GROUP)


@router.message(Command("today", "сегодня"))
async def cmd_today(message: Message, db, config) -> None:
    await show_as_message(message, db, config, "today")


@router.message(Command("overdue", "просрочено"))
async def cmd_overdue(message: Message, db, config) -> None:
    await show_as_message(message, db, config, "overdue")


@router.message(Command("done", "готово"))
async def cmd_done(message: Message, db, config) -> None:
    await show_as_message(message, db, config, "done")


@router.message(Command("show"))
async def cmd_show(message: Message, db, config, command: CommandObject) -> None:
    if not command.args or not command.args.strip().isdigit():
        await message.answer("Использование: <code>/show 12</code>, где 12 — id заметки")
        return
    user = await load_user(db, config, message)
    reminder = await db.get(int(command.args.strip()), user.user_id)
    if reminder is None:
        await message.answer("Такой заметки нет 🤷")
        return
    now = utcnow()
    await message.answer(
        views.render_card(
            reminder,
            index=1,
            total=1,
            group="open" if reminder.is_open else "done",
            tz=user_tz(user),
            now=now,
            remind_before=user.remind_before,
        ),
        reply_markup=list_card("open" if reminder.is_open else "done", 1, 1, reminder),
    )


@router.callback_query(lambda callback: bool(callback.data) and callback.data.startswith("grp:"))
async def cb_group(callback: CallbackQuery, db, config) -> None:
    group = parse_group((callback.data or "").split(":")[1])
    user = await load_user(db, config, callback)
    await show_in_place(callback, db, config, user, group, 1)
    await callback.answer()


@router.callback_query(lambda callback: bool(callback.data) and callback.data.startswith("nav:"))
async def cb_nav(callback: CallbackQuery, db, config) -> None:
    _, group, page, direction = (callback.data or "").split(":")
    group = parse_group(group)
    page = int(page)
    step = -1 if direction == "prev" else 1
    user = await load_user(db, config, callback)
    await show_in_place(callback, db, config, user, group, page + step)
    await callback.answer()


@router.callback_query(lambda callback: bool(callback.data) and callback.data.startswith("act:"))
async def cb_action(callback: CallbackQuery, db, config, state: FSMContext) -> None:
    _, raw_id, verb, source = (callback.data or "").split(":")
    user = await load_user(db, config, callback)
    reminder = await db.get(int(raw_id), user.user_id)
    if reminder is None:
        await show_in_place(callback, db, config, user, DEFAULT_GROUP, 1)
        await callback.answer("Такой заметки уже нет", show_alert=True)
        return

    group = "done" if reminder.status == ReminderStatus.DONE else "open"
    now = utcnow()

    if verb == "done":
        await db.set_status(reminder.id, user.user_id, ReminderStatus.DONE, now=now)
        await callback.answer("Отметил как выполненное ✅")
    elif verb == "undo":
        await db.reschedule(reminder.id, user.user_id, reminder.deadline, user.remind_before, now=now)
        group = "open"  # заметка вернулась в активные
        await callback.answer("Вернул в работу 🕓")
    elif verb == "post":
        await safe_edit(
            callback.message,
            "⏰ <b>На что перенести срок?</b>\n\n"
            f"<b>{escape(reminder.text)}</b>\n"
            f"Сейчас: <i>{format_local(reminder.deadline, user_tz(user))}</i>",
            postpone_menu(reminder.id, source),
        )
        await callback.answer()
        return
    elif verb == "back":
        await show_in_place(callback, db, config, user, group, await _position(db, user, reminder, group, now))
        await callback.answer()
        return
    elif verb == "edit":
        await safe_edit(
            callback.message,
            f"✏️ <b>Что изменить в заметке?</b>\n\n<b>{escape(reminder.text)}</b>",
            edit_menu(reminder.id, source),
        )
        await callback.answer()
        return
    elif verb == "del":
        await safe_edit(
            callback.message,
            f"🗑 <b>Удалить заметку?</b>\n\n<b>{escape(reminder.text)}</b>\n\n"
            f"🗓 {format_local(reminder.deadline, user_tz(user))}",
            delete_confirm(reminder.id, source),
        )
        await callback.answer()
        return
    else:
        await callback.answer()
        return

    refreshed = await db.get(reminder.id, user.user_id)
    if refreshed is None:
        await show_in_place(callback, db, config, user, group, 1)
        return

    if source == "c":
        await show_in_place(
            callback, db, config, user, group, await _position(db, user, reminder, group, now)
        )
        return

    status_line = "✅ <b>Выполнено</b>" if verb == "done" else "🕓 <b>Вернуто в работу</b>"
    await safe_edit(
        callback.message,
        views.render_summary(refreshed, tz=user_tz(user), status_line=status_line),
        done_note(refreshed.id) if verb == "done" else standalone(refreshed.id, refreshed.is_open, source),
    )


async def _position(db, user: UserSettings, reminder: Reminder, group: str, now) -> int:
    day_start, day_end = day_bounds(user, now)
    return await db.position(user.user_id, reminder.id, group, now=now, day_start=day_start, day_end=day_end) or 1


@router.callback_query(lambda callback: bool(callback.data) and callback.data.startswith("del:"))
async def cb_delete(callback: CallbackQuery, db, config) -> None:
    _, raw_id, source = (callback.data or "").split(":")
    user = await load_user(db, config, callback)
    removed = await db.delete(int(raw_id), user.user_id)
    if not removed:
        await callback.answer("Заметка уже удалена", show_alert=True)
        return
    if source == "c":
        await show_in_place(callback, db, config, user, DEFAULT_GROUP, 1)
    else:
        await safe_edit(callback.message, "🗑 <b>Заметка удалена</b>", standalone(None, False))
    await callback.answer("Удалил 🗑")


@router.callback_query(lambda callback: bool(callback.data) and callback.data.startswith("edit:"))
async def cb_edit(callback: CallbackQuery, db, config, state: FSMContext) -> None:
    _, raw_id, part, source = (callback.data or "").split(":")
    user = await load_user(db, config, callback)
    reminder = await db.get(int(raw_id), user.user_id)
    if reminder is None:
        await callback.answer("Заметки нет", show_alert=True)
        return

    await state.update_data(reminder_id=reminder.id, source=source)
    if part == "text":
        await state.set_state(EditFlow.note)
        await safe_edit(callback.message, "✏️ Пришли новый текст заметки одним сообщением.")
    else:
        await state.set_state(PostponeFlow.time)
        await safe_edit(
            callback.message,
            "🗓 Пришли новое время в свободной форме:\n"
            "<code>завтра 15:00</code>, <code>05.11 вечером</code>, <code>через 3 часа</code>",
        )
    await callback.answer()
