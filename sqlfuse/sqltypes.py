"""Mapping of Python / Pydantic types to portable SQLAlchemy column types."""
from __future__ import annotations

import datetime as dt
import decimal
import enum
import ipaddress
import pathlib
import uuid
from typing import Any, get_args, get_origin

import sqlalchemy as sa
from pydantic import BaseModel, TypeAdapter
from pydantic.fields import FieldInfo
from sqlalchemy.types import TypeDecorator

DEFAULT_STRING_LENGTH = 255


def constraint(field_info: FieldInfo | None, name: str) -> Any:
    """Read a constraint (max_length, max_digits, ...) from a FieldInfo."""
    if field_info is None:
        return None
    val = getattr(field_info, name, None)
    if val is not None:
        return val
    for meta in field_info.metadata:
        val = getattr(meta, name, None)
        if val is not None:
            return val
    return None


class PydanticJSON(TypeDecorator):
    """JSON column holding a Pydantic model / nested structure, validated both ways."""

    impl = sa.JSON
    cache_ok = True

    def __init__(self, annotation: Any, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.annotation = annotation
        self._adapter: TypeAdapter | None = None

    @property
    def adapter(self) -> TypeAdapter:
        if self._adapter is None:
            self._adapter = TypeAdapter(self.annotation)
        return self._adapter

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        value = self.adapter.validate_python(value)
        return self.adapter.dump_python(value, mode="json")

    def process_result_value(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        return self.adapter.validate_python(value)


def _is_json_like(tp: Any) -> bool:
    origin = get_origin(tp)
    if origin in (list, dict, set, tuple, frozenset):
        return True
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return True
    if tp in (dict, list):
        return True
    return False


def sa_type_for(tp: Any, field_info: FieldInfo | None) -> Any:
    """Return a SQLAlchemy type instance for python type ``tp``."""
    if get_origin(tp) is not None and get_origin(tp).__name__ == "Literal":
        values = get_args(tp)
        if all(isinstance(v, str) for v in values):
            return sa.String(max(len(v) for v in values) or 1)
        return sa.Integer()
    if isinstance(tp, type):
        if issubclass(tp, bool):
            return sa.Boolean()
        if issubclass(tp, enum.Enum):
            return sa.Enum(tp, native_enum=False, length=64, validate_strings=True)
        if issubclass(tp, int):
            return sa.Integer()
        if issubclass(tp, float):
            return sa.Float()
        if issubclass(tp, decimal.Decimal):
            return sa.Numeric(precision=constraint(field_info, "max_digits"),
                              scale=constraint(field_info, "decimal_places"))
        if issubclass(tp, str):
            return sa.String(constraint(field_info, "max_length") or DEFAULT_STRING_LENGTH)
        if issubclass(tp, dt.datetime):
            return sa.DateTime(timezone=True)
        if issubclass(tp, dt.date):
            return sa.Date()
        if issubclass(tp, dt.time):
            return sa.Time()
        if issubclass(tp, dt.timedelta):
            return sa.Interval()
        if issubclass(tp, uuid.UUID):
            return sa.Uuid()
        if issubclass(tp, bytes):
            return sa.LargeBinary(constraint(field_info, "max_length"))
        if issubclass(tp, (ipaddress.IPv4Address, ipaddress.IPv6Address,
                           ipaddress.IPv4Network, ipaddress.IPv6Network, pathlib.Path)):
            return sa.String(DEFAULT_STRING_LENGTH)
    if _is_json_like(tp):
        return PydanticJSON(tp)
    # Pydantic special str-like types (EmailStr, HttpUrl, ...)
    if getattr(tp, "__module__", "").startswith("pydantic"):
        return sa.String(constraint(field_info, "max_length") or DEFAULT_STRING_LENGTH)
    raise TypeError(
        f"Cannot map type {tp!r} to a SQL column; pass Field(sa_type=...) explicitly"
    )
