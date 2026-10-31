"""Тесты планировщика: отправка напоминаний, повторы, реакция на выполнение."""

from __future__ import annotations

from datetime import time, timedelta

from app.config import Config
from app.models import ReminderStatus
from app.scheduler import ReminderScheduler
from app.storage import Database


class FakeBot:
    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None) -> None:  # noqa: ANN001
        self.sent.append((chat_id, text))


def make_config() -> Config:
    return Config(
        bot_token="123:abc",
        database_path="/tmp/none.db",
        timezone="Europe/Moscow",
        remind_before=30,
        poll_interval=1,
        repeat_after=10,
        max_repeats=2,
        default_time=time(12, 0),
        allowed_users=frozenset(),
    )


async def test_sends_pre_reminder_once(db: Database, now):
    await db.ensure_user(1, 100, "Europe/Moscow", 30)
    reminder = await db.create(1, "Оплатить", now + timedelta(minutes=20), 30, now=now)

    bot = FakeBot()
    scheduler = ReminderScheduler(bot, db, make_config())  # type: ignore[arg-type]

    await scheduler.tick(now)
    assert len(bot.sent) == 1
    assert "Оплатить" in bot.sent[0][1]

    updated = await db.get(reminder.id, 1)
    assert updated is not None
    assert updated.status == ReminderStatus.NOTIFIED
    assert updated.next_remind_at == now + timedelta(minutes=10)

    # повторный тик не должен слать то же напоминание снова
    await scheduler.tick(now)
    assert len(bot.sent) == 1


async def test_repeat_until_limit(db: Database, now):
    await db.ensure_user(1, 100, "Europe/Moscow", 30)
    # срок через 55 минут -> первое напоминание через 25 минут
    reminder = await db.create(1, "Оплатить", now + timedelta(minutes=55), 30, now=now)

    bot = FakeBot()
    scheduler = ReminderScheduler(bot, db, make_config())  # type: ignore[arg-type]

    await scheduler.tick(now)
    assert len(bot.sent) == 0  # рано

    await scheduler.tick(now + timedelta(minutes=25))  # первое напоминание
    assert len(bot.sent) == 1

    await scheduler.tick(now + timedelta(minutes=30))
    assert len(bot.sent) == 1  # время повтора ещё не пришло

    # повтор 1 из 2
    await scheduler.tick(now + timedelta(minutes=35))
    assert len(bot.sent) == 2

    # повтор 2 из 2
    await scheduler.tick(now + timedelta(minutes=45))
    assert len(bot.sent) == 3

    # лимит исчерпан — больше не напоминаем
    await scheduler.tick(now + timedelta(minutes=50))
    assert len(bot.sent) == 3

    updated = await db.get(reminder.id, 1)
    assert updated is not None
    assert updated.notify_count == 3
    assert updated.next_remind_at is None


async def test_postpone_restores_active_status(db: Database, now):
    await db.ensure_user(1, 100, "Europe/Moscow", 30)
    reminder = await db.create(1, "Оплатить", now + timedelta(minutes=20), 30, now=now)

    bot = FakeBot()
    scheduler = ReminderScheduler(bot, db, make_config())  # type: ignore[arg-type]
    await scheduler.tick(now)
    assert len(bot.sent) == 1

    # пользователь нажал «Отложить» на час
    moved = await db.reschedule(reminder.id, 1, now + timedelta(hours=1), 30, postpone=True, now=now)
    assert moved is not None
    assert moved.status == ReminderStatus.ACTIVE

    await scheduler.tick(now + timedelta(minutes=20))
    assert len(bot.sent) == 1  # раньше нового срока не напоминаем


async def test_done_stops_reminders(db: Database, now):
    await db.ensure_user(1, 100, "Europe/Moscow", 30)
    reminder = await db.create(1, "Оплатить", now + timedelta(minutes=20), 30, now=now)
    await db.set_status(reminder.id, 1, ReminderStatus.DONE, now=now)

    bot = FakeBot()
    scheduler = ReminderScheduler(bot, db, make_config())  # type: ignore[arg-type]
    await scheduler.tick()

    assert bot.sent == []


async def test_deadline_notification(db: Database, now):
    await db.ensure_user(1, 100, "Europe/Moscow", 30)
    reminder = await db.create(1, "Сдать отчёт", now + timedelta(minutes=5), 30, now=now)
    # срок наступил
    await db.reschedule(reminder.id, 1, now - timedelta(minutes=1), 30, now=now)

    bot = FakeBot()
    scheduler = ReminderScheduler(bot, db, make_config())  # type: ignore[arg-type]
    await scheduler.tick()

    assert len(bot.sent) == 1
    assert "Сдать отчёт" in bot.sent[0][1]

    updated = await db.get(reminder.id, 1)
    assert updated is not None
    assert updated.deadline_notified is True

    await scheduler.tick()
    assert len(bot.sent) == 1
