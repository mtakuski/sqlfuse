"""Core: SQLFuse base class, metaclass, and the table-model runtime."""
from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar, TypeVar, get_origin

import sqlalchemy as sa
from pydantic import BaseModel, ConfigDict, ValidationError
from pydantic_core import PydanticCustomError
from pydantic import Field as PydanticField
from pydantic._internal._decorators import PydanticDescriptorProxy
from pydantic._internal._model_construction import ModelMetaclass
from pydantic.fields import FieldInfo
from sqlalchemy.orm import DeclarativeBase, relationship as sa_relationship

from .fields import ColumnSpec, OrmField, RelationshipSpec, Undefined
from .sqltypes import sa_type_for
from .typing_utils import analyze, build_namespace, contains_placeholder, evaluate

T = TypeVar("T", bound="TableModel")

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class SQLBase(DeclarativeBase):
    """Shared SQLAlchemy declarative base for every ``table=True`` model."""

    metadata = sa.MetaData(naming_convention=NAMING_CONVENTION)


#: class name -> table model (used to resolve relationship targets)
TABLE_MODELS: dict[str, type[TableModel]] = {}

_DEFAULT_CONFIG = ConfigDict(from_attributes=True, arbitrary_types_allowed=True)


@dataclass(frozen=True)
class RelInfo:
    target_name: str
    is_list: bool
    optional: bool

    @property
    def target(self) -> type[TableModel]:
        try:
            return TABLE_MODELS[self.target_name]
        except KeyError:
            raise LookupError(f"Unknown relationship target model {self.target_name!r}") from None


# --------------------------------------------------------------------------- helpers

def _class_frame_locals() -> dict | None:
    """Locals of the scope that executes the ``class`` statement (for local forward refs)."""
    frame = sys._getframe(2)
    while frame is not None and frame.f_globals.get("__name__", "").startswith(("pydantic", "sqlfuse.main")):
        frame = frame.f_back
    if frame is None or frame.f_code.co_name == "<module>":
        return None
    return dict(frame.f_locals)


def _own_annotations(namespace: dict) -> dict[str, Any]:
    if "__annotations__" in namespace:
        return dict(namespace["__annotations__"])
    if sys.version_info >= (3, 14):  # PEP 649/749: lazily evaluated annotations
        import annotationlib

        annotate = annotationlib.get_annotate_from_class_namespace(namespace)
        if annotate is not None:
            # STRING format → resolved later by our lazy namespace (forward refs allowed)
            return annotationlib.call_annotate_function(annotate, annotationlib.Format.STRING)
    return {}


def _is_classvar(ann: Any) -> bool:
    if isinstance(ann, str):
        return ann.startswith(("ClassVar", "typing.ClassVar"))
    return get_origin(ann) is ClassVar or ann is ClassVar


def _merge_line_errors(errors: list[dict], exc: ValidationError, prefix: tuple) -> None:
    for err in exc.errors(include_url=False):
        # Re-raise every error as a custom error carrying its original type and message,
        # so any error (incl. EmailStr / custom types without standard ctx) round-trips.
        ctx = err.get("ctx")
        errors.append({
            "type": PydanticCustomError(err["type"], err["msg"].replace("{", "{{").replace("}", "}}"),
                                        ctx),
            "loc": prefix + tuple(err["loc"]),
            "input": err.get("input"),
        })


# --------------------------------------------------------------------------- metaclass

