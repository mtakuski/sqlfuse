import uuid
from decimal import Decimal

import pytest

from sqlfuse import SQLFuse, ValidationError
from tests.models import Address, Customer, Hero, HeroBase, HeroCreate, HeroUpdate, Power, Status, Tag, Team


def locs(exc: ValidationError):
    return {tuple(e["loc"]) for e in exc.errors()}


def test_table_model_validates_on_init():
    with pytest.raises(ValidationError) as ei:
        Hero(name="", age=-1)
    assert locs(ei.value) == {("name",), ("age",)}


def test_missing_required_field():
    with pytest.raises(ValidationError) as ei:
        Hero(age=3)
    assert ei.value.errors()[0]["type"] == "missing"


def test_coercion_and_field_validator():
    h = Hero(name="  Tony  ", age="42")
    assert h.name == "Tony" and h.age == 42


def test_model_validator_runs_for_table_models():
    with pytest.raises(ValidationError, match="villains must be adults"):
        Hero(name="Villain X", age=10)


def test_validate_assignment():
    h = Hero(name="Tony", age=40)
    with pytest.raises(ValidationError):
        h.age = -5
    with pytest.raises(ValidationError):
        h.name = "   "
    h.age = "41"
    assert h.age == 41


def test_model_validator_on_assignment():
    h = Hero(name="Villain", age=30)
    with pytest.raises(ValidationError):
        h.age = 5


def test_nested_relationship_validation_paths():
    with pytest.raises(ValidationError) as ei:
        Team(name="ok", heroes=[{"name": "A"}, {"name": "", "powers": [{"name": "x", "level": 99}]}, 5])
    assert locs(ei.value) == {
        ("heroes", 1, "name"),
        ("heroes", 1, "powers", 0, "name"),
        ("heroes", 1, "powers", 0, "level"),
        ("heroes", 2),
    }


def test_nested_relationship_builds_graph():
    t = Team(name="Avengers", heroes=[
        {"name": "Tony", "powers": [{"name": "suit", "level": 9}], "tags": [{"label": "rich"}]},
        Hero(name="Steve"),
    ])
    assert [h.name for h in t.heroes] == ["Tony", "Steve"]
    assert t.heroes[0].team is t                       # back_populates in memory
    assert t.heroes[0].powers[0].hero is t.heroes[0]
    assert t.heroes[0].tags[0].heroes == [t.heroes[0]]


def test_many_to_one_from_dict_and_wrong_type():
    h = Hero(name="Bucky", team={"name": "Winter"})
    assert isinstance(h.team, Team) and h.team.heroes == [h]
    with pytest.raises(ValidationError):
        Hero(name="Bucky", team=Tag(label="x"))
    with pytest.raises(ValidationError):
        Hero(name="Bucky", team={"name": "x"})          # team name too short


def test_relationship_assignment_is_validated():
    h = Hero(name="Tony")
    h.powers = [{"name": "flight"}]
    assert isinstance(h.powers[0], Power)
    with pytest.raises(ValidationError):
        h.powers = [{"name": "f"}]
    with pytest.raises(ValidationError):
        h.powers = "nope"


def test_explicit_fk_not_clobbered_by_relationship_default():
    h = Hero(name="Tony", team_id=7)
    assert h.team_id == 7 and h.team is None


def test_nested_pydantic_json_fields():
    c = Customer(email="a@b.pl", address={"street": "Długa 1", "city": "Gdańsk", "zip_code": "80-001"},
                 shipping=[{"street": "x", "city": "y", "zip_code": "00-000"}], balance="10.50")
    assert isinstance(c.address, Address) and isinstance(c.shipping[0], Address)
    assert c.balance == Decimal("10.50") and c.status is Status.active
    assert isinstance(c.uid, uuid.UUID)
    with pytest.raises(ValidationError) as ei:
        Customer(email="bad", address={"street": "", "city": "c", "zip_code": "1"}, status="nope")
    assert {("email",), ("address", "street"), ("address", "zip_code"), ("status",)} <= locs(ei.value)


def test_model_validate_from_schema_and_update():
    h = Hero.model_validate(HeroCreate(name="Tony", age=40), update={"age": 41})
    assert (h.name, h.age) == ("Tony", 41)
    h.model_update(HeroUpdate(age=50))
    assert (h.name, h.age) == ("Tony", 50)
    with pytest.raises(ValidationError):
        h.model_update({"age": -1, "name": ""})
    assert h.age == 50                                   # unchanged on failure


def test_isinstance_and_schema():
    h = Hero(name="Tony")
    assert isinstance(h, SQLFuse) and isinstance(h, HeroBase) and issubclass(Hero, HeroBase)
    assert not isinstance(h, HeroCreate)
    schema = Hero.model_json_schema()
    assert schema["title"] == "Hero" and schema["properties"]["name"]["minLength"] == 1
    assert h.describe() == "Tony (None)"


def test_non_table_models_are_pydantic():
    with pytest.raises(ValidationError):
        Address(street="", city="c", zip_code="00-000")


def test_relationship_on_non_table_model_rejected():
    from sqlfuse import Relationship
    with pytest.raises(TypeError):
        class Bad(SQLFuse):
            x: list = Relationship()


def test_email_str_field():
    pytest.importorskip("email_validator")
    from pydantic import EmailStr
    from sqlfuse import Field, SQLFuse

    class Account(SQLFuse, table=True):
        id: int | None = Field(default=None, primary_key=True)
        email: EmailStr = Field(max_length=255, unique=True)

    assert Account(email="anna@example.com").email == "anna@example.com"
    assert str(Account.__table__.c.email.type) == "VARCHAR(255)"
    with pytest.raises(ValidationError) as ei:
        Account(email="nope")
    assert ei.value.errors()[0]["loc"] == ("email",)


def test_field_accepts_every_pydantic_option():
    import inspect

    from pydantic import AliasChoices
    from pydantic import Field as PydanticField

    from sqlfuse import Field, SQLFuse
    from sqlfuse.fields import _PYDANTIC_FIELD_PARAMS

    sqlfuse_params = set(inspect.signature(Field).parameters)
    assert _PYDANTIC_FIELD_PARAMS <= sqlfuse_params
    assert set(inspect.signature(PydanticField).parameters) - {"extra"} <= sqlfuse_params

    class Product(SQLFuse, table=True):
        id: int | None = Field(default=None, primary_key=True)
        name: str = Field(validation_alias=AliasChoices("name", "productName"), description="Name",
                          examples=["Pen"], max_length=40)
        code: str = Field(coerce_numbers_to_str=True, frozen=False)
        price: float = Field(allow_inf_nan=False, gt=0, multiple_of=0.01)
        slug: str = Field(default_factory=lambda data: data["name"].lower())
        secret: str | None = Field(default=None, exclude=True, repr=False)

    p = Product(productName="Pen", code=123, price=1.5)
    assert (p.name, p.code, p.slug) == ("Pen", "123", "pen")
    assert "secret" not in p.model_dump()
    with pytest.raises(ValidationError):
        Product(name="Pen", code="x", price=float("inf"))
    assert Product.model_json_schema()["properties"]["name"]["examples"] == ["Pen"]
