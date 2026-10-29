"""End-to-end example: sync + async, nested relations, validation, migrations.

    pip install -e ".[sqlite]"
    python examples/app.py
"""
from __future__ import annotations

import asyncio

from sqlfuse import (
    Database, Field, SQLFuse, Relationship, ValidationError,
    field_validator, select, selectinload,
)


class Address(SQLFuse):                       # nested value object -> JSON column
    city: str = Field(min_length=2)
    zip_code: str = Field(pattern=r"^\d{2}-\d{3}$")


class StudentCourseLink(SQLFuse, table=True):
    student_id: int | None = Field(default=None, foreign_key="student.id", primary_key=True)
    course_id: int | None = Field(default=None, foreign_key="course.id", primary_key=True)


class School(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=3, max_length=80, unique=True)
    address: Address
    students: list[Student] = Relationship(back_populates="school", cascade="all, delete-orphan")


class Student(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+$", unique=True)
    age: int = Field(ge=6, le=120)
    school_id: int | None = Field(default=None, foreign_key="school.id")
    school: School | None = Relationship(back_populates="students")
    courses: list[Course] = Relationship(back_populates="students", link_model=StudentCourseLink)

    @field_validator("email")
    @classmethod
    def lower(cls, v: str) -> str:
        return v.lower()


class Course(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str = Field(min_length=2)
    students: list[Student] = Relationship(back_populates="courses", link_model=StudentCourseLink)


class StudentRead(SQLFuse):                  # API schema
    id: int
    email: str
    courses: list[CourseRead] = []


class CourseRead(SQLFuse):
    id: int
    title: str


StudentRead.model_rebuild()

PAYLOAD = {
    "name": "Liceum nr 1",
    "address": {"city": "Kraków", "zip_code": "30-001"},
    "students": [
        {"email": "ANNA@x.pl", "age": 17, "courses": [{"title": "Math"}, {"title": "Physics"}]},
        {"email": "jan@x.pl", "age": 16},
    ],
}


def sync_demo() -> None:
    db = Database("sqlite:///:memory:")
    db.create_all()
    with db.session() as s:
        s.add(School(**PAYLOAD))           # whole graph validated, then inserted
    with db.session() as s:
        stmt = select(School).options(selectinload(School.students).selectinload(Student.courses))
        school = s.exec(stmt).one()
        print("sync:", school.name, school.address, [st.email for st in school.students])
        print("read schema:", StudentRead.model_validate(school.students[0]).model_dump())
    try:
        School(name="X", address={"city": "K", "zip_code": "bad"}, students=[{"email": "nope", "age": 3}])
    except ValidationError as e:
        print(f"{e.error_count()} errors:", [".".join(map(str, err["loc"])) for err in e.errors()])


async def async_demo() -> None:
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.acreate_all()
    async with db.async_session() as s:
        s.add(School(**PAYLOAD))
    async with db.async_session() as s:
        result = await s.exec(select(Student).options(selectinload(Student.courses)).order_by(Student.email))
        print("async:", [(st.email, [c.title for c in st.courses]) for st in result])
    await db.dispose()


if __name__ == "__main__":
    sync_demo()
    asyncio.run(async_demo())
    # Migrations (Alembic):
    #   from sqlfuse.migrations import Migrator
    #   m = Migrator("postgresql+asyncpg://u:p@localhost/app", "examples.app", "migrations")
    #   m.revision("initial"); m.upgrade()
