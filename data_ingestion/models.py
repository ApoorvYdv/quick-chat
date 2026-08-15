from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import UUID7, EmailStr
from sqlalchemy import (
    ARRAY,
    DECIMAL,
    UUID,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.hybrid import hybrid_property
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from uuid_utils.compat import uuid7

from data_ingestion.constants import (
    AddressType,
    CaseAppearanceStatus,
    CaseStatus,
    CaseTypes,
    ChargeType,
    Ethnicity,
    EyeColor,
    HairColor,
    HearingType,
    LicenseType,
    PartyType,
    Race,
    ReviewStatus,
    Sex,
    WarrantType,
)
from data_ingestion.helper import (
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
                except Exception:
                    pass

        return result

    @classmethod
    def column_names(cls):
        return {c_attr.key for c_attr in sa_inspect(cls).column_attrs}


class CaseRecord(AgencyBase):
    __tablename__ = "case_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_number: Mapped[str] = mapped_column(
        Text, nullable=False
    )  # Gin index is implemented for this

    ticket_number: Mapped[str | None] = mapped_column(
        Text, nullable=True, unique=True, index=True
    )
    ia_reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_type: Mapped[CaseTypes] = mapped_column(Text, nullable=False, index=True)

    incident_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    incident_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    incident_location: Mapped[str | None] = mapped_column(Text, nullable=True)

    issuer_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    issuer_identifier: Mapped[str | None] = mapped_column(Text, nullable=True)

    hearing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    hearing_time: Mapped[time | None] = mapped_column(Time, nullable=True)

    case_status: Mapped[CaseStatus] = mapped_column(
        Text,
        nullable=False,
        default=CaseStatus.OPEN.value,
        server_default=CaseStatus.OPEN.value,
        index=True,
    )
    is_case_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    issue_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    case_subtype: Mapped[str] = mapped_column(Text, nullable=False, index=True)

    review_status: Mapped[ReviewStatus] = mapped_column(
        Text,
        nullable=False,
        default=ReviewStatus.CLERK,
        server_default=ReviewStatus.CLERK.value,
    )
    county_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    must_appear: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    legacy_case_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    case_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    additional_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    incident_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    primary_internal_form_id: Mapped[UUID7 | None] = mapped_column(UUID, nullable=True)
    party_pretrial_plea: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_juvenile: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    is_felony: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    hearing_types: Mapped[list[HearingType]] = mapped_column(
        ARRAY(Text), default=list, nullable=True
    )

    # Every appearance (past and future) for this case
    appearance_history: Mapped[list[CaseAppearance]] = relationship(
        "CaseAppearance",
        back_populates="case_record",
        cascade="all, delete-orphan",
        uselist=True,
    )
    criminal: Mapped[Criminal | None] = relationship(
        "Criminal", uselist=False, back_populates="case_record"
    )
    vehicles: Mapped[list[VehicleDetail]] = relationship(
        "VehicleDetail",
        uselist=True,
        back_populates="case_record",
        cascade="all, delete-orphan",
        order_by="VehicleDetail.created_on.asc()",
    )
    parties: Mapped[list[PartyDetail]] = relationship(
        "PartyDetail",
        back_populates="case_record",
        cascade="all, delete-orphan",
        uselist=True,
    )
    addresses: Mapped[list[AddressDetail]] = relationship(
        "AddressDetail",
        back_populates="case_record",
        order_by="desc(AddressDetail.is_default), AddressDetail.id",
    )
    charges: Mapped[list[CaseCharge]] = relationship(
        "CaseCharge",
        back_populates="case_record",
        uselist=True,
        order_by=lambda: (
            CaseCharge.void.asc(),
            CaseCharge.created_on.desc(),
        ),
    )
    imposed_sanctions: Mapped[list[ImposedSanction]] = relationship(
        "ImposedSanction", back_populates="case_record", uselist=True
    )
    imposed_dispositions: Mapped[list[ImposedDisposition]] = relationship(
        "ImposedDisposition", back_populates="case_record", uselist=True
    )
    payment_records: Mapped[list[PaymentRecord]] = relationship(
        "PaymentRecord", back_populates="case_record", uselist=True
    )


class Criminal(AgencyBase):
    __tablename__ = "criminal"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_record_id: Mapped[int] = mapped_column(
        ForeignKey("case_record.id", name="criminal_case_record_id_fkey"),
        unique=True,
        index=True,
        nullable=False,
    )

    is_arrested: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    arrested_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    arrested_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    arrest_location: Mapped[str | None] = mapped_column(Text, nullable=True)
    warrant_type: Mapped[WarrantType | None] = mapped_column(Text, nullable=True)
    is_warrant_issued: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    warrant_issued_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    warrant_issued_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    warrant_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    observation_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="criminal"
    )


