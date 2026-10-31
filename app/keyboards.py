"""Inline-клавиатуры бота.

Схема callback_data:
    menu                        главное меню
    add                         начать добавление заметки
    grp:{group}                 переключение фильтра списка
    nav:{group}:{page}:{dir}    листание списка (prev|next)
    act:{id}:{verb}:{src}       действие над заметкой (done|post|edit|del|undo|back)
    edit:{id}:{part}:{src}      что именно менять (text|time)
    del:{id}:{src}              подтверждённое удаление
    pos:{id}:{key}:{src}        перенос срока
    quick:{key}:{ctx}           быстрый вариант времени при вводе текстом
    set:rb:{min}                интервал напоминания
    set:tz / set:tzc:{name}     часовой пояс
src: c — карточка в списке, r — отдельное сообщение.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from .models import Reminder
from .options import OPTION_LABELS
from .storage import GROUPS

POSTPONE_KEYS: tuple[str, ...] = ("m15", "m30", "h1", "h3", "eve", "tmr9", "tmr18", "wk")
QUICK_KEYS: tuple[str, ...] = ("h1", "eve", "tmr9", "tmr18")

TIMEZONES: tuple[tuple[str, str], ...] = (
    ("Europe/Moscow", "🇷🇺 Москва"),
    ("Europe/Kyiv", "🇺🇦 Киев"),
    ("Europe/Minsk", "🇧🇾 Минск"),
    ("Asia/Almaty", "🇰🇿 Алматы"),
    ("Asia/Tashkent", "🇺🇿 Ташкент"),
    ("Asia/Dubai", "🇦🇪 Дубай"),
    ("Europe/London", "🇬🇧 Лондон"),
    ("UTC", "🌍 UTC"),
)

REMIND_BEFORE_CHOICES: tuple[int, ...] = (0, 10, 15, 30, 60, 120)

GROUP_ICONS = {"open": "🗂", "today": "📅", "overdue": "⚠️", "done": "✅"}


def _button(text: str, callback_data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text=text, callback_data=callback_data)


def main_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("📝 Мои заметки", "grp:open"), _button("➕ Новая заметка", "add"))
    builder.row(_button("📅 Сегодня", "grp:today"), _button("⚠️ Просроченные", "grp:overdue"))
    builder.row(_button("✅ Выполненные", "grp:done"), _button("⚙️ Настройки", "set:menu"))
    return builder.as_markup()


def navigation(group: str, page: int, pages: int) -> list[InlineKeyboardButton]:
    """Строка листания: ◀ | счётчик | ▶ (неактивные границы заглушены)."""
    return [
        _button("◀️", f"nav:{group}:{page}:prev" if page > 1 else "#"),
        _button(f"{page} / {pages}", "#"),
        _button("▶️", f"nav:{group}:{page}:next" if page < pages else "#"),
    ]


def list_menu(group: str) -> list[InlineKeyboardButton]:
    return [
        _button(
            f"{GROUP_ICONS[key]} {title.capitalize()}" + (" ▾" if key == group else ""),
            f"grp:{key}",
        )
        for key, (title, _, _) in GROUPS.items()
    ]


def footer() -> list[InlineKeyboardButton]:
    return [_button("➕ Новая заметка", "add"), _button("🏠 Меню", "menu")]


def card_actions(reminder_id: int, source: str = "c") -> list[list[InlineKeyboardButton]]:
    return [
        [
            _button("✅ Выполнено", f"act:{reminder_id}:done:{source}"),
            _button("⏰ Отложить", f"act:{reminder_id}:post:{source}"),
        ],
        [
            _button("✏️ Изменить", f"act:{reminder_id}:edit:{source}"),
            _button("🗑 Удалить", f"act:{reminder_id}:del:{source}"),
        ],
    ]


def list_card(group: str, page: int, pages: int, reminder: Reminder | None) -> InlineKeyboardMarkup:
    """Клавиатура карточки в списке: листание + действия + переходы."""
    rows: list[list[InlineKeyboardButton]] = [navigation(group, page, pages)]
    if reminder is not None:
        if reminder.is_open:
            rows += card_actions(reminder.id, "c")
        else:
            rows.append(
                [
                    _button("↩️ Вернуть в работу", f"act:{reminder.id}:undo:c"),
                    _button("🗑 Удалить", f"act:{reminder.id}:del:c"),
                ]
            )
    rows.append(list_menu(group))
    rows.append(footer())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def standalone(reminder_id: int | None, is_open: bool, source: str = "r") -> InlineKeyboardMarkup:
    """Клавиатура отдельного сообщения (напоминание, подтверждение создания)."""
    rows: list[list[InlineKeyboardButton]] = []
    if reminder_id is not None and is_open:
        rows += card_actions(reminder_id, source)
    rows.append(footer())
    return InlineKeyboardMarkup(inline_keyboard=rows)


def edit_menu(reminder_id: int, source: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("✏️ Новый текст", f"edit:{reminder_id}:text:{source}"),
        _button("🗓 Новый срок", f"edit:{reminder_id}:time:{source}"),
    )
    builder.row(_button("✖️ Назад", f"act:{reminder_id}:back:{source}"))
    return builder.as_markup()


def postpone_menu(reminder_id: int, source: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button(OPTION_LABELS["m15"], f"pos:{reminder_id}:m15:{source}"),
        _button(OPTION_LABELS["m30"], f"pos:{reminder_id}:m30:{source}"),
        _button(OPTION_LABELS["h1"], f"pos:{reminder_id}:h1:{source}"),
        _button(OPTION_LABELS["h3"], f"pos:{reminder_id}:h3:{source}"),
    )
    builder.row(
        _button(OPTION_LABELS["eve"], f"pos:{reminder_id}:eve:{source}"),
        _button(OPTION_LABELS["tmr9"], f"pos:{reminder_id}:tmr9:{source}"),
    )
    builder.row(
        _button(OPTION_LABELS["tmr18"], f"pos:{reminder_id}:tmr18:{source}"),
        _button(OPTION_LABELS["wk"], f"pos:{reminder_id}:wk:{source}"),
    )
    builder.row(
        _button("🗓 Свой срок", f"pos:{reminder_id}:custom:{source}"),
        _button("✖️ Назад", f"act:{reminder_id}:back:{source}"),
    )
    return builder.as_markup()


def quick_choices(context: str) -> InlineKeyboardMarkup:
    """Быстрые варианты времени, когда пользователь вводит срок текстом."""
    rows = [
        [_button(OPTION_LABELS[key], f"quick:{key}:{context}") for key in QUICK_KEYS[:2]],
        [_button(OPTION_LABELS[key], f"quick:{key}:{context}") for key in QUICK_KEYS[2:]],
        [_button("✖️ Отмена", "menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def delete_confirm(reminder_id: int, source: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(
        _button("🗑 Да, удалить", f"del:{reminder_id}:{source}"),
        _button("✖️ Отмена", f"act:{reminder_id}:back:{source}"),
    )
    return builder.as_markup()


def done_note(reminder_id: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button("↩️ Вернуть в работу", f"act:{reminder_id}:undo:c"), _button("🏠 Меню", "menu"))
    return builder.as_markup()


def settings_menu(timezone_name: str, remind_before: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.row(_button(f"🔔 Напоминать за {remind_before} мин" if remind_before else "🔕 Без напоминания", "#"))
    row = [_button(str(value) if value else "выкл", f"set:rb:{value}") for value in REMIND_BEFORE_CHOICES]
    builder.row(*row)
    builder.row(_button(f"🌍 {timezone_name}", "set:tz"))
    builder.row(_button("🏠 Меню", "menu"), _button("📝 Заметки", "grp:open"))
    return builder.as_markup()


def timezone_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for code, label in TIMEZONES:
        builder.button(text=label, callback_data=f"set:tzc:{code}")
    builder.adjust(2)
    builder.row(_button("✍️ Указать свой", "set:tzcustom"), _button("✖️ Отмена", "menu"))
    return builder.as_markup()