class SQLFuseMeta(ModelMetaclass):
    """Builds a Pydantic model (``table=False``) or a validated SQLAlchemy model (``table=True``)."""

    def __new__(mcs, name: str, bases: tuple, namespace: dict, table: bool = False, **kwargs: Any):
        if table:
            return _build_table_model(name, bases, namespace, _class_frame_locals())

        columns: dict[str, ColumnSpec] = {}
        for base in reversed(bases):
            columns.update(getattr(base, "__orm_columns__", {}))
        new_ns = dict(namespace)
        for key, value in namespace.items():
            if isinstance(value, OrmField):
                new_ns[key] = value.to_field_info()
                columns[key] = value.column
            elif isinstance(value, RelationshipSpec):
                raise TypeError(
                    f"{name}.{key}: Relationship() is only allowed on table=True models"
                )
        new_ns["__orm_columns__"] = columns
        cls = super().__new__(mcs, name, bases, new_ns, **kwargs)
        if not cls.__pydantic_complete__:
            localns = _class_frame_locals()
            if localns:
                cls.model_rebuild(raise_errors=False, _types_namespace=localns)
        return cls

    # isinstance(hero, SQLFuse) / isinstance(hero, HeroBase) work for table instances too
    def __instancecheck__(cls, instance: Any) -> bool:
        if isinstance(type(instance), type) and issubclass(type(instance), TableModel):
            return cls is SQLFuse or cls in type(instance).__orm_pydantic_mro__
        return super().__instancecheck__(instance)

    def __subclasscheck__(cls, subclass: Any) -> bool:
        if isinstance(subclass, type) and issubclass(subclass, TableModel) and subclass is not TableModel:
            return cls is SQLFuse or cls in subclass.__orm_pydantic_mro__
        return super().__subclasscheck__(subclass)


def _make_column(name: str, ann: Any, finfo: FieldInfo, col: ColumnSpec, ns: dict) -> sa.Column:
    if col.sa_column is not None:
        column = col.sa_column
        if column.name is None:
            column.name = name
        return column
    info = analyze(ann, ns)
    sa_type = col.sa_type if col.sa_type is not None else sa_type_for(info.outer, finfo)
    if isinstance(sa_type, type):
        sa_type = sa_type()
    args: list[Any] = list(col.sa_column_args)
    if col.foreign_key:
        args.append(sa.ForeignKey(col.foreign_key, ondelete=col.ondelete))
    nullable = col.nullable
    if nullable is None:
        nullable = (not col.primary_key) and info.optional
    kwargs: dict[str, Any] = dict(
        primary_key=col.primary_key,
        nullable=nullable,
        autoincrement=col.autoincrement,
        comment=col.comment,
    )
    if col.unique:
        kwargs["unique"] = True
    if col.index:
        kwargs["index"] = True
    if col.server_default is not None:
        sd = col.server_default
        kwargs["server_default"] = sa.text(sd) if isinstance(sd, str) else sd
    if col.onupdate is not None:
        kwargs["onupdate"] = col.onupdate
    if finfo.default is not Undefined and finfo.default is not None and not callable(finfo.default):
        kwargs["default"] = finfo.default
    elif finfo.default_factory is not None and not finfo.default_factory_takes_validated_data:
        factory = finfo.default_factory
        kwargs["default"] = lambda ctx: factory()
    kwargs.update(col.sa_column_kwargs)
    return sa.Column(name, sa_type, *args, **kwargs)


def _make_relationship(owner: str, name: str, raw_ann: Any, spec: RelationshipSpec, ns: dict):
    info = analyze(raw_ann, ns)
    if not info.target_name:
        raise TypeError(f"{owner}.{name}: cannot infer relationship target from {raw_ann!r}")
    rel = RelInfo(info.target_name, info.is_list, info.optional)
    if spec.sa_relationship is not None:
        return spec.sa_relationship, rel
    kwargs: dict[str, Any] = {"uselist": info.is_list}
    if spec.back_populates:
        kwargs["back_populates"] = spec.back_populates
    if spec.link_model is not None:
        link = spec.link_model
        if isinstance(link, str):
            kwargs["secondary"] = lambda: TABLE_MODELS[link].__table__
        else:
            kwargs["secondary"] = link.__table__
    for key in ("cascade", "lazy", "order_by", "foreign_keys"):
        val = getattr(spec, key)
        if val is not None:
            kwargs[key] = val
    if spec.passive_deletes:
        kwargs["passive_deletes"] = True
    kwargs.update(spec.sa_relationship_kwargs)
    return sa_relationship(info.target_name, *spec.sa_relationship_args, **kwargs), rel


