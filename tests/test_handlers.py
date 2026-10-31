"""Интеграционные тесты: апдейты проходят через настоящий Dispatcher с фейковой сессией.

Роутеры aiogram нельзя подключить к двум Dispatcher'ам, поэтому окружение
создаётся один раз на модуль, а данные между тестами очищаются.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from pathlib import Path

import pytest_asyncio
from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import (
    AnswerCallbackQuery,
    EditMessageText,
    SendMessage,
    TelegramMethod,
)
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from app.bot import create_dispatcher
from app.config import Config
from app.storage import Database

USER = User(id=1, is_bot=False, first_name="Тест")
CHAT = Chat(id=1, type="private")


class FakeSession(BaseSession):
    """Перехватывает запросы к Telegram и возвращает правдоподобные ответы."""

    def __init__(self) -> None:
        super().__init__()
        self.requests: list[TelegramMethod] = []

    async def make_request(self, bot: Bot, method: TelegramMethod, timeout: int | None = None):  # noqa: ANN001
        self.requests.append(method)
        if isinstance(method, (SendMessage, EditMessageText)):
            return Message(
                message_id=len(self.requests),
                date=datetime.now(tz=timezone.utc),
                chat=CHAT,
                text=method.text,
            )
        if isinstance(method, AnswerCallbackQuery):
            return True
        return True

    async def stream_content(self, *args, **kwargs):  # pragma: no cover
        raise NotImplementedError

    async def close(self) -> None:
        return None

    @property
    def texts(self) -> list[str]:
        return [request.text for request in self.requests if getattr(request, "text", None)]

    def has_text(self, needle: str) -> bool:
        return any(needle in text for text in self.texts)

    @property
    def alerts(self) -> list[str]:
        return [request.text or "" for request in self.requests if isinstance(request, AnswerCallbackQuery)]


@dataclass
class Env:
    dispatcher: object
    bot: Bot
    session: FakeSession
    db: Database


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def env():
    config = Config(
        bot_token="42:TEST",
        database_path="/tmp/none.db",
        timezone="Europe/Moscow",
        remind_before=30,
        poll_interval=1,
        repeat_after=0,
        max_repeats=0,
        default_time=time(12, 0),
        allowed_users=frozenset(),
    )
    db = Database(Path(tempfile.mkdtemp()) / "handlers.db")
    await db.connect()

    bot = Bot(token=config.bot_token)
    session = FakeSession()
    bot.session = session
    dispatcher = create_dispatcher(config, db)

    yield Env(dispatcher, bot, session, db)

    await bot.session.close()
    await db.close()


@pytest_asyncio.fixture(loop_scope="module", autouse=True)
async def clean(env: Env):
    await env.db.conn.execute("DELETE FROM reminders")
    await env.db.conn.execute("DELETE FROM users")
    await env.db.conn.commit()
    env.session.requests.clear()
    yield


def make_update(text: str, update_id: int = 1) -> Update:
    return Update(
        update_id=update_id,
        message=Message(
            message_id=update_id,
            date=datetime.now(tz=timezone.utc),
            chat=CHAT,
            from_user=USER,
            text=text,
        ),
    )


def make_callback(data: str, update_id: int = 2) -> Update:
    return Update(
        update_id=update_id,
        callback_query=CallbackQuery(
            id=str(update_id),
            from_user=USER,
            chat_instance="test",
            data=data,
            message=Message(
                message_id=100,
                date=datetime.now(tz=timezone.utc),
                chat=CHAT,
                from_user=USER,
                text="карточка",
            ),
        ),
    )


async def test_start_shows_menu(env: Env):
    await env.dispatcher.feed_update(env.bot, make_update("/start"))

    assert env.session.texts, "бот должен ответить на /start"
    assert "напоминалка" in env.session.texts[0].lower()


async def test_text_note_is_created(env: Env):
    await env.dispatcher.feed_update(env.bot, make_update("Оплатить интернет завтра в 10:00"))

    assert env.session.has_text("Заметка сохранена")
    now = datetime.now(tz=timezone.utc)
    reminders = await env.db.list(1, "open", now=now, day_start=now, day_end=now + timedelta(days=30))
    assert [item.text for item in reminders] == ["Оплатить интернет"]


async def test_note_without_time_asks_for_it(env: Env):
    await env.dispatcher.feed_update(env.bot, make_update("Купить хлеб"))
    assert env.session.has_text("До какого времени")

    await env.dispatcher.feed_update(env.bot, make_update("завтра в 18:00", update_id=3))
    assert env.session.has_text("Заметка сохранена")


async def test_list_shows_card(env: Env):
    await env.db.ensure_user(1, 1, "Europe/Moscow", 30)
    await env.db.create(1, "Проверить список", datetime.now(tz=timezone.utc) + timedelta(hours=2), 30)

    await env.dispatcher.feed_update(env.bot, make_update("/list"))

    assert env.session.has_text("Проверить список")
    assert env.session.has_text("1 из 1")


async def test_callback_done_marks_reminder(env: Env):
    await env.db.ensure_user(1, 1, "Europe/Moscow", 30)
    reminder = await env.db.create(1, "Сделать дело", datetime.now(tz=timezone.utc) + timedelta(hours=2), 30)

    await env.dispatcher.feed_update(env.bot, make_callback(f"act:{reminder.id}:done:r"))

    updated = await env.db.get(reminder.id, 1)
    assert updated is not None
    assert str(updated.status) == "done"
    assert env.session.has_text("Выполнено")


async def test_callback_postpone_quick_option(env: Env):
    await env.db.ensure_user(1, 1, "Europe/Moscow", 30)
    reminder = await env.db.create(1, "Перенести меня", datetime.now(tz=timezone.utc) + timedelta(minutes=10), 30)

    await env.dispatcher.feed_update(env.bot, make_callback(f"pos:{reminder.id}:h1:r"))

    updated = await env.db.get(reminder.id, 1)
    assert updated is not None
    assert updated.postpone_count == 1
    assert updated.deadline > datetime.now(tz=timezone.utc) + timedelta(minutes=50)
    assert env.session.has_text("Срок перенесён")


async def test_callback_navigation(env: Env):
    await env.db.ensure_user(1, 1, "Europe/Moscow", 30)
    for index in range(3):
        await env.db.create(1, f"Задача {index}", datetime.now(tz=timezone.utc) + timedelta(hours=index + 1), 30)

    await env.dispatcher.feed_update(env.bot, make_callback("grp:open"))
    assert env.session.has_text("1 из 3")

    await env.dispatcher.feed_update(env.bot, make_callback("nav:open:1:next", update_id=5))
    assert env.session.has_text("2 из 3")


async def test_unknown_command_gets_hint(env: Env):
    await env.dispatcher.feed_update(env.bot, make_update("/nonexistent"))
    assert env.session.has_text("Не знаю такую команду")


async def test_stub_button_is_answered(env: Env):
    await env.dispatcher.feed_update(env.bot, make_callback("#"))
    assert env.session.requests, "кнопка-заглушка должна получать answerCallbackQuery"


async def test_relative_time_only_asks_for_task_text(env: Env):
    await env.dispatcher.feed_update(env.bot, make_update("через 2 часа"))
    assert env.session.has_text("Что нужно сделать")

    await env.dispatcher.feed_update(env.bot, make_update("Размяться", update_id=4))
    assert env.session.has_text("Заметка сохранена")

    now = datetime.now(tz=timezone.utc)
    reminders = await env.db.list(1, "open", now=now, day_start=now, day_end=now + timedelta(days=1))
    assert [item.text for item in reminders] == ["Размяться"]


async def test_settings_interval_button(env: Env):
    await env.dispatcher.feed_update(env.bot, make_update("/settings"))
    assert env.session.has_text("Настройки")

    await env.dispatcher.feed_update(env.bot, make_callback("set:rb:60", update_id=6))
    user = await env.db.get_user(1)
    assert user is not None
    assert user.remind_before == 60
    assert env.session.has_text("за 60 мин")


async def test_custom_postpone_by_text(env: Env):
    await env.db.ensure_user(1, 1, "Europe/Moscow", 30)
    reminder = await env.db.create(1, "Свой срок", datetime.now(tz=timezone.utc) + timedelta(minutes=10), 30)

    await env.dispatcher.feed_update(env.bot, make_callback(f"pos:{reminder.id}:custom:r", update_id=7))
    assert env.session.has_text("Свой срок")

    await env.dispatcher.feed_update(env.bot, make_update("через 3 часа", update_id=8))
    updated = await env.db.get(reminder.id, 1)
    assert updated is not None
    assert updated.postpone_count == 1
    assert updated.deadline > datetime.now(tz=timezone.utc) + timedelta(hours=2)
    assert env.session.has_text("Срок перенесён")


async def test_done_from_card_returns_to_list(env: Env):
    await env.db.ensure_user(1, 1, "Europe/Moscow", 30)
    first = await env.db.create(1, "Первая", datetime.now(tz=timezone.utc) + timedelta(hours=1), 30)
    await env.db.create(1, "Вторая", datetime.now(tz=timezone.utc) + timedelta(hours=2), 30)

    await env.dispatcher.feed_update(env.bot, make_callback(f"act:{first.id}:done:c", update_id=9))

    updated = await env.db.get(first.id, 1)
    assert updated is not None
    assert str(updated.status) == "done"
    # карточка списка обновилась на следующую активную заметку
    assert env.session.has_text("Вторая")
    assert env.session.has_text("1 из 1")


async def test_empty_list_has_hint(env: Env):
    await env.dispatcher.feed_update(env.bot, make_callback("grp:overdue"))
    assert env.session.has_text("Просроченных заметок нет")
