import pytest
import sqlalchemy as sa

from sqlfuse import Session, ValidationError, delete, func, select, selectinload, update
from tests.models import Category, Customer, Hero, HeroTagLink, Power, Tag, Team, TeamRead


def seed(session):
    team = Team(name="Avengers", heroes=[
        {"name": "Tony", "age": 48, "powers": [{"name": "suit", "level": 9}, {"name": "money", "level": 10}],
         "tags": [{"label": "rich"}, {"label": "genius"}]},
        {"name": "Steve", "age": 100, "powers": [{"name": "shield"}]},
    ])
    session.add(team)
    session.commit()
    return team


def test_crud(session):
    h = Hero(name="Peter", age=16)
    session.add(h)
    session.commit()
    assert h.id is not None
    got = session.get(Hero, h.id)
    got.age = 17
    session.commit()
    assert session.exec(select(Hero).where(Hero.name == "Peter")).one().age == 17
    session.delete(got)
    session.commit()
    assert session.exec(select(func.count()).select_from(Hero)).one() == 0


def test_exec_shapes(session):
    seed(session)
    assert [h.name for h in session.exec(select(Hero).order_by(Hero.name))] == ["Steve", "Tony"]
    assert session.exec(select(Hero.name).order_by(Hero.name)).all() == ["Steve", "Tony"]
    rows = session.exec(select(Hero.name, Team.name).join(Team).order_by(Hero.name)).all()
    assert rows == [("Steve", "Avengers"), ("Tony", "Avengers")]
    session.exec(update(Hero).where(Hero.name == "Steve").values(age=101))
    assert session.exec(select(Hero.age).where(Hero.name == "Steve")).one() == 101


def test_one_to_many_and_nested_eager(session):
    seed(session)
    session.expunge_all()
    team = session.exec(
        select(Team).options(selectinload(Team.heroes).selectinload(Hero.powers))
    ).one()
    tony = next(h for h in team.heroes if h.name == "Tony")
    assert sorted(p.name for p in tony.powers) == ["money", "suit"]
    dumped = team.model_dump()
    assert dumped["name"] == "Avengers"
    assert {h["name"] for h in dumped["heroes"]} == {"Tony", "Steve"}
    assert "team" not in dumped["heroes"][0]  # cycle avoided
    read = TeamRead.model_validate(team)       # pydantic schema from ORM object (nested)
    assert {p.name for h in read.heroes for p in h.powers} == {"suit", "money", "shield"}


def test_many_to_many(session):
    seed(session)
    rich = session.exec(select(Tag).where(Tag.label == "rich")).one()
    assert [h.name for h in rich.heroes] == ["Tony"]
    steve = session.exec(select(Hero).where(Hero.name == "Steve")).one()
    steve.tags.append(rich)
    session.commit()
    assert sorted(h.name for h in rich.heroes) == ["Steve", "Tony"]
    assert session.exec(select(func.count()).select_from(HeroTagLink)).one() == 3
    q = select(Hero).join(Hero.tags).where(Tag.label == "rich").order_by(Hero.name)
    assert [h.name for h in session.exec(q)] == ["Steve", "Tony"]


def test_cascade_delete(session):
    team = seed(session)
    session.delete(team)
    session.commit()
    assert session.exec(select(func.count()).select_from(Hero)).one() == 0
    assert session.exec(select(func.count()).select_from(Power)).one() == 0
    assert session.exec(select(func.count()).select_from(HeroTagLink)).one() == 0
    assert session.exec(select(func.count()).select_from(Tag)).one() == 2


def test_self_referential_tree(session):
    root = Category(name="root", children=[{"name": "a", "children": [{"name": "a1"}]}, {"name": "b"}])
    session.add(root)
    session.commit()
    session.expunge_all()
    root = session.exec(select(Category).where(Category.parent_id.is_(None))).one()
    assert sorted(c.name for c in root.children) == ["a", "b"]
    a = next(c for c in root.children if c.name == "a")
    assert a.children[0].name == "a1" and a.children[0].parent.name == "a"


def test_json_roundtrip(session):
    c = Customer(email="a@b.pl", address={"street": "s", "city": "c", "zip_code": "00-001"},
                 shipping=[{"street": "x", "city": "y", "zip_code": "11-111"}], balance="12.34")
    session.add(c)
    session.commit()
    session.expunge_all()
    got = session.exec(select(Customer)).one()
    assert got.address.city == "c" and got.shipping[0].zip_code == "11-111"
    assert type(got.address).__name__ == "Address"
    assert str(got.balance) == "12.34" and got.status.value == "active"
    assert got.model_dump(mode="json")["address"] == {"street": "s", "city": "c", "zip_code": "00-001"}


def test_db_constraints_enforced(session):
    session.add(Tag(label="x"))
    session.commit()
    session.add(Tag(label="x"))
    with pytest.raises(sa.exc.IntegrityError):
        session.commit()
    session.rollback()
    session.add(Hero(name="Ghost", team_id=999))      # FK enforced on SQLite via PRAGMA
    with pytest.raises(sa.exc.IntegrityError):
        session.commit()


def test_loaded_rows_skip_validation(session):
    session.exec(sa.text("INSERT INTO hero (name, age) VALUES ('', -1)"))
    h = session.exec(select(Hero)).one()     # legacy/invalid rows still load
    assert h.name == "" and h.age == -1
    with pytest.raises(ValidationError):
        h.age = -2


def test_bulk_delete(session):
    seed(session)
    session.exec(delete(Power).where(Power.level < 5))
    assert session.exec(select(Power.name).order_by(Power.name)).all() == ["money", "suit"]
