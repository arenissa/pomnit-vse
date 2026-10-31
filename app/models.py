"""Модели данных бота."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class ReminderStatus(StrEnum):
    ACTIVE = "active"  # срок ещё не наступал, напоминание не отправлено
    NOTIFIED = "notified"  # напоминание отправлено, ждём реакцию
    DONE = "done"


OPEN_STATUSES = (ReminderStatus.ACTIVE, ReminderStatus.NOTIFIED)


@dataclass(slots=True)
class UserSettings:
    user_id: int
    chat_id: int
    timezone: str
    remind_before: int

    @property
    def tz_name(self) -> str:
        return self.timezone


@dataclass(slots=True)
class Reminder:
    id: int
    user_id: int
    text: str
    deadline: datetime
    status: ReminderStatus
    remind_at: datetime | None
    next_remind_at: datetime | None
    notify_count: int
    deadline_notified: bool
    postpone_count: int
    created_at: datetime
    updated_at: datetime

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    def is_overdue(self, now: datetime) -> bool:
        return self.is_open and self.deadline <= now