class VehicleDetail(AgencyBase):
    __tablename__ = "vehicle_detail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_record_id: Mapped[int] = mapped_column(
        ForeignKey("case_record.id", name="vehicle_details_case_record_id_fkey"),
        index=True,
        nullable=False,
    )
    vehicle_make: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_model: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_year: Mapped[str | None] = mapped_column(Text, nullable=True)
    legal_speed_rate: Mapped[str | None] = mapped_column(Text, nullable=True)
    recorded_speed_rate: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_plate: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    plate_expiration_year: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    vehicle_state_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_commercial_vehicle: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    vehicle_vin: Mapped[str | None] = mapped_column(Text, nullable=True)

    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="vehicles"
    )


class PartyDetail(AgencyBase):
    __tablename__ = "party_detail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_record_id: Mapped[int] = mapped_column(
        ForeignKey("case_record.id", name="party_detail_case_record_id_fkey"),
        index=True,
        nullable=False,
    )

    party_type: Mapped[PartyType] = mapped_column(Text, nullable=False)

    ssn_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    first_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    middle_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    suffix: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary_party: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    dob: Mapped[date | None] = mapped_column(Date, nullable=True)
    race: Mapped[Race | None] = mapped_column(Text, nullable=True)
    sex: Mapped[Sex | None] = mapped_column(Text, nullable=True)
    ethnicity: Mapped[Ethnicity | None] = mapped_column(Text, nullable=True)
    eye_color: Mapped[EyeColor | None] = mapped_column(Text, nullable=True)
    hair_color: Mapped[HairColor | None] = mapped_column(Text, nullable=True)
    height: Mapped[str | None] = mapped_column(Text, nullable=True)
    weight: Mapped[str | None] = mapped_column(Text, nullable=True)

    license_type: Mapped[LicenseType | None] = mapped_column(Text, nullable=True)
    license_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    license_state_code: Mapped[str | None] = mapped_column(Text, nullable=True)

    phone_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    email: Mapped[EmailStr | None] = mapped_column(Text, nullable=True)
    party_organization: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_license_suspended: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_license_surrendered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_commercial_license: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    is_juvenile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # CaseAttachedForm linked parties' internal id
    internal_form_id: Mapped[UUID7 | None] = mapped_column(
        UUID, nullable=True, index=True
    )

    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="parties"
    )
    addresses: Mapped[list[AddressDetail]] = relationship(
        "AddressDetail",
        back_populates="party",
        order_by="desc(AddressDetail.is_default), AddressDetail.id",
    )

    __table_args__ = (
        # GIN Trigram index
        Index(
            "idx_full_name_trgm",
            "full_name",
            postgresql_using="gin",
            postgresql_ops={"full_name": "gin_trgm_ops"},
        ),
        Index(
            "idx_first_name_trgm",
            "first_name",
            postgresql_using="gin",
            postgresql_ops={"first_name": "gin_trgm_ops"},
        ),
        Index(
            "idx_last_name_trgm",
            "last_name",
            postgresql_using="gin",
            postgresql_ops={"last_name": "gin_trgm_ops"},
        ),
        UniqueConstraint("id", "case_record_id", name="uq_party_detail_id_case_record"),
    )