def _build_table_model(name: str, bases: tuple, namespace: dict, localns: dict | None):
    module = namespace.get("__module__", "__main__")
    globalns = vars(sys.modules[module]) if module in sys.modules else {}
    ns = build_namespace(globalns, localns)

    pyd_bases: list[type[BaseModel]] = []
    mixins: list[type] = []
    for base in bases:
        if isinstance(base, type) and issubclass(base, TableModel):
            raise TypeError(f"{name}: inheriting from table model {base.__name__} is not supported; "
                            "inherit from a table=False base model instead")
        if isinstance(base, type) and issubclass(base, BaseModel):
            pyd_bases.append(base)
        else:
            mixins.append(base)

    # ---- collect fields: inherited (pydantic bases) then own
    fields: dict[str, tuple[Any, FieldInfo, ColumnSpec]] = {}
    for base in reversed(pyd_bases):
        base_cols = getattr(base, "__orm_columns__", {})
        for fname, finfo in base.model_fields.items():
            fields[fname] = (finfo.annotation, finfo, base_cols.get(fname, ColumnSpec()))

    relationships: dict[str, tuple[Any, RelationshipSpec]] = {}
    for fname, raw_ann in _own_annotations(namespace).items():
        if _is_classvar(raw_ann) or fname.startswith("_"):
            continue
        value = namespace.get(fname, Undefined)
        if isinstance(value, RelationshipSpec):
            relationships[fname] = (raw_ann, value)
            fields.pop(fname, None)
            continue
        if isinstance(value, OrmField):
            finfo, col = value.to_field_info(), value.column
        elif isinstance(value, FieldInfo):
            finfo, col = value, ColumnSpec()
        elif value is Undefined:
            finfo, col = PydanticField(), ColumnSpec()
        else:
            finfo, col = PydanticField(default=value), ColumnSpec()
        ann = evaluate(raw_ann, ns)
        if contains_placeholder(ann):
            raise TypeError(f"{name}.{fname}: cannot resolve annotation {raw_ann!r}. "
                            "Use Relationship() for references to other table models.")
        fields[fname] = (ann, finfo, col)

    validators = {k: v for k, v in namespace.items() if isinstance(v, PydanticDescriptorProxy)}

    # ---- pydantic validator model
    config = dict(_DEFAULT_CONFIG)
    for base in pyd_bases:
        config.update(base.model_config)
    user_config = dict(namespace.get("model_config", {}))
    validate_assignment = user_config.pop("validate_assignment", True)
    config.update(user_config)
    config.pop("validate_assignment", None)
    config["title"] = config.get("title") or name

    v_ns: dict[str, Any] = {"__module__": module, "__annotations__": {}, "model_config": config}
    for fname, (ann, finfo, _col) in fields.items():
        v_ns["__annotations__"][fname] = ann
        v_ns[fname] = finfo
    for rname in relationships:
        v_ns["__annotations__"][rname] = Any
        v_ns[rname] = None
    v_ns.update(validators)
    v_bases = tuple(pyd_bases) or (BaseModel,)
    validator = type(v_bases[0])(name, v_bases, v_ns)

    # ---- SQLAlchemy mapped class
    skip = set(fields) | set(relationships) | set(validators) | {
        "__annotations__", "__annotate__", "__annotate_func__", "__annotations_cache__", "model_config", "__orm_columns__",
        "__qualname__", "__classcell__",
    }
    sa_ns: dict[str, Any] = {k: v for k, v in namespace.items() if k not in skip}
    sa_ns["__qualname__"] = namespace.get("__qualname__", name)
    sa_ns["__annotations__"] = {}
    sa_ns.setdefault("__tablename__", name.lower())
    for fname, (ann, finfo, col) in fields.items():
        sa_ns[fname] = _make_column(fname, ann, finfo, col, ns)
    rel_infos: dict[str, RelInfo] = {}
    for rname, (raw_ann, spec) in relationships.items():
        sa_ns[rname], rel_infos[rname] = _make_relationship(name, rname, raw_ann, spec, ns)

    pyd_mro: set[type] = set()
    for base in pyd_bases:
        pyd_mro.update(c for c in base.__mro__ if issubclass(c, BaseModel))

    sa_ns.update(
        __validator__=validator,
        __orm_columns__={f: c for f, (_, _, c) in fields.items()},
        __orm_fields__=tuple(fields),
        __orm_relationships__=rel_infos,
        __orm_validate_assignment__=validate_assignment,
        __orm_pydantic_mro__=frozenset(pyd_mro),
    )
    if "__classcell__" in namespace:
        sa_ns["__classcell__"] = namespace["__classcell__"]

    cls = type(SQLBase)(name, (TableModel, *mixins, SQLBase), sa_ns)
    if name in TABLE_MODELS and TABLE_MODELS[name].__module__ != module:
        raise TypeError(f"Duplicate table model name {name!r}")
    TABLE_MODELS[name] = cls
    return cls


