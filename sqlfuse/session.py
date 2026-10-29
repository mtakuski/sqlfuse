"""Sync / async sessions with SQLModel-style ``exec()`` and a small Database facade."""
from __future__ import annotations

from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from typing import Any, TypeVar, overload

import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.engine import Engine, Result, ScalarResult
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.ext.asyncio import AsyncSession as _SAAsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine as _sa_create_async_engine
from sqlalchemy.orm import Session as _SASession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.sql import Select

from .main import SQLBase

_T = TypeVar("_T")

ASYNC_DRIVERS = ("+asyncpg", "+aiosqlite", "+aiomysql", "+asyncmy", "+psycopg_async")


def _single_entity(statement: Any) -> bool:
    return isinstance(statement, Select) and len(statement.column_descriptions) == 1


def _shape(statement: Any, result: Result) -> Any:
    return result.scalars() if _single_entity(statement) else result


class Session(_SASession):
    """SQLAlchemy Session + ``exec()`` returning scalars for single-entity selects."""

    @overload
    def exec(self, statement: Select[tuple[_T]], params: Any = ..., **kw: Any) -> ScalarResult[_T]: ...
    @overload
    def exec(self, statement: Any, params: Any = ..., **kw: Any) -> Result[Any]: ...

    def exec(self, statement: Any, params: Any = None, **kw: Any) -> Any:
        return _shape(statement, self.execute(statement, params, **kw))


class AsyncSession(_SAAsyncSession):
    """Async session; ``await session.exec(select(Hero))`` returns a ScalarResult."""

    sync_session_class = Session

    async def exec(self, statement: Any, params: Any = None, **kw: Any) -> Any:
        return _shape(statement, await self.execute(statement, params, **kw))


def _sqlite_fk_pragma(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _on_connect(dbapi_conn: Any, _record: Any) -> None:  # pragma: no cover - trivial
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()


def create_engine(url: str, **kwargs: Any) -> Engine:
    """``sqlalchemy.create_engine`` + SQLite foreign-key enforcement."""
    engine = sa.create_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        _sqlite_fk_pragma(engine)
    return engine


def create_async_engine(url: str, **kwargs: Any) -> AsyncEngine:
    """``sqlalchemy.ext.asyncio.create_async_engine`` + SQLite foreign-key enforcement."""
    engine = _sa_create_async_engine(url, **kwargs)
    if engine.dialect.name == "sqlite":
        _sqlite_fk_pragma(engine.sync_engine)
    return engine


def is_async_url(url: str | sa.URL) -> bool:
    return any(d in str(url).split("://", 1)[0] for d in ASYNC_DRIVERS)


class Database:
    """Engine + session factory for one database URL (sync or async driver).

    >>> db = Database("sqlite:///app.db")              # sync
    >>> db = Database("postgresql+asyncpg://u:p@h/db")  # async
    """

    def __init__(self, url: str, *, echo: bool = False, metadata: sa.MetaData | None = None,
                 **engine_kwargs: Any):
        self.url = url
        self.metadata = metadata or SQLBase.metadata
        self.is_async = is_async_url(url)
        if self.is_async:
            self.engine: Engine | AsyncEngine = create_async_engine(url, echo=echo, **engine_kwargs)
            self._async_factory = async_sessionmaker(self.engine, class_=AsyncSession,
                                                     expire_on_commit=False)
        else:
            self.engine = create_engine(url, echo=echo, **engine_kwargs)
            self._factory = sessionmaker(self.engine, class_=Session, expire_on_commit=False)

    # ---- sync
    @contextmanager
    def session(self) -> Iterator[Session]:
        """Transactional scope: commits on success, rolls back on error."""
        self._require(False)
        with self._factory() as session:
            try:
                yield session
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def create_all(self) -> None:
        self._require(False)
        self.metadata.create_all(self.engine)

    def drop_all(self) -> None:
        self._require(False)
        self.metadata.drop_all(self.engine)

    # ---- async
    @asynccontextmanager
    async def async_session(self) -> AsyncIterator[AsyncSession]:
        self._require(True)
        async with self._async_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    async def acreate_all(self) -> None:
        self._require(True)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.create_all)

    async def adrop_all(self) -> None:
        self._require(True)
        async with self.engine.begin() as conn:
            await conn.run_sync(self.metadata.drop_all)

    async def dispose(self) -> None:
        if self.is_async:
            await self.engine.dispose()
        else:
            self.engine.dispose()

    def _require(self, is_async: bool) -> None:
        if self.is_async != is_async:
            kind = "an async" if is_async else "a sync"
            raise RuntimeError(f"This operation needs {kind} driver URL (got {self.url!r})")