class AddressDetail(AgencyBase):
    __tablename__ = "address_detail"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    party_detail_id: Mapped[int] = mapped_column(
        ForeignKey("party_detail.id", name="address_detail_party_detail_id_fkey"),
        index=True,
        nullable=False,
    )
    case_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("case_record.id", name="fk_address_detail_case_record_id"),
        nullable=False,
        index=True,
    )
    address_line_1: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_line_2: Mapped[str | None] = mapped_column(Text, nullable=True)
    city: Mapped[str | None] = mapped_column(Text, nullable=True)
    state: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(
        Boolean, server_default="false", nullable=False, default=False
    )

    address_type: Mapped[AddressType] = mapped_column(
        Text, default=AddressType.HOME.value, nullable=False
    )

    party: Mapped[PartyDetail] = relationship("PartyDetail", back_populates="addresses")
    case_record: Mapped[CaseRecord] = relationship("CaseRecord")

    @hybrid_property
    def full_address(self) -> str:
        return ", ".join(
            filter(
                None,
                [
                    self.address_line_1,
                    self.address_line_2,
                    self.city,
                    self.state,
                    self.zip_code,
                ],
            )
        )

    __table_args__ = (
        Index(
            "uq_default_address_per_party",
            "party_detail_id",
            unique=True,
            postgresql_where=text("is_default = true AND is_active = true"),
        ),
    )


class CaseCharge(AgencyBase):
    __tablename__ = "case_charge"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("case_record.id", name="case_charge_case_record_id_fkey"),
        nullable=False,
        index=True,
    )
    charge_code: Mapped[str] = mapped_column(Text, nullable=False)
    charge_type: Mapped[ChargeType | None] = mapped_column(Text, nullable=True)
    charge_description: Mapped[str] = mapped_column(Text, nullable=False)
    is_charge_closed: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    points: Mapped[int | None] = mapped_column(Integer, nullable=True)
    court_only_fine: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    void: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default=text("false")
    )
    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="charges"
    )
    imposed_disposition: Mapped[ImposedDisposition | None] = relationship(
        "ImposedDisposition",
        back_populates="case_charge",
        uselist=False,
    )
    imposed_sanctions: Mapped[list[ImposedSanction]] = relationship(
        "ImposedSanction", back_populates="case_charge", uselist=True
    )


class PaymentRecord(AgencyBase):
    __tablename__ = "payment_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_record_id: Mapped[int | None] = mapped_column(
        ForeignKey("case_record.id", name="payment_record_case_record_id_fkey"),
        index=True,
        nullable=True,
    )
    payee_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    payee_address: Mapped[str | None] = mapped_column(Text, nullable=True)
    payee_email: Mapped[str | None] = mapped_column(Text, nullable=True)

    service_fee: Mapped[Decimal] = mapped_column(
        DECIMAL(8, 2), nullable=False, default=Decimal("0.00")
    )

    payment_datetime: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(
        DECIMAL(8, 2), nullable=False, default=Decimal("0.00")
    )

    currency: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_last_4: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_brand: Mapped[str | None] = mapped_column(Text, nullable=True)
    card_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    exp_year: Mapped[str | None] = mapped_column(Text, nullable=True)
    exp_month: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_mode: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    consider_as_full: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    consider_as_full_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_window: Mapped[str | None] = mapped_column(
        Text, nullable=False, server_default="CMS_WFE"
    )
    public_reference_id: Mapped[str | None] = mapped_column(Text, nullable=True)

    reference_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    qp_payment_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    void: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    void_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # relationships
    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="payment_records"
    )


