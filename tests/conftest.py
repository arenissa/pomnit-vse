"""Общие фикстуры тестов."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
import pytest_asyncio

from app.storage import Database


@pytest_asyncio.fixture
async def db(tmp_path: Path):
    database = Database(tmp_path / "test.db")
    await database.connect()
    try:
        yield database
    finally:
        await database.close()


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 10, 12, 7, 0, tzinfo=timezone.utc)
