from pydantic import UUID7
from sqlalchemy import JSON, UUID, Boolean, String, Text, func, text
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import Mapped, mapped_column
from uuid_utils.compat import uuid7

from quick_chat_api.core.models import Base


class ConfigBase(Base):
    __abstract__ = True


class Config(ConfigBase):
    __tablename__ = "config"
    __table_args__ = ({"schema": "config"},)

    config_id: Mapped[UUID7] = mapped_column(
        UUID, primary_key=True, default=uuid7, server_default=text("uuidv7()")
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

    agency_id: Mapped[UUID7] = mapped_column(
        UUID, primary_key=True, default=uuid7, server_default=text("uuidv7()")
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

    user_id: Mapped[UUID7] = mapped_column(
        UUID, primary_key=True, default=uuid7, server_default=text("uuidv7()")
    )
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