class ImposedDisposition(AgencyBase):
    __tablename__ = "imposed_disposition"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Criminal
    case_charge_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "case_charge.id",
            name="imposed_disposition_case_charge_id_fkey",
        ),
        nullable=True,
        index=True,
    )

    case_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey(
            "case_record.id",
            name="imposed_disposition_case_record_id_fkey",
        ),
        nullable=False,
        index=True,
    )

    disposition_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    finding: Mapped[str | None] = mapped_column(Text, nullable=True)
    disposed_on: Mapped[date | None] = mapped_column(Date, nullable=True)

    is_conclusive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    case_charge: Mapped[CaseCharge | None] = relationship(
        "CaseCharge", back_populates="imposed_disposition"
    )
    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="imposed_dispositions"
    )

    __table_args__ = (
        Index(
            "uq_imposed_disposition_case_charge",
            "case_record_id",
            "case_charge_id",
            unique=True,
            postgresql_where=text("case_charge_id IS NOT NULL"),
        ),
    )


class ImposedSanction(AgencyBase):
    __tablename__ = "imposed_sanction"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_record_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("case_record.id", name="imposed_sanction_case_record_id_fkey"),
        nullable=False,
        index=True,
    )
    # Criminal
    case_charge_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("case_charge.id", name="imposed_sanction_case_charge_id_fkey"),
        nullable=True,
        index=True,
    )

    sanction_type: Mapped[str] = mapped_column(Text, nullable=False)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    mark_as_completed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    is_conclusive: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    sanction_metadata: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="imposed_sanctions"
    )
    case_charge: Mapped[CaseCharge | None] = relationship(
        "CaseCharge", back_populates="imposed_sanctions"
    )


class CaseAppearance(AgencyBase):
    """
    Links cases directly to Dockets (which now include hearing info).
    """

    __tablename__ = "case_appearance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    case_record_id: Mapped[int] = mapped_column(
        ForeignKey("case_record.id", name="case_appearance_case_record_id_fkey"),
        nullable=False,
        index=True,
    )

    hearing_types: Mapped[list[HearingType]] = mapped_column(ARRAY(Text), default=list)
    hearing_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    hearing_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # ========== SECTION STATE ==========
    status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default=CaseAppearanceStatus.UNREGISTERED.value,
        index=True,
    )

    # ========== REGISTRATION FIELDS ==========
    check_in_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    legal_representative_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey(
            "party_detail.id", name="case_appearance_legal_representative_id_fkey"
        ),
        nullable=True,
        index=True,
    )
    translator_language: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ========== FTA FIELDS ==========
    fta_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    next_case_appearance_id: Mapped[int | None] = mapped_column(
        ForeignKey(
            "case_appearance.id",
            name="case_appearance_next_case_appearance_id_fkey",
        ),
        nullable=True,
        index=True,
    )

    next_case_appearance: Mapped[CaseAppearance | None] = relationship(
        "CaseAppearance",
        foreign_keys=[next_case_appearance_id],
        remote_side=[id],
    )

    # ========== RELATIONSHIPS ==========
    case_record: Mapped[CaseRecord] = relationship(
        "CaseRecord", back_populates="appearance_history", foreign_keys=[case_record_id]
    )

    legal_representative: Mapped[PartyDetail | None] = relationship(
        "PartyDetail", foreign_keys=[legal_representative_id], uselist=False
    )

    @property
    def party_pretrial_plea(self):
        """
        Proxy property for CaseRecord.party_pretrial_plea.

        Getter:
            Returns the plea from the associated CaseRecord if it has been
            loaded. Otherwise falls back to a locally cached value.

        Setter:
            Updates the associated CaseRecord when available while also
            caching the value locally. This allows callers to interact with
            the plea directly from CaseAppearance without traversing the
            CaseRecord relationship.
        """
        if "case_record" in self.__dict__ and self.case_record is not None:
            return self.case_record.party_pretrial_plea

        return getattr(self, "_party_pretrial_plea", None)

    @party_pretrial_plea.setter
    def party_pretrial_plea(self, value):
        if "case_record" in self.__dict__ and self.case_record is not None:
            self.case_record.party_pretrial_plea = value

        self._party_pretrial_plea = value

    __table_args__ = (Index("idx_case_record_id", "case_record_id"),)
