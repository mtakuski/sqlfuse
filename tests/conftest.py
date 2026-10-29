import pytest

from sqlfuse import SQLFuse, Session, create_engine


@pytest.fixture
def engine():
    eng = create_engine("sqlite://")
    SQLFuse.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s
