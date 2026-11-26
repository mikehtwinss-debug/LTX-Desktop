"""Engine, declarative base, model mixins and the session factory."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    Engine,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    String,
    create_engine,
    event,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    MappedColumn,
    Session,
    UOWTransaction,
    declared_attr,
    mapped_column,
    sessionmaker,
)
from sqlalchemy.sql import func

from app.core.errors import Conflict

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def utcnow() -> datetime:
    return datetime.now(UTC)


def ref(target: str, *, ondelete: str = "RESTRICT", **kwargs: Any) -> MappedColumn[Any]:
    """Foreign key column to a BigInteger primary key (`ref("org_plant.id")`)."""
    return mapped_column(BigInteger, ForeignKey(target, ondelete=ondelete), **kwargs)


def currency_ref(**kwargs: Any) -> MappedColumn[Any]:
    """Foreign key column to `org_currency.code`."""
    return mapped_column(String(3), ForeignKey("org_currency.code", ondelete="RESTRICT"), **kwargs)


class IdMixin:
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True, sort_order=-100)


class TimestampMixin:
    """Creation/update stamps; the user columns are filled from `session.info["user_id"]`."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, server_default=func.now(), sort_order=100
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, server_default=func.now(), sort_order=101
    )
    created_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("auth_user.id", ondelete="RESTRICT"), sort_order=102
    )
    updated_by_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("auth_user.id", ondelete="RESTRICT"), sort_order=103
    )


class CompanyMixin:
    company_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("org_company.id", ondelete="RESTRICT"), index=True, sort_order=-90
    )


class VersionMixin:
    """Optimistic locking: update payloads carry `version`; see `assert_version`."""

    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", sort_order=90)

    @declared_attr.directive
    def __mapper_args__(cls) -> dict[str, Any]:
        return {"version_id_col": cls.version}


def assert_version(obj: VersionMixin, version: int) -> None:
    """Reject an update that was prepared against an older version of the row."""
    if obj.version != version:
        raise Conflict(
            "STALE_DATA",
            "Kayıt başka bir kullanıcı tarafından değiştirilmiş. Lütfen yenileyip tekrar deneyin.",
            details={"current_version": obj.version},
        )


@event.listens_for(Session, "before_flush")
def _stamp_users(session: Session, flush_context: UOWTransaction, instances: Any) -> None:
    user_id = session.info.get("user_id")
    if user_id is None:
        return
    for obj in session.new:
        if isinstance(obj, TimestampMixin):
            if obj.created_by_id is None:
                obj.created_by_id = user_id
            if obj.updated_by_id is None:
                obj.updated_by_id = user_id
    for obj in session.dirty:
        if isinstance(obj, TimestampMixin) and session.is_modified(obj):
            obj.updated_by_id = user_id


def make_engine(url: str) -> Engine:
    return create_engine(url, pool_pre_ping=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
