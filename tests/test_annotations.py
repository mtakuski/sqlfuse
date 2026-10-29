"""Models declared WITHOUT `from __future__ import annotations` (string forward refs)."""
from typing import List, Optional

from sqlfuse import Field, SQLFuse, Relationship, Session, create_engine, select


class Author(SQLFuse, table=True):
    __tablename__ = "authors"
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str = Field(min_length=1)
    books: List["Book"] = Relationship(back_populates="author")


class Book(SQLFuse, table=True):
    __tablename__ = "books"
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    author_id: Optional[int] = Field(default=None, foreign_key="authors.id")
    author: Optional["Author"] = Relationship(back_populates="books")


def test_typing_style_annotations():
    engine = create_engine("sqlite://")
    SQLFuse.metadata.create_all(engine, tables=[Author.__table__, Book.__table__])
    with Session(engine) as s:
        s.add(Author(name="Lem", books=[{"title": "Solaris"}, {"title": "Golem XIV"}]))
        s.commit()
        book = s.exec(select(Book).where(Book.title == "Solaris")).one()
        assert book.author.name == "Lem"
        assert Book.__table__.c.author_id.nullable


def test_locally_defined_models():
    class LocalNote(SQLFuse, table=True):
        id: int | None = Field(default=None, primary_key=True)
        text: str = Field(max_length=10)
        parent_id: int | None = Field(default=None, foreign_key="localnote.id")
        replies: list["LocalNote"] = Relationship(
            sa_relationship_kwargs={"remote_side": "LocalNote.parent_id", "viewonly": False}
        )

    n = LocalNote(text="hi", replies=[{"text": "re"}])
    assert n.replies[0].text == "re"
    assert str(LocalNote.__table__.c.text.type) == "VARCHAR(10)"
