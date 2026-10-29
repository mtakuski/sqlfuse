import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from sqlfuse import Session, create_engine  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402
from tests.models import Hero, SQLFuse  # noqa: E402


def test_table_model_as_request_body_and_response():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLFuse.metadata.create_all(engine)
    app = fastapi.FastAPI()

    @app.post("/heroes")
    def create(hero: Hero) -> Hero:
        with Session(engine, expire_on_commit=False) as s:
            s.add(hero)
            s.commit()
        return hero

    c = TestClient(app)
    r = c.post("/heroes", json={"name": " Tony ", "age": 48})
    assert r.status_code == 200 and r.json()["name"] == "Tony" and r.json()["id"] == 1
    r = c.post("/heroes", json={"name": "", "agee": 1})
    assert r.status_code == 422
    assert [e["loc"] for e in r.json()["detail"]] == [["body", "name"]]
    assert c.get("/openapi.json").status_code == 200


def test_body_with_alias_and_nested_relationships():
    from pydantic import TypeAdapter

    from sqlfuse import Field, SQLFuse
    from tests.models import Team

    class Gadget(SQLFuse, table=True):
        id: int | None = Field(default=None, primary_key=True)
        name: str = Field(validation_alias="gadgetName", min_length=2)

    g = TypeAdapter(Gadget).validate_python({"gadgetName": "Phone"})
    assert isinstance(g, Gadget) and g.name == "Phone"
    t = TypeAdapter(Team).validate_python({"name": "Avengers", "heroes": [{"name": "Tony"}]})
    assert t.heroes[0].name == "Tony" and t.heroes[0].team is t
    with pytest.raises(Exception) as ei:
        TypeAdapter(Team).validate_python({"name": "Avengers", "heroes": [{"name": ""}]})
    assert "heroes" in str(ei.value)
