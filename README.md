<img width="1280" height="384" alt="sqlfuse-banner-wide" src="https://github.com/user-attachments/assets/664b2d96-0c17-4bd8-8138-a78cbad26690" /><br>

[![Tests](https://github.com/mtakuski/sqlfuse/actions/workflows/tests.yml/badge.svg)](https://github.com/mtakuski/sqlfuse/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/sqlfuse)](https://pypi.org/project/sqlfuse/)
![Coverage](https://raw.githubusercontent.com/mtakuski/sqlfuse/badges/coverage.svg)
![Last commit](https://img.shields.io/github/last-commit/mtakuski/sqlfuse)
![Issues](https://img.shields.io/github/issues/mtakuski/sqlfuse)
![Repo size](https://img.shields.io/github/repo-size/mtakuski/sqlfuse)

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/github/license/mtakuski/sqlfuse)
![Pydantic v2](https://img.shields.io/badge/pydantic-v2-E92063)
![SQLAlchemy 2](https://img.shields.io/badge/SQLAlchemy-2.x-D71F00)

# SQLFuse

**A Python ORM where Pydantic validation always runs, including on database table models.**

SQLFuse combines Pydantic v2 and SQLAlchemy 2 into a single class definition. You describe your data once, and you get both a fully validated Pydantic model and a real SQLAlchemy table. Validation is never skipped: it runs when objects are created, when attributes are changed, and recursively through nested relationships.

## Why SQLFuse?

Using one class for both your database table and your API schema removes a lot of duplication. But if table models skip validation, invalid data can silently reach your database. SQLFuse keeps the single-class approach and makes validation a guarantee rather than an option.

## Features

- **Validation that always works.** Field constraints, custom field validators and model validators run on table models, both on creation and on assignment.
- **Nested validation.** Building an object graph from nested data validates every level, and errors report the full path to the invalid value.
- **Relationships.** One-to-many, many-to-one, many-to-many and self-referential relationships, declared with simple type annotations.
- **Nested models.** Pydantic models, lists and dictionaries can be stored as JSON columns, validated when written and turned back into Pydantic objects when read.
- **Sync and async.** The same models work with both synchronous and asynchronous sessions.
- **Multiple databases.** PostgreSQL, MySQL and SQLite, with portable type mapping.
- **FastAPI ready.** Table models can be used directly as request bodies and response models, with standard validation error responses.
- **Migrations.** Built-in Alembic integration that needs no extra configuration files, plus a simple schema sync helper for development.
- **Full Pydantic field support.** Every Pydantic field option is supported, alongside database column options.
- **SQLAlchemy compatible.** Models are real SQLAlchemy mapped classes, so the full SQLAlchemy query API remains available.

## Installation

SQLFuse is installed from PyPI. Optional extras install the drivers for PostgreSQL, MySQL or async SQLite. Python 3.10 or newer is required; it has been tested on Python 3.13 and 3.14.

## Supported databases

| Database   | Sync driver | Async driver |
|------------|-------------|--------------|
| PostgreSQL | psycopg     | asyncpg      |
| MySQL      | PyMySQL     | aiomysql     |
| SQLite     | built-in    | aiosqlite    |

## How it works

Each table model is compiled into two parts: a SQLAlchemy mapped class that owns database state, and a hidden Pydantic model that owns the validation rules. SQLFuse connects the two, so every value that enters a table model passes through Pydantic first. Rows loaded from the database are not re-validated, which keeps loading fast and means older or legacy data never fails to load.

## Project status

SQLFuse is an early release (version 0.1.0). The core features are covered by an automated test suite, but the library has not yet been tested in production. Feedback and bug reports are very welcome.

### Known limitations

- Table models cannot inherit from other table models; shared fields should live in a non-table base model.
- All table models share one registry, so two table models cannot have the same class name.
- SQLFuse relies on some internal Pydantic APIs, so major Pydantic upgrades may require an update.

## Contributing
![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen)

Contributions are welcome. Please open an issue to discuss bugs or ideas before submitting a pull request, and make sure the test suite passes.

## License

SQLFuse is released under the MIT License.
