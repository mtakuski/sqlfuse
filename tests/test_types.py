"""Type mapping and annotation analysis."""
import datetime as dt
import decimal
import enum
import ipaddress
import pathlib
import typing
from typing import Annotated, ForwardRef, Literal, Optional

import pytest
import sqlalchemy as sa
from pydantic import Field as PydanticField
from pydantic import HttpUrl

from sqlfuse.sqltypes import DEFAULT_STRING_LENGTH, PydanticJSON, constraint, sa_type_for
from sqlfuse.typing_utils import (
    _name_of, _placeholder, analyze, build_namespace, contains_placeholder, evaluate,
)


class Color(enum.Enum):
    red = "red"


@pytest.mark.parametrize(("tp", "expected"), [
    (bool, sa.Boolean),
    (int, sa.Integer),
    (float, sa.Float),
    (decimal.Decimal, sa.Numeric),
    (str, sa.String),
    (dt.datetime, sa.DateTime),
    (dt.date, sa.Date),
    (dt.time, sa.Time),
    (dt.timedelta, sa.Interval),
    (bytes, sa.LargeBinary),
    (ipaddress.IPv4Address, sa.String),
    (pathlib.Path, sa.String),
    (Color, sa.Enum),
    (HttpUrl, sa.String),
    (dict, PydanticJSON),
    (list, PydanticJSON),
    (dict[str, int], PydanticJSON),
])
def test_sa_type_for(tp, expected):
    assert isinstance(sa_type_for(tp, None), expected)


def test_literal_types():
    t = sa_type_for(Literal["a", "bbb"], None)
    assert isinstance(t, sa.String) and t.length == 3
    assert isinstance(sa_type_for(Literal[1, 2], None), sa.Integer)


def test_string_length_from_constraint():
    assert sa_type_for(str, PydanticField(max_length=12)).length == 12
    assert sa_type_for(str, None).length == DEFAULT_STRING_LENGTH


def test_unmappable_type():
    with pytest.raises(TypeError, match="sa_type"):
        sa_type_for(complex, None)


def test_constraint_helper():
    assert constraint(None, "max_length") is None
    assert constraint(PydanticField(alias="x"), "alias") == "x"
    assert constraint(PydanticField(max_length=5), "max_length") == 5
    assert constraint(PydanticField(), "max_length") is None


def test_pydantic_json_none_passthrough():
    t = PydanticJSON(list[int])
    assert t.process_bind_param(None, None) is None
    assert t.process_result_value(None, None) is None
    assert t.process_bind_param(["1", 2], None) == [1, 2]
    assert t.process_result_value([1], None) == [1]


def test_analyze_variants():
    ns = build_namespace({}, {"Hero": int})
    info = analyze(Annotated[int, "meta"], ns)
    assert info.inner is int and not info.optional
    info = analyze("int | str", ns)                     # real union is left as is
    assert typing.get_origin(info.outer) is not None and not info.is_list
    info = analyze(ForwardRef("Optional[int]"), ns)
    assert info.inner is int and info.optional
    info = analyze(list, ns)                            # bare list: no item type
    assert info.inner is list and not info.is_list
    info = analyze(list[Optional["Missing"]], ns)       # Optional inside list
    assert info.is_list and info.target_name == "Missing"
    info = analyze(Optional["Team"], ns)
    assert info.optional and info.target_name == "Team"
    assert analyze(Literal["x"], ns).target_name is None
    assert analyze(Annotated["int", "meta"], ns).inner is int    # string inside Annotated
    info = analyze(typing.List, ns)                              # bare typing.List
    assert not info.is_list


def test_name_of_and_placeholders():
    assert _name_of("'Hero'") == "Hero"
    assert _name_of(ForwardRef("Hero")) == "Hero"
    assert _name_of(5) is None
    ph = _placeholder("Ghost")
    assert _placeholder("Ghost") is ph and _name_of(ph) == "Ghost"
    assert contains_placeholder(ph)
    assert contains_placeholder(list[ph]) and not contains_placeholder(list[int])


def test_lazy_namespace():
    ns = build_namespace({"x": 1}, {"y": 2})
    assert ns["x"] == 1 and ns["y"] == 2 and ns["list"] is list
    with pytest.raises(KeyError):
        ns["__dunder__"]
    assert evaluate("Unknown", ns).__orm_ref__ == "Unknown"
    assert evaluate(int, ns) is int


def test_is_classvar():
    from typing import ClassVar

    from sqlfuse.main import _is_classvar

    assert _is_classvar(ClassVar[int]) and _is_classvar(ClassVar) and _is_classvar("ClassVar[int]")
    assert not _is_classvar(int) and not _is_classvar("int")
