# SQLFuse Architecture

SQLFuse is an ORM: one class definition gives you a Pydantic-validated model **and**
a SQLAlchemy 2.x mapped table. Validation is *always* applied to `table=True`
models. It runs on construction, on attribute assignment, and recursively on nested
relationship data.

## Core idea: one declaration, two compiled artefacts

```
                    class Hero(SQLFuse, table=True): ...
                                   │
                             SQLFuseMeta.__new__
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
     Pydantic validator model             SQLAlchemy mapped class
     (Hero.__validator__)                 (Hero, subclass of SQLBase)
     - field types + constraints          - Column() per scalar field
     - @field_validator / @model_validator - relationship() per Relationship()
     - nested relationship coercion        - secondary= for many-to-many
                    │                             │
                    └────── Hero.__init__ ────────┘
                 validate(data) → set attributes on mapped instance
```

* `table=False` (default) → the class *is* a normal Pydantic `BaseModel`
  (with `from_attributes=True`). Use it for schemas (Create/Read/Update) and
  as a base class that table models inherit fields from.
* `table=True` → `SQLFuseMeta` returns a real SQLAlchemy declarative class
  (no Pydantic in its MRO, so no `__dict__`/instrumentation conflicts). A
  hidden Pydantic model (`__validator__`) is generated from the same fields and
  inherits fields + validators from Pydantic base classes.

This split is what lets validation work with `table=True`: SQLAlchemy owns the
instance state, Pydantic owns the rules, and `__init__`/`__setattr__` bridge them.

## Modules

| Module | Responsibility |
|---|---|
| `sqlfuse/fields.py` | `Field()` (Pydantic constraints + column options), `Relationship()` |
| `sqlfuse/typing_utils.py` | Lazy annotation evaluation (forward refs, `X \| None`, `list["Hero"]`) |
| `sqlfuse/sqltypes.py` | Python type → SQLAlchemy type mapping; `PydanticJSON` for nested models |
| `sqlfuse/main.py` | `SQLBase`, `SQLFuseMeta`, `SQLFuse`, `TableModel` mixin (validation, dump) |
| `sqlfuse/session.py` | `Session` / `AsyncSession` with `.exec()`; engine helpers |
| `sqlfuse/migrations.py` | Alembic integration (programmatic, no `alembic.ini` needed) + `sync_schema()` |

## Validation pipeline (`table=True`)

1. `Hero(**data)` → `Hero.__validator__.model_validate(data)`.
2. Scalar fields: full Pydantic validation (types, `min_length`, `ge`, regex,
   custom validators, `model_validator`s).
3. Relationship fields: a `BeforeValidator` resolves the target class from the
   registry and coerces `dict → Target(**dict)` (recursively validated),
   accepts `Target` instances, and rejects anything else. Lists for
   one-to-many / many-to-many, single values for many-to-one.
4. Only explicitly passed relationships are assigned (so `team_id=1` is not
   clobbered by an implicit `team=None`).
5. `hero.name = ""` → `__setattr__` re-runs field validation
   (`validate_assignment`), unless the class sets `model_config = {"validate_assignment": False}`.
6. Rows loaded from the DB bypass `__init__`/`__setattr__` (SQLAlchemy writes
   to instance state directly), so loading is fast and never fails on legacy data.

## Nested models

* **Nested relations**: `Team(heroes=[{"name": "A", "powers": [{...}]}])`
  builds the full object graph with validation at every level; errors carry
  the nested path (`heroes.0.powers.0.name`).
* **Nested value objects**: a field typed with a non-table `SQLFuse`
  (or `list[SQLFuse]`, `dict`, …) is stored in a `JSON` column via
  `PydanticJSON`, validated on input and re-hydrated into the Pydantic type on load.

## Relationships

| Kind | Declaration |
|---|---|
| many-to-one | `team_id: int \| None = Field(foreign_key="team.id")` + `team: "Team \| None" = Relationship(back_populates="heroes")` |
| one-to-many | `heroes: list["Hero"] = Relationship(back_populates="team")` |
| many-to-many | `tags: list["Tag"] = Relationship(link_model=HeroTagLink, back_populates="heroes")` |
| self-referential / custom | `Relationship(sa_relationship_kwargs={...})` |

`uselist` and the target class are derived from the annotation.

## Sync & async

Same models for both. `Session.exec(stmt)` / `await AsyncSession.exec(stmt)`
return scalars for single-entity selects and normal results otherwise. Async
uses SQLAlchemy's asyncio extension; use `selectinload()` (re-exported) for
relationships, or `Relationship(lazy="selectin")`.

## Databases

Dialect-neutral type mapping (`str` → `VARCHAR(max_length or 255)` so MySQL
indexes/uniques work, `JSON`, `Uuid`, `Enum`, `Numeric(max_digits, decimal_places)`).

| DB | Sync URL | Async URL |
|---|---|---|
| PostgreSQL | `postgresql+psycopg://` | `postgresql+asyncpg://` |
| SQLite | `sqlite:///file.db` | `sqlite+aiosqlite:///file.db` |
| MySQL | `mysql+pymysql://` | `mysql+aiomysql://` |

## Migrations

* `sqlfuse.migrations.Migrator(url, models_module, directory)` wraps Alembic:
  `init()`, `revision(message, autogenerate=True)`, `upgrade()`, `downgrade()`,
  `current()`, `history()`. `env.py` is generated with
  `target_metadata = SQLFuse.metadata`, `compare_type=True`, and
  `render_as_batch` for SQLite. Async URLs are converted to sync drivers for
  migrations automatically.
* CLI: `python -m sqlfuse.migrations --url ... --models app.models revision -m "msg"`.
* `sync_schema(engine)`: a dev helper that creates missing tables and adds missing
  columns, never drops anything.
