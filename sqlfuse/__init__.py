"""SQLFuse: an ORM where Pydantic validation always applies, even with table=True."""
from pydantic import ValidationError, field_validator, model_validator
from sqlalchemy import and_, delete, func, insert, not_, or_, select, text, update
from sqlalchemy.orm import joinedload, selectinload, subqueryload

from .fields import Field, Relationship
from .main import TABLE_MODELS, SQLFuse, SQLBase, TableModel
from .session import (
    AsyncSession,
    Database,
    Session,
    create_async_engine,
    create_engine,
)

__version__ = "0.1.0"

__all__ = [
    "SQLFuse", "TableModel", "SQLBase", "TABLE_MODELS", "Field", "Relationship",
    "Session", "AsyncSession", "Database", "create_engine", "create_async_engine",
    "select", "insert", "update", "delete", "text", "func", "and_", "or_", "not_",
    "selectinload", "joinedload", "subqueryload",
    "ValidationError", "field_validator", "model_validator",
]
