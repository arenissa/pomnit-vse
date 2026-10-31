"""Разбор даты и времени из строки на русском языке.

Поддержка:
    "завтра в 18:30", "30.10 14:00", "5 ноября", "в пятницу утром",
    "через 2 часа", "через полчаса", "вечером", "9 утра", "сегодня 12:00"
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MONTHS: dict[str, int] = {}
for _index, _forms in enumerate(
    [
        ("январь", "января", "янв"),
        ("февраль", "февраля", "февр"),
        ("март", "марта"),
        ("апрель", "апреля", "апр"),
        ("май", "мая"),
        ("июнь", "июня", "июн"),
        ("июль", "июля", "июл"),
        ("август", "августа", "авг"),
        ("сентябрь", "сентября", "сент"),
        ("октябрь", "октября", "окт"),
        ("ноябрь", "ноября", "нояб"),
        ("декабрь", "декабря", "дек"),
    ],
    start=1,
):
    for _form in _forms:
        MONTHS[_form] = _index

WEEKDAYS: dict[str, int] = {}
for _index, _forms in enumerate(
    [
        ("понедельник", "понедельника", "пн"),
        ("вторник", "вторника", "вт"),
        ("среда", "среды", "среду", "ср"),
        ("четверг", "четверга", "чт"),
        ("пятница", "пятницы", "пятницу", "пт"),
        ("суббота", "субботы", "субботу", "сб"),
        ("воскресенье", "воскресенья", "вс"),
    ],
    start=0,
):
    for _form in _forms:
        WEEKDAYS[_form] = _index

DAY_OFFSETS = {"сегодня": 0, "завтра": 1, "послезавтра": 2}
PART_HOURS = {
    "утром": 9,
    "утра": 9,
    "утро": 9,
    "днём": 14,
    "днем": 14,
    "дня": 14,
    "день": 14,
    "вечером": 19,
    "вечера": 19,
    "вечер": 19,
    "ночью": 2,
    "ночи": 2,
    "ночь": 2,
}
PART_OF_DAY = ("утра", "дня", "вечера", "ночи")

UNIT_MINUTES = (
    ("секунд", 0),
    ("сек", 0),
    ("минут", 1),
    ("мин", 1),
    ("час", 60),
    ("сут", 24 * 60),
    ("дн", 24 * 60),
    ("нед", 7 * 24 * 60),
)

_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_WEEKDAY_ALT = "|".join(sorted(WEEKDAYS, key=len, reverse=True))
_PART_ALT = "|".join(sorted(PART_HOURS, key=len, reverse=True))
_PART_OF_DAY_ALT = "|".join(sorted(PART_OF_DAY, key=len, reverse=True))

RE_RELATIVE = re.compile(
    r"\bчерез\s+(полтора\s+часа|полчаса|полторы\s+недели|(?:\d+(?:[.,]\d+)?\s*"
    r"(?:секунд\w*|сек|минут\w*|мин|час\w*|сут\w*|дн\w*|нед\w*)\s*)+)",
    re.IGNORECASE,
)
RE_UNIT_PAIR = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(секунд\w*|сек|минут\w*|мин|час\w*|сут\w*|дн\w*|нед\w*)", re.IGNORECASE
)
RE_TIME = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")
RE_HOUR_PART = re.compile(rf"\b(\d{{1,2}})\s+({_PART_OF_DAY_ALT})\b", re.IGNORECASE)
RE_DATE_NUM = re.compile(r"\b(\d{1,2})[.](\d{1,2})(?:[.](\d{2,4}))?\b")
RE_MONTH_DAY = re.compile(rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\w*\b", re.IGNORECASE)
RE_DAY_MONTH = re.compile(rf"\b({_MONTH_ALT})\w*\s+(\d{{1,2}})\b", re.IGNORECASE)
RE_WEEKDAY = re.compile(rf"\b(?:в\s+|по\s+)?({_WEEKDAY_ALT})\b", re.IGNORECASE)
RE_DAY_WORD = re.compile(r"\b(сегодня|завтра|послезавтра)\b", re.IGNORECASE)
RE_PART = re.compile(rf"\b({_PART_ALT})\b", re.IGNORECASE)

PREPOSITIONS = ("в", "на", "к", "до", "с", "со", "об")


@dataclass(slots=True)
class ParsedTime:
    """Распознанный момент времени + текст заметки без временных фрагментов."""

    when: datetime
    raw: str
    note: str
    explicit_date: bool

    @property
    def is_past(self) -> bool:
        return self.when <= datetime.now(tz=timezone.utc)


def _overlaps(spans: list[tuple[int, int]], start: int, end: int) -> bool:
    return any(start < span_end and span_start < end for span_start, span_end in spans)


def _valid_date(year: int, month: int, day: int) -> bool:
    if not 1 <= month <= 12:
        return False
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _relative_minutes(chunk: str) -> int:
    lowered = chunk.lower().strip()
    if lowered.startswith("полчаса"):
        return 30
    if lowered.startswith("полтора"):
        return 90
    if lowered.startswith("полторы"):
        return 7 * 24 * 60
    total = 0
    for value, unit in RE_UNIT_PAIR.findall(chunk):
        number = float(value.replace(",", "."))
        key = unit.lower().strip()
        for prefix, minutes in UNIT_MINUTES:
            if key.startswith(prefix):
                total += int(round(number * minutes))
                break
    return total


def _at(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=tz)


def _same_day_next_year(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 февраля
        return date(day.year + 1, 2, calendar.monthrange(day.year + 1, 2)[1])


def _clean_note(text: str, spans: list[tuple[int, int]]) -> str:
    """Убирает из строки распознанные временные фрагменты, оставляя текст заметки."""
    if not spans:
        return text.strip()

    merged: list[list[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    lowered = text.lower()
    pieces: list[str] = []
    cursor = 0
    for start, end in merged:
        prefix = re.search(rf"\b({'|'.join(PREPOSITIONS)})\s+$", lowered[cursor:start])
        cut_from = cursor + prefix.start() if prefix else start
        pieces.append(text[cursor:cut_from])
        cursor = end
    pieces.append(text[cursor:])

    result = " ".join("".join(pieces).split())
    return re.sub(r"^[.,;:!?-]+|[.,;:!?-]+$", "", result).strip()


def parse_when(
    text: str,
    *,
    now: datetime,
    tz: ZoneInfo,
    default_hour: int = 12,
    default_minute: int = 0,
) -> ParsedTime | None:
    """Ищет в строке дату/время. Возвращает None, если ничего не распознано."""
    if not text or not text.strip():
        return None

    local_now = now.astimezone(tz)
    spans: list[tuple[int, int]] = []
    matched: list[str] = []

    # Относительная форма "через ..." — самодостаточна.
    relative = RE_RELATIVE.search(text)
    if relative:
        minutes = _relative_minutes(relative.group(1))
        if minutes:
            spans.append(relative.span())
            when = (local_now + timedelta(minutes=minutes)).replace(second=0, microsecond=0)
            return ParsedTime(
                when=when.astimezone(timezone.utc),
                raw=relative.group(0).strip(),
                note=_clean_note(text, spans),
                explicit_date=True,
            )

    # Сначала дата: "30.10", "30.10.2026" — иначе "05.11" можно принять за время 05:11.
    day: int | None = None
    month: int | None = None
    year: int | None = None
    for match in RE_DATE_NUM.finditer(text):
        if _overlaps(spans, *match.span()):
            continue
        candidate_day, candidate_month = int(match.group(1)), int(match.group(2))
        if 1 <= candidate_day <= 31 and 1 <= candidate_month <= 12:
            raw_year = match.group(3)
            year = int(raw_year) if raw_year else None
            if year is not None and year < 100:
                year += 2000
            day, month = candidate_day, candidate_month
            spans.append(match.span())
            matched.append(match.group(0))
            break

    if day is None:
        for pattern in (RE_MONTH_DAY, RE_DAY_MONTH):
            match = pattern.search(text)
            if not match or _overlaps(spans, *match.span()):
                continue
            if pattern is RE_MONTH_DAY:
                day, month_name = int(match.group(1)), match.group(2).lower()
            else:
                day, month_name = int(match.group(2)), match.group(1).lower()
            month = MONTHS[month_name]
            spans.append(match.span())
            matched.append(match.group(0))
            break

    # Время: "18:30" либо "9 утра".
    hour: int | None = None
    minute = 0
    for match in RE_TIME.finditer(text):
        if _overlaps(spans, *match.span()):
            continue
        hour, minute = int(match.group(1)), int(match.group(2))
        spans.append(match.span())
        matched.append(match.group(0))
        break
    if hour is None:
        hour_part = RE_HOUR_PART.search(text)
        if hour_part and not _overlaps(spans, *hour_part.span()):
            raw_hour = int(hour_part.group(1))
            part = hour_part.group(2).lower()
            if part in {"вечера", "ночи"} and raw_hour < 12:
                raw_hour += 12
            if raw_hour <= 23:
                hour = raw_hour
                spans.append(hour_part.span())
                matched.append(hour_part.group(0))

    # Часть суток: "вечером", "утром".
    part_match = RE_PART.search(text)
    if part_match and not _overlaps(spans, *part_match.span()):
        spans.append(part_match.span())
        matched.append(part_match.group(0))
        if hour is None:
            hour = PART_HOURS[part_match.group(1).lower()]

    # "сегодня" / "завтра" / день недели.
    offset: int | None = None
    day_word = RE_DAY_WORD.search(text)
    if day_word and not _overlaps(spans, *day_word.span()):
        offset = DAY_OFFSETS[day_word.group(1).lower()]
        spans.append(day_word.span())
        matched.append(day_word.group(0))

    weekday: int | None = None
    if offset is None and day is None:
        weekday_match = RE_WEEKDAY.search(text)
        if weekday_match and not _overlaps(spans, *weekday_match.span()):
            weekday = WEEKDAYS[weekday_match.group(1).lower()]
            spans.append(weekday_match.span())
            matched.append(weekday_match.group(0))

    if hour is None and day is None and offset is None and weekday is None:
        return None
    if hour is None:
        hour, minute = default_hour, default_minute

    explicit_date = day is not None or offset is not None or weekday is not None
    base_day = local_now.date()
    if day is not None and month is not None:
        target_year = year or local_now.year
        if not _valid_date(target_year, month, day):
            return None
        base_day = date(target_year, month, day)
        if year is None and _at(base_day, hour, minute, tz) <= local_now:
            base_day = _same_day_next_year(base_day)  # дата в этом году уже прошла
    elif offset is not None:
        base_day = local_now.date() + timedelta(days=offset)
    elif weekday is not None:
        delta = (weekday - local_now.weekday()) % 7
        base_day = local_now.date() + timedelta(days=delta)
        if delta == 0 and _at(base_day, hour, minute, tz) <= local_now:
            base_day += timedelta(days=7)

    when = _at(base_day, hour, minute, tz)
    if not explicit_date and when <= local_now:
        when = _at(base_day + timedelta(days=1), hour, minute, tz)

    return ParsedTime(
        when=when.astimezone(timezone.utc),
        raw=", ".join(dict.fromkeys(matched)) or when.strftime("%d.%m %H:%M"),
        note=_clean_note(text, spans),
        explicit_date=explicit_date,
    )