# --------------------------------------------------------------------------- runtime

class TableModel:
    """Mixin providing validation and Pydantic-like API to mapped classes."""

    __validator__: ClassVar[type[BaseModel]]
    __orm_columns__: ClassVar[dict[str, ColumnSpec]]
    __orm_fields__: ClassVar[tuple[str, ...]]
    __orm_relationships__: ClassVar[dict[str, RelInfo]]
    __orm_validate_assignment__: ClassVar[bool]
    __orm_pydantic_mro__: ClassVar[frozenset]

    # -- validation -----------------------------------------------------------
    def __init__(self, **data: Any) -> None:
        cls = type(self)
        errors: list[dict] = []
        validated: BaseModel | None = None
        try:
            validated = cls.__validator__.model_validate(data)
        except ValidationError as exc:
            _merge_line_errors(errors, exc, ())

        rel_values: dict[str, Any] = {}
        for rname, rel in cls.__orm_relationships__.items():
            key = rname if rname in data else _alias_key(cls, rname, data)
            if key is None:
                continue
            try:
                rel_values[rname] = _coerce_relationship(rel, data[key], (rname,), errors)
            except _RelError:
                pass
        if errors:
            raise ValidationError.from_exception_data(cls.__name__, errors)

        assert validated is not None
        self._apply(validated, rel_values)

    def _apply(self, validated: BaseModel, rel_values: dict[str, Any]) -> None:
        cls = type(self)
        fields_set = validated.model_fields_set
        for fname in cls.__orm_fields__:
            value = getattr(validated, fname)
            col = cls.__orm_columns__[fname]
            if value is None and fname not in fields_set and (
                col.primary_key or col.server_default is not None
            ):
                continue
            object.__setattr__(self, fname, value)
        for rname, value in rel_values.items():
            object.__setattr__(self, rname, value)

    def __setattr__(self, name: str, value: Any) -> None:
        cls = type(self)
        if name in cls.__orm_relationships__:
            errors: list[dict] = []
            try:
                value = _coerce_relationship(cls.__orm_relationships__[name], value, (name,), errors)
            except _RelError:
                raise ValidationError.from_exception_data(cls.__name__, errors) from None
        elif cls.__orm_validate_assignment__ and name in cls.__orm_fields__:
            value = self._validate_assignment(name, value)
        object.__setattr__(self, name, value)

    def _validate_assignment(self, name: str, value: Any) -> Any:
        cls = type(self)
        current = {f: self.__dict__[f] for f in cls.__orm_fields__ if f in self.__dict__}
        proxy = cls.__validator__.model_construct(**current)
        cls.__validator__.__pydantic_validator__.validate_assignment(proxy, name, value)
        return getattr(proxy, name)

    # -- pydantic-like API ----------------------------------------------------
    @classmethod
    def model_validate(cls: type[T], obj: Any, *, update: dict[str, Any] | None = None) -> T:
        if isinstance(obj, TableModel):
            data = obj.model_dump(relationships=False)
        elif isinstance(obj, BaseModel):
            data = obj.model_dump(exclude_unset=True)
        elif isinstance(obj, Mapping):
            data = dict(obj)
        else:
            names = (*cls.__orm_fields__, *cls.__orm_relationships__)
            data = {n: getattr(obj, n) for n in names if hasattr(obj, n)}
        if update:
            data.update(update)
        return cls(**data)

    @classmethod
    def __get_pydantic_core_schema__(cls, source: Any, handler: Any) -> Any:
        """Lets table models be used directly as FastAPI / Pydantic field types."""
        from pydantic_core import core_schema as cs

        def build(validated: BaseModel) -> Any:
            # already validated by the schema: build the instance without re-validating
            errors: list[dict] = []
            rel_values: dict[str, Any] = {}
            for rname, rel in cls.__orm_relationships__.items():
                if rname in validated.model_fields_set:
                    try:
                        rel_values[rname] = _coerce_relationship(
                            rel, getattr(validated, rname), (rname,), errors)
                    except _RelError:
                        pass
            if errors:
                raise ValidationError.from_exception_data(cls.__name__, errors)
            cls.__mapper__._check_configure()
            obj = cls.__mapper__.class_manager.new_instance()
            obj._apply(validated, rel_values)
            return obj

        from_data = cs.no_info_after_validator_function(build, cls.__validator__.__pydantic_core_schema__)
        return cs.no_info_wrap_validator_function(
            lambda v, handler: v if isinstance(v, cls) else handler(v),
            from_data,
            serialization=cs.plain_serializer_function_ser_schema(
                lambda v, info: v.model_dump(mode=info.mode), info_arg=True,
            ),
        )

    @classmethod
    def model_validate_json(cls: type[T], json_data: str | bytes) -> T:
        return cls.model_validate(json.loads(json_data))

    @classmethod
    def model_json_schema(cls, **kwargs: Any) -> dict[str, Any]:
        return cls.__validator__.model_json_schema(**kwargs)

    @classmethod
    def model_fields(cls) -> dict[str, FieldInfo]:  # noqa: D401
        return {k: v for k, v in cls.__validator__.model_fields.items() if k in cls.__orm_fields__}

    def model_update(self: T, data: Mapping[str, Any] | BaseModel, *, exclude_unset: bool = True) -> T:
        """Apply a partial update (e.g. a PATCH payload) with validation."""
        if isinstance(data, BaseModel):
            data = data.model_dump(exclude_unset=exclude_unset)
        cls = type(self)
        errors: list[dict] = []
        values: dict[str, Any] = {}
        for key, value in data.items():
            if key in cls.__orm_fields__ and cls.__orm_validate_assignment__:
                try:
                    values[key] = self._validate_assignment(key, value)
                except ValidationError as exc:
                    _merge_line_errors(errors, exc, ())
            elif key in cls.__orm_relationships__:
                try:
                    values[key] = _coerce_relationship(cls.__orm_relationships__[key], value, (key,), errors)
                except _RelError:
                    pass
            elif key in cls.__orm_fields__:
                values[key] = value
        if errors:
            raise ValidationError.from_exception_data(cls.__name__, errors)
        for key, value in values.items():
            object.__setattr__(self, key, value)
        return self

    def model_dump(
        self,
        *,
        mode: str = "python",
        include: set[str] | None = None,
        exclude: set[str] | None = None,
        exclude_none: bool = False,
        by_alias: bool = False,
        relationships: bool = True,
        _seen: frozenset[int] = frozenset(),
    ) -> dict[str, Any]:
        """Serialize loaded columns (and loaded relationships, recursively). Never triggers I/O."""
        cls = type(self)
        state = sa.inspect(self)
        unloaded = state.unloaded
        cols = {f: self.__dict__[f] for f in cls.__orm_fields__
                if f not in unloaded and f in self.__dict__}
        data = cls.__validator__.model_construct(**cols).model_dump(
            mode=mode, include=set(cols) & (include or set(cols)), exclude=exclude,
            exclude_none=exclude_none, by_alias=by_alias, warnings=False,
        )
        if relationships:
            seen = _seen | {id(self)}
            for rname in cls.__orm_relationships__:
                if rname in unloaded or (include and rname not in include) or (exclude and rname in exclude):
                    continue
                value = self.__dict__.get(rname)
                if value is None:
                    if not exclude_none:
                        data[rname] = None
                    continue
                kw = dict(mode=mode, exclude_none=exclude_none, by_alias=by_alias, _seen=seen)
                if isinstance(value, (list, set, tuple)):
                    data[rname] = [v.model_dump(**kw) for v in value if id(v) not in seen]
                elif id(value) not in seen:
                    data[rname] = value.model_dump(**kw)
        return data

    def model_dump_json(self, *, indent: int | None = None, **kwargs: Any) -> str:
        return json.dumps(self.model_dump(mode="json", **kwargs), indent=indent)

    def __repr__(self) -> str:
        cls = type(self)
        parts = [f"{f}={self.__dict__[f]!r}" for f in cls.__orm_fields__ if f in self.__dict__]
        return f"{cls.__name__}({', '.join(parts)})"

    # -- read-only mapping view (dict(user), FastAPI body detection) ----------
    def keys(self) -> list[str]:
        return list(self.model_dump().keys())

    def items(self) -> list[tuple[str, Any]]:
        return list(self.model_dump().items())

    def __getitem__(self, key: str) -> Any:
        cls = type(self)
        if key in cls.__orm_fields__ or key in cls.__orm_relationships__:
            return getattr(self, key)
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: object) -> bool:
        cls = type(self)
        return key in cls.__orm_fields__ or key in cls.__orm_relationships__


