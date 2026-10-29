"""Table-model API, declaration options and edge cases."""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import ClassVar

import pytest
import sqlalchemy as sa
from pydantic import Field as PydanticField
from sqlalchemy.orm import relationship as sa_relationship

from sqlfuse import Field, Relationship, Session, SQLFuse, ValidationError, create_engine, select
from sqlfuse.fields import OrmField
from sqlfuse.main import SQLFuseMeta
from tests.models import Hero, HeroCreate, Tag, Team


# ---- models exercising declaration options ----------------------------------
class Greeter:
    """Plain (non-pydantic) mixin."""

    def greet(self) -> str:
        return f"hi {self.name}"


class ApiOwner(Greeter, SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = PydanticField(min_length=2)                # plain pydantic Field
    kind: str = Field(default="person", server_default="'person'")
    version: int = Field(default=1, onupdate=sa.text("version + 1"))
    note: str | None = Field(default=None, sa_column=sa.Column(sa.Text, nullable=True))
    body: str | None = Field(default=None, sa_type=sa.Text)
    counter: ClassVar[int] = 0
    _private: int = 0
    pets: list[ApiPet] = Relationship(back_populates="owner", passive_deletes=True)
    pets_view: list[ApiPet] = Relationship(
        sa_relationship=sa_relationship("ApiPet", viewonly=True)
    )

    def __repr__(self) -> str:                             # uses super() -> __classcell__
        return "Owner:" + super().__repr__()


class ApiPet(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str
    owner_id: int | None = Field(default=None, foreign_key="apiowner.id", ondelete="CASCADE")
    owner: ApiOwner | None = Relationship(back_populates="pets")
    clubs: list[ApiClub] = Relationship(back_populates="pets", link_model="ApiPetClubLink")


class ApiPetClubLink(SQLFuse, table=True):
    pet_id: int | None = Field(default=None, foreign_key="apipet.id", primary_key=True)
    club_id: int | None = Field(default=None, foreign_key="apiclub.id", primary_key=True)


class ApiClub(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    pets: list[ApiPet] = Relationship(back_populates="clubs", link_model="ApiPetClubLink")


class LooseNote(SQLFuse, table=True):
    model_config = {"validate_assignment": False}
    id: int | None = Field(default=None, primary_key=True)
    text: str = Field(min_length=3)


@pytest.fixture
def db():
    engine = create_engine("sqlite://")
    SQLFuse.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


# ---- declaration ------------------------------------------------------------
def test_declaration_options(db):
    table = ApiOwner.__table__
    assert "kind" in table.c and table.c.kind.server_default is not None
    assert table.c.version.onupdate is not None
    assert isinstance(table.c.note.type, sa.Text) and isinstance(table.c.body.type, sa.Text)
    assert "counter" not in table.c and "_private" not in table.c
    assert ApiPet.__mapper__.relationships["owner"].back_populates == "pets"
    assert ApiOwner.__mapper__.relationships["pets"].passive_deletes
    assert ApiOwner.__mapper__.relationships["pets_view"].viewonly

    owner = ApiOwner(name="Ann", pets=[{"name": "Rex", "clubs": [{"title": "Dogs"}]}])
    assert owner.greet() == "hi Ann"
    assert repr(owner).startswith("Owner:ApiOwner(")
    db.add(owner)
    db.commit()
    db.refresh(owner)
    assert owner.kind == "person"                          # server default applied
    assert db.exec(select(ApiClub)).one().pets[0].name == "Rex"
    with pytest.raises(ValidationError):
        ApiOwner(name="A")


def test_declaration_errors():
    with pytest.raises(TypeError, match="not supported"):
        class SubHero(Hero, table=True):
            extra: int = 0

    with pytest.raises(TypeError, match="cannot resolve annotation"):
        class BadRef(SQLFuse, table=True):
            id: int | None = Field(default=None, primary_key=True)
            team: NotDefinedAnywhere | None = None  # noqa: F821

    with pytest.raises(TypeError, match="cannot infer relationship target"):
        class BadRel(SQLFuse, table=True):
            id: int | None = Field(default=None, primary_key=True)
            thing: int | str = Relationship()

    with pytest.raises(TypeError, match="Duplicate table model name"):
        SQLFuseMeta("Hero", (SQLFuse,), {
            "__module__": "somewhere.else", "__tablename__": "hero_dup",
            "__annotations__": {"id": "int | None"},
            "id": Field(default=None, primary_key=True),
        }, table=True)


def test_field_helpers():
    f = Field(5)
    assert isinstance(f, OrmField) and f.default == 5
    with pytest.raises(TypeError):
        Field(1, default_factory=list)


def test_local_forward_refs_in_plain_models():
    marker = 1  # noqa: F841  (non-empty local scope triggers the local rebuild path)

    class NodeA(SQLFuse):
        child: NodeB | None = None

    class NodeB(SQLFuse):
        value: int

    NodeA.model_rebuild()
    assert NodeA(child={"value": 1}).child.value == 1


def test_subclass_checks():
    assert not issubclass(int, SQLFuse)
    assert issubclass(Hero, SQLFuse)
    assert not isinstance(1, SQLFuse)


# ---- pydantic-like API ------------------------------------------------------
def test_model_validate_sources():
    from_obj = Hero.model_validate(SimpleNamespace(name="Obj", age=3, unrelated=1))
    assert (from_obj.name, from_obj.age) == ("Obj", 3)
    copy = Hero.model_validate(from_obj)
    assert copy is not from_obj and copy.name == "Obj"
    assert Hero.model_validate_json(json.dumps({"name": "J"})).name == "J"
    assert set(Hero.model_fields()) == {"id", "name", "age", "team_id"}


def test_model_update_paths():
    hero = Hero(name="Tony")
    hero.model_update({"powers": [{"name": "flight"}], "unknown": 1})
    assert hero.powers[0].name == "flight"
    with pytest.raises(ValidationError) as ei:
        hero.model_update({"powers": [{"name": "x"}]})
    assert ei.value.errors()[0]["loc"] == ("powers", 0, "name")

    note = LooseNote(text="long enough")
    note.text = "no"                                       # validate_assignment disabled
    note.model_update({"text": "ok"})
    assert note.text == "ok"


def test_dump_variants():
    team = Team(name="Avengers")
    hero = Hero(name="Tony", team=team)
    dumped = hero.model_dump()
    assert dumped["team"]["name"] == "Avengers"            # many-to-one dumped
    lone = Hero(name="Solo")
    lone.team = None
    assert lone.model_dump()["team"] is None
    assert "team" not in lone.model_dump(exclude_none=True)
    assert json.loads(hero.model_dump_json())["name"] == "Tony"
    assert "team" not in hero.model_dump(relationships=False)
    assert hero.model_dump(include={"name"}) == {"name": "Tony"}


def test_mapping_view():
    hero = Hero(name="Tony", age=40)
    assert hero["name"] == "Tony" and hero.get("age") == 40
    assert hero.get("nope", "dflt") == "dflt"
    with pytest.raises(KeyError):
        hero["nope"]
    assert "name" in hero and "nope" not in hero
    assert dict(hero)["name"] == "Tony"
    assert ("age", 40) in hero.items() and "name" in hero.keys()


def test_relationship_coercion_errors():
    with pytest.raises(ValidationError) as ei:
        Team(name="ok", heroes=None)
    assert ei.value.errors()[0]["type"] == "list_type"
    with pytest.raises(ValidationError):
        Team(name="ok", heroes=[Tag(label="wrong")])
    with pytest.raises(ValidationError):
        Team(name="ok", heroes={"name": "not a list"})
    team = Team(name="ok", heroes=[HeroCreate(name="FromSchema")])  # pydantic model coerced
    assert team.heroes[0].name == "FromSchema"
    assert Hero(name="x", team=None).team is None


def test_plain_subclass_of_table_model_rejected():
    with pytest.raises(TypeError, match="not supported"):
        class SubHeroPlain(Hero):
            pass


def test_unknown_relationship_target():
    from sqlfuse.main import RelInfo

    with pytest.raises(LookupError, match="Nope"):
        RelInfo("Nope", False, False).target


class WithIdBase(SQLFuse):
    id: int | None = Field(default=None, primary_key=True)
    label: str = Field(max_length=20)


class InheritsEverything(WithIdBase, table=True):
    pass


def test_table_model_with_only_inherited_fields():
    assert set(InheritsEverything.__table__.c.keys()) == {"id", "label"}
    assert InheritsEverything(label="x").label == "x"
