"""Точка входа: запуск бота-напоминалки."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram.exceptions import TelegramNetworkError, TelegramUnauthorizedError

from .bot import create_bot, create_dispatcher
from .config import Config
from .scheduler import ReminderScheduler
from .storage import Database

logger = logging.getLogger(__name__)


async def run() -> None:
    config = Config.load()
    db = Database(config.database_path)
    await db.connect()

    bot = create_bot(config)
    dispatcher = create_dispatcher(config, db)
    scheduler = ReminderScheduler(bot, db, config)

    try:
        me = await bot.get_me()
        logger.info("Бот @%s запущен (БД: %s)", me.username, config.database_path)
        scheduler.start()
        await dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types())
    finally:
        await scheduler.stop()
        await db.close()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )
    try:
        asyncio.run(run())
    except (KeyboardInterrupt, SystemExit):
        print("\nОстановлено пользователем")
    except TelegramUnauthorizedError:
        print("Telegram отклонил токен. Проверьте BOT_TOKEN в .env", file=sys.stderr)
        sys.exit(1)
    except TelegramNetworkError as exc:
        print(f"Нет связи с Telegram: {exc}. Проверьте интернет или прокси.", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(f"Ошибка запуска: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
