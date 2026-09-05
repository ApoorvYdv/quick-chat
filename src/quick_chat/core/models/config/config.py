from sqlalchemy import JSON, Boolean, CheckConstraint, Integer, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column

from quick_chat.core.models import Base


class ConfigBase(Base):
    __abstract__ = True


class Config(ConfigBase):
    __tablename__ = "config"
    __table_args__ = ({"schema": "config"},)

    config_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    agency_name: Mapped[str] = mapped_column(String, nullable=True)
    config_section: Mapped[str] = mapped_column(String, nullable=True)
    config_key: Mapped[str] = mapped_column(String, nullable=True)
    config_value: Mapped[dict] = mapped_column(JSON, nullable=True)
    config_description: Mapped[str] = mapped_column(Text, nullable=True)
    exposable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


class Agencies(ConfigBase):
    __tablename__ = "agencies"
    __table_args__ = ({"schema": "config"},)

    agency_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    abbr: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    app_name: Mapped[str] = mapped_column(
        String, unique=True, nullable=False
    )  # TODO: Need to review
    profile_logo_s3_key: Mapped[str] = mapped_column(String, nullable=True)
    code: Mapped[str] = mapped_column(String, unique=True, nullable=False)


class User(ConfigBase):
    __tablename__ = "user"
    __table_args__ = ({"schema": "config"},)

    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cognito_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    first_name: Mapped[str | None] = mapped_column(Text)
    last_name: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(Text)
    is_super_admin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    @hybrid_property
    def full_name(self) -> str:
        return " ".join(filter(None, [self.first_name, self.last_name]))

    @full_name.expression
    def full_name(cls):
        return (
            func.coalesce(cls.first_name, "") + " " + func.coalesce(cls.last_name, "")
        )


class PermissionCatalog(ConfigBase):
    """One global copy of every permission code, synced from the ``Perm``
    enum (core/constants/permissions.py) by ``sync_permission_catalog``.
    Never hand-edited and never hard-deleted — a retired code is
    deactivated so existing agency.role_permission rows keep a valid FK."""

    __tablename__ = "permission_catalog"
    __table_args__ = ({"schema": "config"},)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    domain: Mapped[str] = mapped_column(Text, nullable=False)
    resource: Mapped[str] = mapped_column(Text, nullable=False)
    action: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)


class EventStream(ConfigBase):
    __tablename__ = "event_stream"

    event_stream_id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    event_channel: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[dict] = mapped_column(JSONB, nullable=False)
    agency: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    __table_args__ = (
        CheckConstraint(
            "octet_length(description::text) <= 8000",
            name="ck_event_stream_description_8kb",
        ),
        {"schema": "config"},
    )
