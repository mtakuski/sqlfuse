import asyncio

import pytest

from sqlfuse import AsyncSession, Database, ValidationError, create_async_engine, func, select, selectinload
from tests.models import Hero, SQLFuse, Team


def run(coro):
    return asyncio.run(coro)


def test_async_database_facade(tmp_path):
    async def main():
        db = Database(f"sqlite+aiosqlite:///{tmp_path}/a.db")
        await db.acreate_all()
        async with db.async_session() as s:
            s.add(Team(name="Guardians", heroes=[{"name": "Groot", "powers": [{"name": "grow"}]},
                                                  {"name": "Rocket"}]))
        async with db.async_session() as s:
            team = (await s.exec(
                select(Team).options(selectinload(Team.heroes).selectinload(Hero.powers))
            )).one()
            assert sorted(h.name for h in team.heroes) == ["Groot", "Rocket"]
            groot = next(h for h in team.heroes if h.name == "Groot")
            assert groot.powers[0].name == "grow"
            assert (await s.exec(select(func.count()).select_from(Hero))).one() == 2
            names = (await s.exec(select(Hero.name).order_by(Hero.name))).all()
            assert names == ["Groot", "Rocket"]
        with pytest.raises(ValidationError):
            async with db.async_session() as s:
                s.add(Hero(name=""))
        await db.dispose()
    run(main())


def test_async_session_directly():
    async def main():
        engine = create_async_engine("sqlite+aiosqlite://")
        async with engine.begin() as conn:
            await conn.run_sync(SQLFuse.metadata.create_all)
        async with AsyncSession(engine, expire_on_commit=False) as s:
            h = Hero(name="Thor", age=1500)
            s.add(h)
            await s.commit()
            got = await s.get(Hero, h.id)
            got.age = 1501
            await s.commit()
            assert (await s.exec(select(Hero).where(Hero.age > 1000))).one().age == 1501
        await engine.dispose()
    run(main())


def test_sync_api_rejected_on_async_db():
    db = Database("sqlite+aiosqlite://")
    with pytest.raises(RuntimeError):
        db.create_all()
