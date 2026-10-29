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
