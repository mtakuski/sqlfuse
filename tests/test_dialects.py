import pytest
from sqlalchemy.dialects import mysql, postgresql, sqlite
from sqlalchemy.schema import CreateIndex, CreateTable

from sqlfuse import SQLFuse
import tests.models  # noqa: F401


@pytest.mark.parametrize("dialect", [postgresql.dialect(), mysql.dialect(), sqlite.dialect()],
                         ids=["postgresql", "mysql", "sqlite"])
def test_ddl_compiles(dialect):
    for table in SQLFuse.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=dialect))
        assert table.name in ddl
        for idx in table.indexes:
            str(CreateIndex(idx).compile(dialect=dialect))


def test_type_mapping():
    cust = SQLFuse.metadata.tables["customer"]
    pg = postgresql.dialect()
    assert str(cust.c.email.type.compile(pg)) == "VARCHAR(120)"
    assert str(cust.c.balance.type.compile(pg)) == "NUMERIC(10, 2)"
    assert str(cust.c.uid.type.compile(pg)) == "UUID"
    assert str(cust.c.address.type.compile(pg)) == "JSON"
    assert cust.c.address.nullable and not cust.c.email.nullable
    hero = SQLFuse.metadata.tables["hero"]
    assert str(hero.c.name.type.compile(mysql.dialect())) == "VARCHAR(100)"
    fk = next(iter(hero.c.team_id.foreign_keys))
    assert fk.target_fullname == "team.id" and fk.ondelete == "CASCADE"
    assert SQLFuse.metadata.tables["team"].c.name.index
