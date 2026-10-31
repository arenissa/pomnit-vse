"""Хранилище на SQLite (aiosqlite): заметки, настройки пользователей, очередь напоминаний."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from .models import OPEN_STATUSES, Reminder, ReminderStatus, UserSettings
from .timeutil import from_db, to_db

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id        INTEGER PRIMARY KEY,
    chat_id        INTEGER NOT NULL,
    timezone       TEXT    NOT NULL,
    remind_before  INTEGER NOT NULL,
    created_at     TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id           INTEGER NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    text              TEXT    NOT NULL,
    deadline          TEXT    NOT NULL,
    status            TEXT    NOT NULL DEFAULT 'active',
    remind_at         TEXT,
    next_remind_at    TEXT,
    notify_count      INTEGER NOT NULL DEFAULT 0,
    deadline_notified INTEGER NOT NULL DEFAULT 0,
    postpone_count    INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders (user_id, status, deadline);
CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders (status, remind_at);
CREATE INDEX IF NOT EXISTS idx_reminders_repeat ON reminders (status, next_remind_at);
"""

# Группы списка заметок: (название, SQL-условие, сортировка)
GROUPS: dict[str, tuple[str, str, str]] = {
    "open": ("активные", "status IN ('active', 'notified')", "deadline ASC"),
    "today": ("на сегодня", "status IN ('active', 'notified') AND deadline >= :day_start AND deadline < :day_end", "deadline ASC"),
    "overdue": ("просроченные", "status IN ('active', 'notified') AND deadline <= :now", "deadline ASC"),
    "done": ("выполненные", "status = 'done'", "updated_at DESC"),
}

def _row_to_reminder(row: aiosqlite.Row) -> Reminder:
    return Reminder(
        id=row["id"],
        user_id=row["user_id"],
        text=row["text"],
        deadline=from_db(row["deadline"]),  # type: ignore[arg-type]
        status=ReminderStatus(row["status"]),
        remind_at=from_db(row["remind_at"]),
        next_remind_at=from_db(row["next_remind_at"]),
        notify_count=row["notify_count"],
        deadline_notified=bool(row["deadline_notified"]),
        postpone_count=row["postpone_count"],
        created_at=from_db(row["created_at"]),  # type: ignore[arg-type]
        updated_at=from_db(row["updated_at"]),  # type: ignore[arg-type]
    )


def _params(now: datetime, day_start: datetime, day_end: datetime) -> dict[str, str]:
    return {
        "now": to_db(now),
        "day_start": to_db(day_start),
        "day_end": to_db(day_end),
    }


