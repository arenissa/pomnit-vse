"""Фоновый планировщик напоминаний.

Каждые POLL_INTERVAL_SECONDS секунд проверяет базу и отправляет:
  • предварительное напоминание (за N минут до срока);
  • повторные напоминания, если пользователь не отреагировал;
  • уведомление о наступившем сроке.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Callable

from aiogram import Bot
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramRetryAfter,
)

from . import views
from .config import Config
from .keyboards import standalone
from .models import Reminder
from .storage import Database
from .timeutil import get_tz, utcnow

logger = logging.getLogger(__name__)


class ReminderScheduler:
    def __init__(self, bot: Bot, db: Database, config: Config, now_fn: Callable[[], datetime] = utcnow) -> None:
        self._bot = bot
        self._db = db
        self._config = config
        self._now = now_fn
        self._task: asyncio.Task | None = None
        self._stopping = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="reminder-scheduler")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        logger.info("Планировщик запущен, интервал опроса %s c", self._config.poll_interval)
        while not self._stopping.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — планировщик не должен падать
                logger.exception("Ошибка в цикле планировщика")
            try:
                await asyncio.wait_for(self._stopping.wait(), timeout=self._config.poll_interval)
            except asyncio.TimeoutError:
                continue

    async def tick(self, now: datetime | None = None) -> None:
        now = now or self._now()
        await self._send_pre(now)
        await self._send_repeats(now)
        await self._send_deadlines(now)

    # --- отправка -------------------------------------------------------
    async def _deliver(self, reminder: Reminder, text: str) -> bool:
        """Отправляет сообщение в чат пользователя. True — если доставлено."""
        user = await self._db.get_user(reminder.user_id)
        if user is None:
            logger.warning("Нет настроек для пользователя %s, пропускаю заметку %s", reminder.user_id, reminder.id)
            return False
        try:
            await self._bot.send_message(
                chat_id=user.chat_id,
                text=text,
                reply_markup=standalone(reminder.id, True, "r"),
            )
            return True
        except TelegramRetryAfter as exc:
            logger.warning("Telegram просит подождать %s c", exc.retry_after)
            await asyncio.sleep(exc.retry_after)
            return False
        except TelegramForbiddenError:
            logger.warning("Пользователь %s заблокировал бота", reminder.user_id)
            return False
        except TelegramAPIError as exc:
            logger.warning("Не удалось отправить напоминание %s: %s", reminder.id, exc)
            return False

    def _next_repeat(self, reminder: Reminder, now) -> object:
        """Когда присылать следующее повторное напоминание (или None)."""
        if not self._config.repeat_after:
            return None
        # reminder.notify_count — сколько уже было отправлено до текущего
        already = reminder.notify_count + 1
        if already >= 1 + self._config.max_repeats:
            return None
        return now + timedelta(minutes=self._config.repeat_after)

    async def _send_pre(self, now) -> None:
        for reminder in await self._db.due_pre_reminders(now):
            if not await self._db.claim_pre(reminder.id):
                continue  # кто-то успел раньше
            user = await self._db.get_user(reminder.user_id)
            tz = get_tz(user.timezone) if user else get_tz(self._config.timezone)
            text = views.render_notification(reminder, tz=tz, now=now, kind="pre")
            if await self._deliver(reminder, text):
                await self._db.schedule_repeat(reminder.id, self._next_repeat(reminder, now))  # type: ignore[arg-type]
            else:
                await self._db.revert_pre(reminder.id)

    async def _send_repeats(self, now) -> None:
        total = 1 + self._config.max_repeats
        for reminder in await self._db.due_repeats(now):
            if not await self._db.claim_repeat(reminder.id):
                continue
            user = await self._db.get_user(reminder.user_id)
            tz = get_tz(user.timezone) if user else get_tz(self._config.timezone)
            text = views.render_notification(
                reminder, tz=tz, now=now, kind="repeat", repeat_of=total if self._config.max_repeats else 0
            )
            if await self._deliver(reminder, text):
                await self._db.schedule_repeat(reminder.id, self._next_repeat(reminder, now))  # type: ignore[arg-type]
            else:
                await self._db.revert_repeat(reminder.id, now + timedelta(minutes=max(self._config.repeat_after, 1)))

    async def _send_deadlines(self, now) -> None:
        for reminder in await self._db.due_deadlines(now):
            if not await self._db.claim_deadline(reminder.id):
                continue
            user = await self._db.get_user(reminder.user_id)
            tz = get_tz(user.timezone) if user else get_tz(self._config.timezone)
            text = views.render_notification(reminder, tz=tz, now=now, kind="deadline")
            if not await self._deliver(reminder, text):
                await self._db.revert_deadline(reminder.id)
