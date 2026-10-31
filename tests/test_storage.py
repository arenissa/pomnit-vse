"""Тесты хранилища: создание, выборки, листание, захват напоминаний."""

from __future__ import annotations

from datetime import timedelta

from app.models import ReminderStatus
from app.storage import Database


async def make_user(db: Database, now) -> int:
    user = await db.ensure_user(1, 100, "Europe/Moscow", 30)
    return user.user_id


async def test_create_sets_remind_at_before_deadline(db: Database, now):
    await make_user(db, now)
    deadline = now + timedelta(days=1)
    reminder = await db.create(1, "Позвонить", deadline, 30, now=now)

    assert reminder.remind_at == deadline - timedelta(minutes=30)
    assert reminder.status == ReminderStatus.ACTIVE
    assert reminder.notify_count == 0


async def test_list_and_position(db: Database, now):
    await make_user(db, now)
    first = await db.create(1, "Первая", now + timedelta(hours=2), 30, now=now)
    second = await db.create(1, "Вторая", now + timedelta(hours=5), 30, now=now)
    await db.create(1, "Третья", now + timedelta(hours=9), 30, now=now)

    items = await db.list(1, "open", now=now, day_start=now, day_end=now + timedelta(days=1))
    assert [item.id for item in items] == [first.id, second.id, items[2].id]

    assert await db.position(1, second.id, "open", now=now, day_start=now, day_end=now + timedelta(days=1)) == 2
    assert await db.count(1, "open", now=now, day_start=now, day_end=now + timedelta(days=1)) == 3


async def test_done_moves_between_groups(db: Database, now):
    await make_user(db, now)
    reminder = await db.create(1, "Задача", now + timedelta(hours=1), 30, now=now)
    await db.set_status(reminder.id, 1, ReminderStatus.DONE, now=now)

    open_count = await db.count(1, "open", now=now, day_start=now, day_end=now + timedelta(days=1))
    done_count = await db.count(1, "done", now=now, day_start=now, day_end=now + timedelta(days=1))
    assert (open_count, done_count) == (0, 1)


async def test_claim_pre_is_idempotent(db: Database, now):
    await make_user(db, now)
    reminder = await db.create(1, "Задача", now + timedelta(minutes=20), 30, now=now)

    assert await db.claim_pre(reminder.id) is True
    assert await db.claim_pre(reminder.id) is False

    updated = await db.get(reminder.id, 1)
    assert updated is not None
    assert updated.status == ReminderStatus.NOTIFIED
    assert updated.notify_count == 1


async def test_reschedule_resets_notification_state(db: Database, now):
    await make_user(db, now)
    reminder = await db.create(1, "Задача", now + timedelta(minutes=20), 30, now=now)
    await db.claim_pre(reminder.id)
    await db.schedule_repeat(reminder.id, now + timedelta(minutes=10))

    moved = await db.reschedule(
        reminder.id, 1, now + timedelta(days=2), 30, postpone=True, now=now
    )
    assert moved is not None
    assert moved.status == ReminderStatus.ACTIVE
    assert moved.notify_count == 0
    assert moved.next_remind_at is None
    assert moved.postpone_count == 1
    assert moved.deadline == now + timedelta(days=2)


async def test_delete_removes_only_own(db: Database, now):
    await make_user(db, now)
    reminder = await db.create(1, "Задача", now + timedelta(hours=1), 30, now=now)

    assert await db.delete(reminder.id, 999) is False
    assert await db.delete(reminder.id, 1) is True
    assert await db.get(reminder.id, 1) is None


async def test_due_queries_respect_deadline(db: Database, now):
    await make_user(db, now)
    actual = await db.create(1, "Актуальная", now + timedelta(minutes=10), 30, now=now)
    # переносим срок в прошлое — теперь это просроченная заметка
    overdue = await db.create(1, "Просроченная", now + timedelta(minutes=40), 30, now=now)
    await db.reschedule(overdue.id, 1, now - timedelta(minutes=5), 30, now=now)

    pre = await db.due_pre_reminders(now)
    assert [item.id for item in pre] == [actual.id]

    deadlines = await db.due_deadlines(now)
    assert [item.id for item in deadlines] == [overdue.id]


async def test_refresh_remind_times(db: Database, now):
    await make_user(db, now)
    reminder = await db.create(1, "Задача", now + timedelta(hours=3), 30, now=now)

    await db.refresh_remind_times(1, 60, now)
    updated = await db.get(reminder.id, 1)
    assert updated is not None
    assert updated.remind_at == reminder.deadline - timedelta(minutes=60)
