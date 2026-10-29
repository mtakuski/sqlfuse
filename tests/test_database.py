"""Database facade (sync + async)."""
import asyncio

import pytest

from sqlfuse import Database, func, select
from tests.models import Hero


def test_sync_database(tmp_path):
    db = Database(f"sqlite:///{tmp_path}/s.db")
    assert not db.is_async
    db.create_all()
    with db.session() as s:
        s.add(Hero(name="Tony"))
    with pytest.raises(RuntimeError, match="boom"):
        with db.session() as s:
            s.add(Hero(name="Rolled back"))
            raise RuntimeError("boom")
    with db.session() as s:
        assert s.exec(select(Hero.name)).all() == ["Tony"]
    db.drop_all()
    asyncio.run(db.dispose())


def test_sync_database_rejects_async_api():
    db = Database("sqlite://")

    async def use_async():
        async with db.async_session():
            pass

    with pytest.raises(RuntimeError, match="async"):
        asyncio.run(use_async())


def test_async_drop_all(tmp_path):
    async def main():
        db = Database(f"sqlite+aiosqlite:///{tmp_path}/a.db")
        await db.acreate_all()
        async with db.async_session() as s:
            s.add(Hero(name="Thor"))
        async with db.async_session() as s:
            assert (await s.exec(select(func.count()).select_from(Hero))).one() == 1
        await db.adrop_all()
        await db.dispose()

    asyncio.run(main())
