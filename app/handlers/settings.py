"""Настройки пользователя: за сколько минут напоминать и часовой пояс."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from ..keyboards import settings_menu, timezone_menu
from ..states import DataPrefix, SettingsFlow
from ..timeutil import format_local, get_tz, utcnow
from .helpers import load_user, safe_edit

router = Router(name="settings")


def settings_text(user, config, now) -> str:
    interval = f"за <b>{user.remind_before} мин</b>" if user.remind_before else "<b>не напоминать</b> заранее"
    repeats = (
        f"🔁 повтор напоминаний: каждые {config.repeat_after} мин, не больше {config.max_repeats}\n"
        if config.repeat_after
        else "🔁 повторных напоминаний нет\n"
    )
    return (
        "⚙️ <b>Настройки</b>\n"
        "━━━━━━━━━━━━━━━━━━\n"
        f"🔔 Напоминание: {interval}\n"
        f"🌍 Пояс: <code>{user.timezone}</code> · сейчас {format_local(now, get_tz(user.timezone))}\n"
        f"{repeats}"
        "━━━━━━━━━━━━━━━━━━\n"
        "<i>Настройки применяются и к ещё не напомненным заметкам.</i>"
    )


@router.message(Command("settings", "настройки"))
async def cmd_settings(message: Message, db, config) -> None:
    user = await load_user(db, config, message)
    await message.answer(
        settings_text(user, config, utcnow()),
        reply_markup=settings_menu(user.timezone, user.remind_before),
    )


@router.callback_query(DataPrefix("set:"))
async def cb_settings(callback: CallbackQuery, db, config, state: FSMContext) -> None:
    parts = (callback.data or "").split(":")
    action = parts[1] if len(parts) > 1 else "menu"
    user = await load_user(db, config, callback)
    now = utcnow()

    if action == "menu":
        await state.clear()
        await safe_edit(callback.message, settings_text(user, config, now), settings_menu(user.timezone, user.remind_before))
    elif action == "rb":
        minutes = max(0, int(parts[2]))
        await db.set_remind_before(user.user_id, minutes)
        await db.refresh_remind_times(user.user_id, minutes, now)
        updated = await db.get_user(user.user_id)
        await safe_edit(
            callback.message,
            settings_text(updated, config, now),
            settings_menu(updated.timezone, updated.remind_before),
        )
        await callback.answer(f"Буду напоминать за {minutes} мин" if minutes else "Напоминание заранее выключено")
        return
    elif action == "tz":
        await safe_edit(callback.message, "🌍 <b>Выбери часовой пояс</b>", timezone_menu())
    elif action == "tzc":
        zone = parts[2]
        await db.set_timezone(user.user_id, zone)
        updated = await db.get_user(user.user_id)
        await safe_edit(
            callback.message,
            settings_text(updated, config, utcnow()),
            settings_menu(updated.timezone, updated.remind_before),
        )
        await callback.answer(f"Пояс: {zone}")
        return
    elif action == "tzcustom":
        await state.set_state(SettingsFlow.timezone)
        await safe_edit(
            callback.message,
            "✍️ Напиши часовой пояс в формате IANA, например <code>Asia/Yekaterinburg</code> или <code>Europe/Berlin</code>.",
        )
    else:
        await callback.answer("Такой настройки нет", show_alert=True)
        return

    await callback.answer()


@router.message(SettingsFlow.timezone, F.text)
async def set_timezone_text(message: Message, db, config, state: FSMContext) -> None:
    raw = (message.text or "").strip()
    zone = get_tz(raw)
    if zone.key != raw and zone.key == "UTC":
        await message.answer(
            f"Не нашёл пояс <code>{raw}</code> 🤔 Попробуй <code>Europe/Moscow</code> или выбери из списка — /settings"
        )
        return
    user = await load_user(db, config, message)
    await db.set_timezone(user.user_id, raw)
    await state.clear()
    updated = await db.get_user(user.user_id)
    await message.answer(
        settings_text(updated, config, utcnow()),
        reply_markup=settings_menu(updated.timezone, updated.remind_before),
    )
