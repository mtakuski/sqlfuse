import sqlalchemy as sa

from sqlfuse import SQLFuse
from sqlfuse.migrations import Migrator, sync_schema
import tests.models  # noqa: F401


def test_alembic_autogenerate_upgrade_downgrade(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    url = f"sqlite:///{tmp_path}/m.db"
    m = Migrator(url, "tests.models", tmp_path / "migrations")
    m.init()
    m.revision("initial")
    versions = list((tmp_path / "migrations" / "versions").glob("*.py"))
    assert len(versions) == 1
    src = versions[0].read_text()
    assert "op.create_table('hero'" in src and "sa.JSON()" in src and "sqlfuse" not in src
    m.upgrade()
    engine = sa.create_engine(url)
    tables = set(sa.inspect(engine).get_table_names())
    assert set(SQLFuse.metadata.tables) <= tables
    assert m.current() is not None
    # no changes -> empty second revision
    m.revision("noop")
    newest = max((tmp_path / "migrations" / "versions").glob("*.py"), key=lambda p: p.stat().st_mtime)
    assert "pass" in newest.read_text().split("def upgrade")[1].split("def downgrade")[0]
    m.downgrade("base")
    assert set(sa.inspect(engine).get_table_names()) == {"alembic_version"}
    engine.dispose()


def test_async_url_migrations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    m = Migrator(f"sqlite+aiosqlite:///{tmp_path}/a.db", "tests.models", tmp_path / "mig")
    m.revision("initial")
    m.upgrade()
    engine = sa.create_engine(f"sqlite:///{tmp_path}/a.db")
    assert "hero" in sa.inspect(engine).get_table_names()
    engine.dispose()


def test_sync_schema_adds_missing_tables_and_columns(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path}/s.db")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE team (id INTEGER PRIMARY KEY, name VARCHAR(50) NOT NULL)"))
    applied = sync_schema(engine)
    assert any("ADD COLUMN headquarters" in s for s in applied)
    assert "CREATE TABLE hero" in applied
    assert sync_schema(engine) == []
    engine.dispose()


def test_migrator_extras(tmp_path, monkeypatch, capsys):
    import pytest
    from sqlfuse.migrations import main

    monkeypatch.chdir(tmp_path)
    url = f"sqlite:///{tmp_path}/c.db"
    args = ["--url", url, "--models", "tests.models", "--dir", str(tmp_path / "mig")]
    main(args + ["init"])
    main(args + ["init"])                                   # idempotent
    main(args + ["revision", "-m", "first"])
    main(args + ["revision", "-m", "empty", "--empty"])
    main(args + ["upgrade"])
    main(args + ["current"])
    assert capsys.readouterr().out.strip().splitlines()[-1] != "None"
    main(args + ["history"])
    assert "empty" in capsys.readouterr().out
    main(args + ["downgrade", "base"])
    m = Migrator(url, "tests.models", tmp_path / "mig")
    m.stamp("head")
    assert m.current() is not None
    assert len(m.history()) == 2
    with pytest.raises(RuntimeError):
        Migrator("sqlite+aiosqlite:///x.db").current()
    monkeypatch.delenv("SQLFUSE_DATABASE_URL", raising=False)
    with pytest.raises(SystemExit):
        main(["init"])


def test_sync_schema_refuses_not_null_without_default(tmp_path):
    import pytest

    engine = sa.create_engine(f"sqlite:///{tmp_path}/n.db")
    meta = sa.MetaData()
    sa.Table("things", meta, sa.Column("id", sa.Integer, primary_key=True))
    meta.create_all(engine)
    meta2 = sa.MetaData()
    sa.Table("things", meta2, sa.Column("id", sa.Integer, primary_key=True),
             sa.Column("name", sa.String(10), nullable=False))
    with pytest.raises(RuntimeError, match="NOT NULL"):
        sync_schema(engine, meta2)
    engine.dispose()


def test_async_sync_schema(tmp_path):
    import asyncio

    from sqlfuse import create_async_engine
    from sqlfuse.migrations import async_sync_schema

    async def main():
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/as.db")
        applied = await async_sync_schema(engine)
        assert "CREATE TABLE hero" in applied
        await engine.dispose()

    asyncio.run(main())
