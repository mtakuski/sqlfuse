"""Models shared by the test-suite."""
from __future__ import annotations

import datetime as dt
import enum
import uuid
from decimal import Decimal

from sqlfuse import Field, SQLFuse, Relationship, field_validator, model_validator


# ---- nested (non-table) value objects, stored as JSON -----------------------
class Address(SQLFuse):
    street: str = Field(min_length=1)
    city: str
    zip_code: str = Field(pattern=r"^\d{2}-\d{3}$")


class Status(str, enum.Enum):
    active = "active"
    blocked = "blocked"


class Customer(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    uid: uuid.UUID = Field(default_factory=uuid.uuid4, unique=True)
    email: str = Field(max_length=120, pattern=r"^[^@\s]+@[^@\s]+$", unique=True)
    status: Status = Status.active
    balance: Decimal = Field(default=Decimal("0"), max_digits=10, decimal_places=2, ge=0)
    address: Address | None = None
    shipping: list[Address] = Field(default_factory=list)
    created_at: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))


# ---- one-to-many / many-to-many / nested -----------------------------------
class TeamBase(SQLFuse):
    name: str = Field(min_length=2, max_length=50, index=True)
    headquarters: str | None = None


class Team(TeamBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    heroes: list[Hero] = Relationship(back_populates="team", cascade="all, delete-orphan")


class HeroTagLink(SQLFuse, table=True):
    hero_id: int | None = Field(default=None, foreign_key="hero.id", primary_key=True, ondelete="CASCADE")
    tag_id: int | None = Field(default=None, foreign_key="tag.id", primary_key=True, ondelete="CASCADE")


class HeroBase(SQLFuse):
    name: str = Field(min_length=1, max_length=100)
    age: int | None = Field(default=None, ge=0, le=10_000)


class Hero(HeroBase, table=True):
    id: int | None = Field(default=None, primary_key=True)
    team_id: int | None = Field(default=None, foreign_key="team.id", ondelete="CASCADE")
    team: Team | None = Relationship(back_populates="heroes")
    powers: list[Power] = Relationship(back_populates="hero", cascade="all, delete-orphan")
    tags: list[Tag] = Relationship(back_populates="heroes", link_model=HeroTagLink)

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("name must not be blank")
        return v

    @model_validator(mode="after")
    def villains_are_adults(self):
        if self.name.lower().startswith("villain") and (self.age or 0) < 18:
            raise ValueError("villains must be adults")
        return self

    def describe(self) -> str:
        return f"{self.name} ({self.age})"


class Power(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=2)
    level: int = Field(default=1, ge=1, le=10)
    hero_id: int | None = Field(default=None, foreign_key="hero.id")
    hero: Hero | None = Relationship(back_populates="powers")


class Tag(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    label: str = Field(min_length=1, max_length=30, unique=True)
    heroes: list[Hero] = Relationship(back_populates="tags", link_model=HeroTagLink)


# ---- self-referential tree --------------------------------------------------
class Category(SQLFuse, table=True):
    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(min_length=1)
    parent_id: int | None = Field(default=None, foreign_key="category.id")
    parent: Category | None = Relationship(
        back_populates="children", sa_relationship_kwargs={"remote_side": "Category.id"}
    )
    children: list[Category] = Relationship(back_populates="parent", lazy="selectin")


# ---- API schemas (plain pydantic) -------------------------------------------
class PowerRead(SQLFuse):
    id: int
    name: str
    level: int


class HeroCreate(HeroBase):
    team_id: int | None = None


class HeroUpdate(SQLFuse):
    name: str | None = None
    age: int | None = None


class HeroRead(HeroBase):
    id: int
    powers: list[PowerRead] = []


class TeamRead(TeamBase):
    id: int
    heroes: list[HeroRead] = []
