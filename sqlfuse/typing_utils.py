"""Annotation helpers: lazy evaluation of forward references and type analysis."""
from __future__ import annotations

import builtins
import types
import typing
from dataclasses import dataclass
from typing import Any, ForwardRef, Union, get_args, get_origin

NoneType = type(None)
_PLACEHOLDERS: dict[str, type] = {}
_LIST_ORIGINS = {list, set, frozenset, tuple, typing.List, typing.Set,
                 typing.Sequence, typing.Iterable}
try:
    import collections.abc as _abc
    _LIST_ORIGINS |= {_abc.Sequence, _abc.Iterable, _abc.MutableSequence, _abc.Set}
except Exception:  # pragma: no cover
    pass


def _placeholder(name: str) -> type:
    """A stand-in class for a name that does not exist yet (e.g. a model defined later)."""
    ph = _PLACEHOLDERS.get(name)
    if ph is None:
        ph = type(name, (), {"__orm_ref__": name})
        _PLACEHOLDERS[name] = ph
    return ph


def is_placeholder(tp: Any) -> bool:
    return isinstance(tp, type) and "__orm_ref__" in tp.__dict__


class _LazyNamespace(dict):
    def __missing__(self, key: str) -> type:
        if key.startswith("__"):
            raise KeyError(key)
        return _placeholder(key)


def build_namespace(globalns: dict | None, localns: dict | None) -> _LazyNamespace:
    ns = _LazyNamespace()
    ns.update(vars(builtins))
    ns.update(vars(typing))
    if globalns:
        ns.update(globalns)
    if localns:
        ns.update(localns)
    return ns


def evaluate(annotation: Any, ns: dict) -> Any:
    """Evaluate string / ForwardRef annotations; unknown names become placeholders."""
    if isinstance(annotation, ForwardRef):
        annotation = annotation.__forward_arg__
    if isinstance(annotation, str):
        return eval(annotation, {"__builtins__": builtins}, ns)  # noqa: S307
    return annotation


@dataclass
class TypeInfo:
    outer: Any            # type with Optional removed (e.g. list[Address])
    inner: Any            # the core type (int, str, a model class, a placeholder ...)
    optional: bool        # None allowed
    is_list: bool         # collection of items (relationships)
    target_name: str | None  # for relationships: target model class name


def _name_of(tp: Any) -> str | None:
    if isinstance(tp, ForwardRef):
        return tp.__forward_arg__
    if isinstance(tp, str):
        return tp.strip("'\" ")
    if isinstance(tp, type):
        return tp.__dict__.get("__orm_ref__", tp.__name__)
    return None


def analyze(annotation: Any, ns: dict) -> TypeInfo:
    tp = evaluate(annotation, ns)
    optional = False
    is_list = False
    while True:
        origin = get_origin(tp)
        if origin is typing.Annotated:
            tp = get_args(tp)[0]
            continue
        if origin in (Union, types.UnionType):
            args = [a for a in get_args(tp) if a is not NoneType]
            if len(args) != len(get_args(tp)):
                optional = True
            if len(args) == 1:
                tp = evaluate(args[0], ns)
                continue
            break  # real union (e.g. int | str) – leave as is
        if isinstance(tp, (str, ForwardRef)):
            tp = evaluate(tp, ns)
            continue
        break
    target = None
    outer = tp
    origin = get_origin(tp)
    if origin in _LIST_ORIGINS:
        args = get_args(tp)
        if args:
            is_list = True
            item = args[0]
            if isinstance(item, (str, ForwardRef)):
                item = evaluate(item, ns)
            # unwrap Optional inside list
            if get_origin(item) in (Union, types.UnionType):
                item = next(a for a in get_args(item) if a is not NoneType)
            target = _name_of(item)
            tp_inner = item
        else:
            tp_inner = tp
    else:
        tp_inner = tp
        target = _name_of(tp)
    return TypeInfo(outer=outer, inner=tp_inner, optional=optional, is_list=is_list, target_name=target)


def contains_placeholder(tp: Any) -> bool:
    if is_placeholder(tp):
        return True
    return any(contains_placeholder(a) for a in get_args(tp) if not isinstance(a, (str, int)))