# FastAPI treats Mapping-typed parameters as request bodies, so `user: User` just works.
Mapping.register(TableModel)


class _RelError(Exception):
    pass


def _alias_key(cls: type[TableModel], rname: str, data: Mapping) -> str | None:
    finfo = cls.__validator__.model_fields.get(rname)
    if finfo is not None and finfo.alias and finfo.alias in data:
        return finfo.alias
    return None


def _coerce_one(rel: RelInfo, value: Any, loc: tuple, errors: list[dict]) -> Any:
    target = rel.target
    if isinstance(value, target):
        return value
    if isinstance(value, TableModel):
        pass  # wrong table model -> model_type error below
    elif isinstance(value, BaseModel):
        value = value.model_dump(exclude_unset=True)
    if isinstance(value, Mapping) and not isinstance(value, TableModel):
        try:
            return target(**value)
        except ValidationError as exc:
            _merge_line_errors(errors, exc, loc)
            raise _RelError from None
    errors.append({"type": "model_type", "loc": loc, "input": value,
                   "ctx": {"class_name": rel.target_name}})
    raise _RelError


def _coerce_relationship(rel: RelInfo, value: Any, loc: tuple, errors: list[dict]) -> Any:
    if rel.is_list:
        if value is None:
            errors.append({"type": "list_type", "loc": loc, "input": value})
            raise _RelError
        if isinstance(value, (str, bytes, Mapping)) or not hasattr(value, "__iter__"):
            errors.append({"type": "list_type", "loc": loc, "input": value})
            raise _RelError
        out, failed = [], False
        for i, item in enumerate(value):
            try:
                out.append(_coerce_one(rel, item, loc + (i,), errors))
            except _RelError:
                failed = True
        if failed:
            raise _RelError
        return out
    if value is None:
        return None
    return _coerce_one(rel, value, loc, errors)


# --------------------------------------------------------------------------- public base

class SQLFuse(BaseModel, metaclass=SQLFuseMeta):
    """Base class for all models.

    * ``class HeroBase(SQLFuse)``            → Pydantic model (schemas, shared fields)
    * ``class Hero(HeroBase, table=True)`` → validated SQLAlchemy table model
    """

    model_config = _DEFAULT_CONFIG
    metadata: ClassVar[sa.MetaData] = SQLBase.metadata
