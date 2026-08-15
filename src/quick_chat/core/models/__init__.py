from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal

from pydantic import UUID7
from sqlalchemy import (
    UUID,
    Boolean,
    DateTime,
    Integer,
    MetaData,
    String,
    text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from uuid_utils.compat import uuid7

from quick_chat.utils.common.logger import logger
from quick_chat.utils.helper import (
    format_date,
    format_localized_datetime,
    format_time,
    time_now,
)


def current_user():
    return "uuid1"


class AgencyBase(DeclarativeBase):
    metadata = MetaData(schema="southern_ute")

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_on: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=time_now, nullable=False, index=True
    )
    created_by: Mapped[str] = mapped_column(
        String(64), default=current_user, nullable=True
    )
    modified_on: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=time_now, onupdate=time_now, nullable=False
    )
    modified_by: Mapped[str] = mapped_column(
        String(64), default=current_user, onupdate=current_user, nullable=True
    )
    modification_version: Mapped[int] = mapped_column(
        Integer, default=1, nullable=False, server_default="1"
    )
    unique_reference_id: Mapped[UUID7] = mapped_column(
        UUID,
        nullable=False,
        unique=True,
        default=uuid7,
        server_default=text("uuidv7()"),
    )

    def to_dict(self, seen: set | None = None):
        if seen is None:
            seen = set()

        if id(self) in seen:
            return None

        seen = seen | {id(self)}  # new set per branch, not mutated in place

        def convert_value(value):
            if isinstance(value, AgencyBase):
                return value.to_dict(seen)
            elif isinstance(value, dict):
                return {key: convert_value(val) for key, val in value.items()}
            elif isinstance(value, list):
                return [convert_value(item) for item in value]
            elif isinstance(value, datetime):
                return format_localized_datetime(value)
            elif isinstance(value, date):
                return format_date(value)
            elif isinstance(value, time):
                return format_time(value)
            elif isinstance(value, UUID):
                return str(value)
            elif isinstance(value, Decimal):
                return float(value)
            elif hasattr(value, "__dict__"):
                return convert_value(vars(value))
            return value

        result = {
            key: convert_value(value)
            for key, value in self.__dict__.items()
            if not key.startswith("_")
        }

        for key, prop in sa_inspect(type(self)).all_orm_descriptors.items():
            if isinstance(prop, hybrid_property) and key not in result:
                try:
                    result[key] = convert_value(getattr(self, key))
                except Exception as e:
                    logger.info(f"Error converting key {key} to dict: {e}")

        return result

    @classmethod
    def column_names(cls):
        return {c_attr.key for c_attr in sa_inspect(cls).column_attrs}
