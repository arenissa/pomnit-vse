"""Готовые варианты переноса срока и их вычисление в локальном времени пользователя."""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .timeutil import resolve_deadline

OPTION_LABELS: dict[str, str] = {
    "m15": "15 мин",
    "m30": "30 мин",
    "h1": "1 час",
    "h3": "3 часа",
    "h8": "8 часов",
    "eve": "сегодня вечером",
    "tmr9": "завтра 9:00",
    "tmr18": "завтра 18:00",
    "wk": "через неделю",
}

_OFFSETS = {"m15": 15, "m30": 30, "h1": 60, "h3": 180, "h8": 480, "wk": 7 * 24 * 60}
_CLOCK = {"eve": 19, "tmr9": 9, "tmr18": 18}


def option_deadline(key: str, now: datetime, tz: ZoneInfo) -> datetime | None:
    """Возвращает новый срок (UTC) для кнопки-варианта."""
    if key in _OFFSETS:
        return now + timedelta(minutes=_OFFSETS[key])
    if key not in _CLOCK:
        return None

    hour = _CLOCK[key]
    local_now = now.astimezone(tz)
    day = local_now.date() if key == "eve" else local_now.date() + timedelta(days=1)
    when = resolve_deadline(day.year, day.month, day.day, hour, 0, tz)
    if when <= now:  # "сегодня вечером" уже наступило — переносим на завтра
        when = resolve_deadline(
            (day + timedelta(days=1)).year, (day + timedelta(days=1)).month, (day + timedelta(days=1)).day, hour, 0, tz
        )
    return when