class Database:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._conn: aiosqlite.Connection | None = None

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("База данных не подключена")
        return self._conn

    async def connect(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.execute("PRAGMA journal_mode=WAL")
        await self._conn.execute("PRAGMA foreign_keys=ON")
        await self._conn.executescript(SCHEMA)
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None

    # --- пользователи ---------------------------------------------------
    async def ensure_user(self, user_id: int, chat_id: int, timezone_name: str, remind_before: int) -> UserSettings:
        now = to_db(datetime.now(tz=timezone.utc))
        await self.conn.execute(
            """
            INSERT INTO users (user_id, chat_id, timezone, remind_before, created_at)
            VALUES (:user_id, :chat_id, :timezone, :remind_before, :created_at)
            ON CONFLICT (user_id) DO UPDATE SET chat_id = excluded.chat_id
            """,
            {"user_id": user_id, "chat_id": chat_id, "timezone": timezone_name, "remind_before": remind_before, "created_at": now},
        )
        await self.conn.commit()
        return await self.get_user(user_id)  # type: ignore[return-value]

    async def get_user(self, user_id: int) -> UserSettings | None:
        async with self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
        if row is None:
            return None
        return UserSettings(
            user_id=row["user_id"],
            chat_id=row["chat_id"],
            timezone=row["timezone"],
            remind_before=row["remind_before"],
        )

    async def set_timezone(self, user_id: int, timezone_name: str) -> None:
        await self.conn.execute("UPDATE users SET timezone = ? WHERE user_id = ?", (timezone_name, user_id))
        await self.conn.commit()

    async def set_remind_before(self, user_id: int, minutes: int) -> None:
        await self.conn.execute("UPDATE users SET remind_before = ? WHERE user_id = ?", (minutes, user_id))
        await self.conn.commit()

    async def refresh_remind_times(self, user_id: int, remind_before: int, now: datetime) -> int:
        """Пересчитывает время напоминания у заметок, по которым ещё не было напоминания."""
        active = await self._select(
            "SELECT * FROM reminders WHERE user_id = :user_id AND status = 'active' ORDER BY deadline LIMIT 1000",
            {"user_id": user_id},
        )
        for reminder in active:
            remind_at = max(reminder.deadline - timedelta(minutes=remind_before), now)
            await self.conn.execute(
                "UPDATE reminders SET remind_at = :remind_at, updated_at = :now WHERE id = :id AND status = 'active'",
                {"remind_at": to_db(remind_at), "now": to_db(now), "id": reminder.id},
            )
        await self.conn.commit()
        return len(active)

    # --- заметки ---------------------------------------------------------
    async def create(
        self,
        user_id: int,
        text: str,
        deadline: datetime,
        remind_before: int,
        now: datetime | None = None,
    ) -> Reminder:
        now = now or datetime.now(tz=timezone.utc)
        remind_at = max(deadline - timedelta(minutes=remind_before), now)
        reminder_id = await self._insert(user_id, text, deadline, remind_at, now)
        return await self.get(reminder_id, user_id)  # type: ignore[return-value]

    async def _insert(self, user_id: int, text: str, deadline: datetime, remind_at: datetime, now: datetime) -> int:
        cursor = await self.conn.execute(
            """
            INSERT INTO reminders (user_id, text, deadline, status, remind_at, next_remind_at,
                                   notify_count, deadline_notified, postpone_count, created_at, updated_at)
            VALUES (:user_id, :text, :deadline, 'active', :remind_at, NULL, 0, :deadline_notified, 0, :now, :now)
            """,
            {
                "user_id": user_id,
                "text": text,
                "deadline": to_db(deadline),
                "remind_at": to_db(remind_at),
                # срок уже прошёл — не дублируем подтверждением «срок истёк»
                "deadline_notified": 1 if deadline <= now else 0,
                "now": to_db(now),
            },
        )
        await self.conn.commit()
        return cursor.lastrowid  # type: ignore[return-value]

    async def get(self, reminder_id: int, user_id: int) -> Reminder | None:
        async with self.conn.execute(
            "SELECT * FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id)
        ) as cursor:
            row = await cursor.fetchone()
        return _row_to_reminder(row) if row else None

    async def reschedule(
        self,
        reminder_id: int,
        user_id: int,
        deadline: datetime,
        remind_before: int,
        *,
        text: str | None = None,
        postpone: bool = False,
        now: datetime | None = None,
    ) -> Reminder | None:
        """Переносит срок (и при необходимости меняет текст), сбрасывая напоминания."""
        now = now or datetime.now(tz=timezone.utc)
        remind_at = max(deadline - timedelta(minutes=remind_before), now)
        current = await self.get(reminder_id, user_id)
        if current is None:
            return None
        await self.conn.execute(
            """
            UPDATE reminders
               SET text = :text, deadline = :deadline, status = 'active', remind_at = :remind_at,
                   next_remind_at = NULL, notify_count = 0, deadline_notified = 0,
                   postpone_count = postpone_count + :postpone_inc, updated_at = :now
             WHERE id = :id AND user_id = :user_id
            """,
            {
                "text": text if text is not None else current.text,
                "deadline": to_db(deadline),
                "remind_at": to_db(remind_at),
                "postpone_inc": 1 if postpone else 0,
                "now": to_db(now),
                "id": reminder_id,
                "user_id": user_id,
            },
        )
        await self.conn.commit()
        return await self.get(reminder_id, user_id)

    async def set_status(self, reminder_id: int, user_id: int, status: ReminderStatus, now: datetime | None = None) -> None:
        now = now or datetime.now(tz=timezone.utc)
        await self.conn.execute(
            "UPDATE reminders SET status = :status, next_remind_at = NULL, updated_at = :now "
            "WHERE id = :id AND user_id = :user_id",
            {"status": str(status), "now": to_db(now), "id": reminder_id, "user_id": user_id},
        )
        await self.conn.commit()

    async def delete(self, reminder_id: int, user_id: int) -> bool:
        cursor = await self.conn.execute(
            "DELETE FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id)
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def list(
        self,
        user_id: int,
        group: str,
        *,
        now: datetime,
        day_start: datetime,
        day_end: datetime,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Reminder]:
        title, condition, order = GROUPS[group]
        sql = f"SELECT * FROM reminders WHERE user_id = :user_id AND {condition} ORDER BY {order} LIMIT :limit OFFSET :offset"
        params = _params(now, day_start, day_end) | {"user_id": user_id, "limit": limit, "offset": offset}
        async with self.conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_reminder(row) for row in rows]

    async def count(self, user_id: int, group: str, *, now: datetime, day_start: datetime, day_end: datetime) -> int:
        title, condition, _ = GROUPS[group]
        sql = f"SELECT COUNT(*) AS n FROM reminders WHERE user_id = :user_id AND {condition}"
        params = _params(now, day_start, day_end) | {"user_id": user_id}
        async with self.conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
        return int(row["n"])

    async def summary(self, user_id: int, *, now: datetime, day_start: datetime, day_end: datetime) -> dict[str, int]:
        result: dict[str, int] = {}
        for group in GROUPS:
            result[group] = await self.count(user_id, group, now=now, day_start=day_start, day_end=day_end)
        return result

    async def position(
        self, user_id: int, reminder_id: int, group: str, *, now: datetime, day_start: datetime, day_end: datetime
    ) -> int | None:
        """1-based номер заметки внутри отфильтрованного списка (для листания)."""
        target = await self.get(reminder_id, user_id)
        if target is None:
            return None
        _, condition, order = GROUPS[group]
        if order.startswith("deadline"):
            before = "(deadline < :t_deadline OR (deadline = :t_deadline AND id < :t_id))"
        else:
            before = "(updated_at > :t_updated OR (updated_at = :t_updated AND id > :t_id))"
        sql = (
            "SELECT SUM(CASE WHEN id = :t_id THEN 1 ELSE 0 END) AS present, "
            f"SUM(CASE WHEN {before} THEN 1 ELSE 0 END) AS before_n "
            "FROM reminders WHERE user_id = :user_id AND " + condition
        )
        params = _params(now, day_start, day_end) | {
            "user_id": user_id,
            "t_id": target.id,
            "t_deadline": to_db(target.deadline),
            "t_updated": to_db(target.updated_at),
        }
        async with self.conn.execute(sql, params) as cursor:
            row = await cursor.fetchone()
        if row is None or not row["present"]:
            return None
        return int(row["before_n"] or 0) + 1

    # --- очередь напоминаний ---------------------------------------------
    async def due_pre_reminders(self, now: datetime, limit: int = 25) -> list[Reminder]:
        return await self._select(
            "SELECT * FROM reminders WHERE status = 'active' AND remind_at IS NOT NULL AND remind_at <= :now "
            "AND deadline > :now ORDER BY remind_at LIMIT :limit",
            {"now": to_db(now), "limit": limit},
        )

    async def due_repeats(self, now: datetime, limit: int = 25) -> list[Reminder]:
        return await self._select(
            "SELECT * FROM reminders WHERE status = 'notified' AND next_remind_at IS NOT NULL "
            "AND next_remind_at <= :now AND deadline > :now ORDER BY next_remind_at LIMIT :limit",
            {"now": to_db(now), "limit": limit},
        )

    async def due_deadlines(self, now: datetime, limit: int = 25) -> list[Reminder]:
        statuses = ", ".join(f"'{status.value}'" for status in OPEN_STATUSES)
        return await self._select(
            f"SELECT * FROM reminders WHERE status IN ({statuses}) AND deadline_notified = 0 AND deadline <= :now "
            "ORDER BY deadline LIMIT :limit",
            {"now": to_db(now), "limit": limit},
        )

    async def _select(self, sql: str, params: dict) -> list[Reminder]:
        async with self.conn.execute(sql, params) as cursor:
            rows = await cursor.fetchall()
        return [_row_to_reminder(row) for row in rows]

    async def claim_pre(self, reminder_id: int) -> bool:
        """Атомарно переводит active -> notified, чтобы напоминание не ушло дважды."""
        cursor = await self.conn.execute(
            "UPDATE reminders SET status = 'notified', notify_count = notify_count + 1, updated_at = :now "
            "WHERE id = :id AND status = 'active'",
            {"now": to_db(datetime.now(tz=timezone.utc)), "id": reminder_id},
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def revert_pre(self, reminder_id: int) -> None:
        """Откатывает захват, если сообщение не удалось отправить."""
        await self.conn.execute(
            "UPDATE reminders SET status = 'active', notify_count = MAX(notify_count - 1, 0) WHERE id = ? AND status = 'notified'",
            (reminder_id,),
        )
        await self.conn.commit()

    async def claim_repeat(self, reminder_id: int) -> bool:
        cursor = await self.conn.execute(
            "UPDATE reminders SET next_remind_at = NULL, notify_count = notify_count + 1, updated_at = :now "
            "WHERE id = :id AND status = 'notified' AND next_remind_at IS NOT NULL",
            {"now": to_db(datetime.now(tz=timezone.utc)), "id": reminder_id},
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def revert_repeat(self, reminder_id: int, next_at: datetime) -> None:
        await self.conn.execute(
            "UPDATE reminders SET next_remind_at = :next_at WHERE id = :id AND status = 'notified'",
            {"next_at": to_db(next_at), "id": reminder_id},
        )
        await self.conn.commit()

    async def schedule_repeat(self, reminder_id: int, next_at: datetime | None) -> None:
        await self.conn.execute(
            "UPDATE reminders SET next_remind_at = :next_at WHERE id = :id",
            {"next_at": to_db(next_at), "id": reminder_id},
        )
        await self.conn.commit()

    async def claim_deadline(self, reminder_id: int) -> bool:
        cursor = await self.conn.execute(
            "UPDATE reminders SET deadline_notified = 1 WHERE id = :id AND deadline_notified = 0",
            {"id": reminder_id},
        )
        await self.conn.commit()
        return cursor.rowcount > 0

    async def revert_deadline(self, reminder_id: int) -> None:
        await self.conn.execute("UPDATE reminders SET deadline_notified = 0 WHERE id = :id", {"id": reminder_id})
        await self.conn.commit()
