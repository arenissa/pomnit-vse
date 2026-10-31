"""Генерация текстов сообщений (HTML) — карточки заметок, напоминания, подсказки."""

from __future__ import annotations

from datetime import datetime
from html import escape
from zoneinfo import ZoneInfo

from .models import Reminder
from .storage import GROUPS
from .timeutil import deadline_hint, format_local, human_delta

LINE = "━━━━━━━━━━━━━━━━━━"

STATUS_LABEL = {
    "active": "🕓 ждёт срока",
    "notified": "🔔 напоминание отправлено",
    "done": "✅ выполнено",
}


def group_title(group: str) -> str:
    return GROUPS[group][0]


def _header(reminder: Reminder, index: int, total: int, group: str) -> str:
    return f"<i>{escape(group_title(group))} · {index} из {total}</i>"


def render_card(
    reminder: Reminder,
    *,
    index: int,
    total: int,
    group: str,
    tz: ZoneInfo,
    now: datetime,
    remind_before: int,
) -> str:
    """Карточка одной заметки для постраничного просмотра."""
    lines = [
        _header(reminder, index, total, group),
        LINE,
        f"<b>{escape(reminder.text)}</b>",
        "",
        f"🗓 {format_local(reminder.deadline, tz)}",
    ]

    if reminder.status == "done":
        lines.append(f"🕖 выполнено {format_local(reminder.updated_at, tz)}")
    else:
        lines.append(f"⏳ {deadline_hint(reminder.deadline, now)}")
        if remind_before and reminder.remind_at:
            if reminder.remind_at > now:
                lines.append(f"🔔 напомню: {format_local(reminder.remind_at, tz)}")
            else:
                lines.append("🔔 напоминание уже отправлено")
        elif not remind_before:
            lines.append("🔕 напоминание заранее выключено")
        if reminder.notify_count:
            lines.append(f"📨 отправлено напоминаний: {reminder.notify_count}")

    extra = [STATUS_LABEL.get(str(reminder.status), str(reminder.status))]
    if reminder.is_overdue(now):
        extra[0] = "⚠️ срок просрочен"
    if reminder.postpone_count:
        extra.append(f"⏱ откладывал: {reminder.postpone_count}")
    lines += ["", " · ".join(extra), LINE]

    if reminder.is_open:
        lines.append("<i>✅ — сделал, ⏰ — перенести срок</i>")
    return "\n".join(lines)


def render_created(
    reminder: Reminder,
    *,
    tz: ZoneInfo,
    now: datetime,
    remind_before: int,
    header: str = "✅ <b>Заметка сохранена</b>",
) -> str:
    """Подтверждение после добавления/обновления заметки."""
    lines = [
        header,
        LINE,
        f"<b>{escape(reminder.text)}</b>",
        "",
        f"🗓 {format_local(reminder.deadline, tz)}",
        f"⏳ {deadline_hint(reminder.deadline, now)}",
    ]
    if remind_before and reminder.remind_at:
        lines.append(f"🔔 напоминание: {format_local(reminder.remind_at, tz)}")
    elif reminder.remind_at:
        lines.append("🔕 напоминание перед сроком выключено")
    lines += [LINE, "<i>Список: /list</i>"]
    return "\n".join(lines)


def render_rescheduled(reminder: Reminder, *, tz: ZoneInfo, now: datetime, remind_before: int) -> str:
    lines = [
        "⏰ <b>Срок перенесён</b>",
        LINE,
        f"<b>{escape(reminder.text)}</b>",
        "",
        f"🗓 новое время: {format_local(reminder.deadline, tz)}",
        f"⏳ {deadline_hint(reminder.deadline, now)}",
        f"🔁 отложено раз: {reminder.postpone_count}",
    ]
    if reminder.remind_at and reminder.deadline > reminder.remind_at:
        lines.append(f"🔔 напоминание: {format_local(reminder.remind_at, tz)}")
    lines.append(LINE)
    return "\n".join(lines)


def render_notification(reminder: Reminder, *, tz: ZoneInfo, now: datetime, kind: str, repeat_of: int = 0) -> str:
    """Текст push-напоминания от планировщика."""
    titles = {
        "pre": "🔔 <b>Напоминание</b>",
        "repeat": f"🔁 <b>Напоминаю ещё раз</b> ({reminder.notify_count} из {repeat_of})" if repeat_of else "🔁 <b>Напоминаю</b>",
        "deadline": "⚠️ <b>Срок истёк</b>",
    }
    header = [titles[kind], LINE, f"<b>{escape(reminder.text)}</b>", "", f"🗓 {format_local(reminder.deadline, tz)}"]
    if kind == "deadline":
        header.append(f"🕒 просрочено на {human_delta(now - reminder.deadline)}")
    else:
        header.append(f"⏳ осталось {deadline_hint(reminder.deadline, now).replace('через ', '')}")
    header += [LINE, "Отметь, что сделал, или отложи на удобный срок:"]
    return "\n".join(header)


def render_empty(group: str) -> str:
    hints = {
        "open": "Активных заметок нет. Отправь мне текст со временем — я поставлю напоминание. 🚀",
        "today": "На сегодня заметок нет 🎉",
        "overdue": "Просроченных заметок нет — всё под контролем 😎",
        "done": "Выполненных заметок пока нет. Начало положим кнопкой ➕ Новая заметка?",
    }
    return f"{LINE}\n🤷 <b>Пусто</b>\n\n{hints[group]}\n{LINE}"


def render_summary(reminder: Reminder, *, tz: ZoneInfo, status_line: str) -> str:
    return (
        f"{status_line}\n{LINE}\n<b>{escape(reminder.text)}</b>\n\n"
        f"🗓 {format_local(reminder.deadline, tz)}"
    )


WELCOME = f"""👋 <b>Привет! Я бот-напоминалка.</b>

Пришли заметку вместе со временем — например:
<code>Оплатить интернет завтра в 10:00</code>
<code>Статью дописать 05.11 18:30</code>
<code>Позвонить маме через 2 часа</code>

За {"{before}"} минут до срока я напомню о задаче и предложу кнопки
✅ <b>Выполнено</b> или ⏰ <b>Отложить</b> (перенести на удобный срок).

{LINE}
📝 <b>Что умею</b>
/add — новая заметка
/list — пролистать заметки карточками
/today — задачи на сегодня
/overdue — просроченные
/done — выполненные
/settings — за сколько минут напоминать
/help — подробности"""


def welcome_text(before: int) -> str:
    return WELCOME.replace("{before}", str(before))


HELP = f"""📖 <b>Как пользоваться</b>

{LINE}
<b>Добавить заметку</b>
Отправь текстом «что сделать + когда»:
<code>Купить билет 12.11 вечером</code>
Или командой /add и следуй подсказкам.
Если время не указано, бот спросит его отдельно.

<b>Распознаю</b>
• 18:30, 8.00, 9 утра, вечером / утром / днём / ночью
• сегодня, завтра, послезавтра, в пятницу
• 30.10, 30.10.2026, 5 ноября
• через 20 минут, через 1,5 часа, через 3 дня

<b>Напоминание</b>
Приходит за N минут до срока (по умолчанию 30, меняется в /settings).
Кнопки: ✅ Выполнено · ⏰ Отложить (15 мин, час, завтра, свой срок).

<b>Просмотр</b>
/list — карточки с листанием ◀️ ▶️, прямо в карточке кнопки
✅ Выполнено · ⏰ Отложить · ✏️ Изменить · 🗑 Удалить.

<b>Команды</b>
/add · /list · /today · /overdue · /done · /settings · /cancel · /help"""
