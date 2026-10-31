"""Настройки бота из переменных окружения (файл .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # python-dotenv не обязателен
        return
    for candidate in (PROJECT_ROOT / ".env", Path.cwd() / ".env"):
        if candidate.exists():
            load_dotenv(candidate, override=False)
            return


def _int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"Переменная {name} должна быть числом, получено {raw!r}") from exc


@dataclass(slots=True, frozen=True)
class Config:
    bot_token: str
    database_path: Path
    timezone: str
    remind_before: int
    poll_interval: int
    repeat_after: int
    max_repeats: int
    default_time: time
    allowed_users: frozenset[int]

    @classmethod
    def load(cls) -> "Config":
        _load_dotenv()

        token = (os.getenv("BOT_TOKEN") or "").strip()
        if not token:
            raise RuntimeError(
                "Не задан BOT_TOKEN. Скопируйте .env.example в .env и укажите токен от @BotFather."
            )

        db_path = Path((os.getenv("DATABASE_PATH") or "").strip() or PROJECT_ROOT / "data" / "reminders.db")
        default_time_raw = (os.getenv("DEFAULT_TIME") or "12:00").strip()
        try:
            hour_s, minute_s = default_time_raw.split(":")
            default_time = time(int(hour_s), int(minute_s))
        except ValueError as exc:
            raise ValueError(f"DEFAULT_TIME должен быть в формате ЧЧ:ММ, получено {default_time_raw!r}") from exc

        return cls(
            bot_token=token,
            database_path=db_path,
            timezone=(os.getenv("TIMEZONE") or "Europe/Moscow").strip(),
            remind_before=max(0, _int("REMIND_BEFORE_MINUTES", 30)),
            poll_interval=max(1, _int("POLL_INTERVAL_SECONDS", 5)),
            repeat_after=max(0, _int("REPEAT_AFTER_MINUTES", 0)),
            max_repeats=max(0, _int("MAX_REPEATS", 3)),
            default_time=default_time,
            allowed_users=_ids("ALLOWED_USER_IDS"),
        )


def _ids(name: str) -> frozenset[int]:
    raw = (os.getenv(name) or "").replace(";", ",")
    result: set[int] = set()
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            result.add(int(chunk))
        except ValueError as exc:
            raise ValueError(f"{name}: {chunk!r} не является числом") from exc
    return frozenset(result)
