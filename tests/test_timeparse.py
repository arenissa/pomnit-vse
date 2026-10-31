"""Тесты разбора даты/времени из текста."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.timeparse import parse_when

MSK = ZoneInfo("Europe/Moscow")
# Понедельник, 12 октября 2026, 10:00 по Москве
NOW = datetime(2026, 10, 12, 7, 0, tzinfo=timezone.utc)


def parse(text: str):
    return parse_when(text, now=NOW, tz=MSK, default_hour=12, default_minute=0)


def local(parsed) -> datetime:
    return parsed.when.astimezone(MSK)


def test_full_note_with_tomorrow_time():
    parsed = parse("Оплатить интернет завтра в 10:00")
    assert parsed is not None
    assert parsed.note == "Оплатить интернет"
    assert local(parsed) == datetime(2026, 10, 13, 10, 0, tzinfo=MSK)


def test_numeric_date_and_time():
    parsed = parse("Статью дописать 05.11 18:30")
    assert parsed is not None
    assert parsed.note == "Статью дописать"
    assert local(parsed) == datetime(2026, 11, 5, 18, 30, tzinfo=MSK)


def test_date_with_dot_time_is_not_date():
    parsed = parse("Созвон 18.30")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 10, 12, 18, 30, tzinfo=MSK)


def test_relative_hours():
    parsed = parse("Позвонить маме через 2 часа")
    assert parsed is not None
    assert parsed.note == "Позвонить маме"
    assert local(parsed) == datetime(2026, 10, 12, 12, 0, tzinfo=MSK)


def test_relative_half_hour():
    parsed = parse("Размяться через полчаса")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 10, 12, 10, 30, tzinfo=MSK)


def test_relative_days():
    parsed = parse("Полить цветы через 3 дня")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 10, 15, 10, 0, tzinfo=MSK)


def test_month_word_and_evening():
    parsed = parse("Купить билет 12.11 вечером")
    assert parsed is not None
    assert parsed.note == "Купить билет"
    assert local(parsed) == datetime(2026, 11, 12, 19, 0, tzinfo=MSK)


def test_month_word_without_time_uses_default():
    parsed = parse("Сдать отчёт 5 ноября")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 11, 5, 12, 0, tzinfo=MSK)


def test_weekday_in_future():
    parsed = parse("Встреча в пятницу 17:00")
    assert parsed is not None
    assert parsed.note == "Встреча"
    assert local(parsed) == datetime(2026, 10, 16, 17, 0, tzinfo=MSK)


def test_hour_with_part_of_day():
    parsed = parse("Зарядка 11 утра")
    assert parsed is not None
    assert parsed.note == "Зарядка"
    assert local(parsed) == datetime(2026, 10, 12, 11, 0, tzinfo=MSK)


def test_passed_hour_part_rolls_to_tomorrow():
    parsed = parse("Зарядка 9 утра")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 10, 13, 9, 0, tzinfo=MSK)


def test_seven_evening_becomes_19():
    parsed = parse("Ужин 7 вечера")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 10, 12, 19, 0, tzinfo=MSK)


def test_today_time_is_kept_if_future():
    parsed = parse("Обед сегодня 14:00")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 10, 12, 14, 0, tzinfo=MSK)


def test_time_without_date_rolls_to_tomorrow_when_passed():
    parsed = parse("Позвонить 08:00")
    assert parsed is not None
    assert local(parsed) == datetime(2026, 10, 13, 8, 0, tzinfo=MSK)


def test_date_with_year():
    parsed = parse("Новый год 01.01.2027 00:30")
    assert parsed is not None
    assert local(parsed) == datetime(2027, 1, 1, 0, 30, tzinfo=MSK)


def test_no_time_returns_none():
    assert parse("Просто купить хлеб") is None


def test_empty_text_returns_none():
    assert parse("   ") is None


def test_past_date_without_year_moves_to_next_year():
    parsed = parse("Годовщина 1 марта")
    assert parsed is not None
    assert local(parsed).year == 2027


def test_note_keeps_prepositions_inside_words():
    parsed = parse("Позвонить в банк завтра в 11:00")
    assert parsed is not None
    assert parsed.note == "Позвонить в банк"
