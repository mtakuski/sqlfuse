"""Field and Relationship declarations."""
from __future__ import annotations

import inspect
import re
from dataclasses import dataclass, field as dc_field
from typing import Any, Callable, Literal

from annotated_types import SupportsGe, SupportsGt, SupportsLe, SupportsLt
from pydantic import AliasChoices, AliasPath, Discriminator
from pydantic import Field as PydanticField
from pydantic.fields import Deprecated, FieldInfo, JsonDict
from pydantic_core import PydanticUndefined

Undefined = PydanticUndefined


@dataclass
class ColumnSpec:
    """Column-level options collected from ``Field()``."""

    primary_key: bool = False
    foreign_key: str | None = None
    ondelete: str | None = None
    onupdate_fk: str | None = None
    unique: bool = False
    index: bool = False
    nullable: bool | None = None
    autoincrement: bool | str = "auto"
    sa_type: Any = None
    sa_column: Any = None
    sa_column_args: tuple = ()
    sa_column_kwargs: dict = dc_field(default_factory=dict)
    server_default: Any = None
    onupdate: Any = None
    comment: str | None = None


class OrmField:
    """Return value of :func:`Field`: Pydantic kwargs plus column options."""

    __slots__ = ("pydantic_kwargs", "column")

    def __init__(self, pydantic_kwargs: dict[str, Any], column: ColumnSpec):
        self.pydantic_kwargs = pydantic_kwargs
        self.column = column

    @property
    def default(self) -> Any:
        return self.pydantic_kwargs.get("default", Undefined)

    def to_field_info(self) -> FieldInfo:
        return PydanticField(**self.pydantic_kwargs)


def Field(
    default: Any = Undefined,
    *,
    # ---- every pydantic.Field option (forwarded as-is) ----
    default_factory: Callable[[], Any] | Callable[[dict[str, Any]], Any] | None = Undefined,
    alias: str | None = Undefined,
    alias_priority: int | None = Undefined,
    validation_alias: str | AliasPath | AliasChoices | None = Undefined,
    serialization_alias: str | None = Undefined,
    title: str | None = Undefined,
    field_title_generator: Callable[[str, FieldInfo], str] | None = Undefined,
    description: str | None = Undefined,
    examples: list[Any] | None = Undefined,
    exclude: bool | None = Undefined,
    exclude_if: Callable[[Any], bool] | None = Undefined,
    discriminator: str | Discriminator | None = Undefined,
    deprecated: Deprecated | str | bool | None = Undefined,
    json_schema_extra: JsonDict | Callable[[JsonDict], None] | None = Undefined,
    frozen: bool | None = Undefined,
    validate_default: bool | None = Undefined,
    repr: bool = Undefined,
    init: bool | None = Undefined,
    init_var: bool | None = Undefined,
    kw_only: bool | None = Undefined,
    pattern: str | re.Pattern[str] | None = Undefined,
    strict: bool | None = Undefined,
    coerce_numbers_to_str: bool | None = Undefined,
    gt: SupportsGt | None = Undefined,
    ge: SupportsGe | None = Undefined,
    lt: SupportsLt | None = Undefined,
    le: SupportsLe | None = Undefined,
    multiple_of: float | None = Undefined,
    allow_inf_nan: bool | None = Undefined,
    max_digits: int | None = Undefined,
    decimal_places: int | None = Undefined,
    min_length: int | None = Undefined,
    max_length: int | None = Undefined,
    union_mode: Literal["smart", "left_to_right"] = Undefined,
    fail_fast: bool | None = Undefined,
    # ---- column options ----
    primary_key: bool = False,
    foreign_key: str | None = None,
    ondelete: str | None = None,
    unique: bool = False,
    index: bool = False,
    nullable: bool | None = None,
    autoincrement: bool | str = "auto",
    sa_type: Any = None,
    sa_column: Any = None,
    sa_column_args: tuple = (),
    sa_column_kwargs: dict[str, Any] | None = None,
    server_default: Any = None,
    onupdate: Any = None,
    comment: str | None = None,
) -> Any:
    """Declare a field: accepts every ``pydantic.Field`` option plus SQL column options."""
    pyd = {k: v for k, v in locals().items() if k in _PYDANTIC_FIELD_PARAMS and v is not Undefined}
    if "default" in pyd and "default_factory" in pyd:
        raise TypeError("cannot specify both default and default_factory")
    col = ColumnSpec(
        primary_key=primary_key, foreign_key=foreign_key, ondelete=ondelete,
        unique=unique, index=index, nullable=nullable, autoincrement=autoincrement,
        sa_type=sa_type, sa_column=sa_column, sa_column_args=tuple(sa_column_args),
        sa_column_kwargs=dict(sa_column_kwargs or {}), server_default=server_default,
        onupdate=onupdate, comment=comment,
    )
    return OrmField(pyd, col)


_PYDANTIC_FIELD_PARAMS = frozenset(inspect.signature(PydanticField).parameters) - {"extra"}


@dataclass
class RelationshipSpec:
    """Return value of :func:`Relationship`."""

    back_populates: str | None = None
    link_model: Any = None
    cascade: str | None = None
    lazy: str | None = None
    order_by: Any = None
    foreign_keys: Any = None
    passive_deletes: bool = False
    sa_relationship: Any = None
    sa_relationship_args: tuple = ()
    sa_relationship_kwargs: dict = dc_field(default_factory=dict)


def Relationship(
    *,
    back_populates: str | None = None,
    link_model: Any = None,
    cascade: str | None = None,
    lazy: str | None = None,
    order_by: Any = None,
    foreign_keys: Any = None,
    passive_deletes: bool = False,
    sa_relationship: Any = None,
    sa_relationship_args: tuple = (),
    sa_relationship_kwargs: dict[str, Any] | None = None,
) -> Any:
    """Declare a relationship. Target class and ``uselist`` come from the annotation.

    * ``list["Hero"]``            → one-to-many (or many-to-many with ``link_model``)
    * ``"Team | None"`` / ``Team`` → many-to-one / one-to-one
    """
    return RelationshipSpec(
        back_populates=back_populates, link_model=link_model, cascade=cascade,
        lazy=lazy, order_by=order_by, foreign_keys=foreign_keys,
        passive_deletes=passive_deletes, sa_relationship=sa_relationship,
        sa_relationship_args=tuple(sa_relationship_args),
        sa_relationship_kwargs=dict(sa_relationship_kwargs or {}),
    )
