import asyncio
import json
from datetime import UTC, date, time
from decimal import Decimal
from pathlib import Path

from dateutil.parser import parse as parse_dt
from sqlalchemy import Date, DateTime, Numeric, Time, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncConnection

from data_ingestion.db import engine
from quick_chat.core.models.models import (
    AddressDetail,
    AgencyBase,
    CaseAppearance,
    CaseCharge,
    CaseRecord,
    Criminal,
    ImposedDisposition,
    ImposedSanction,
    PartyDetail,
    PaymentRecord,
    VehicleDetail,
)

DATA_DIR = Path(__file__).parent / "data"

# Parent tables before the tables that reference them.
TABLE_ORDER = [
    "case_record",
    "criminal",
    "vehicle_detail",
    "party_detail",
    "case_charge",
    "case_appearance",
    "payment_record",
    "address_detail",
    "imposed_sanction",
    "imposed_disposition",
]

MODEL_BY_TABLE = {
    "case_record": CaseRecord,
    "criminal": Criminal,
    "vehicle_detail": VehicleDetail,
    "party_detail": PartyDetail,
    "case_charge": CaseCharge,
    "case_appearance": CaseAppearance,
    "payment_record": PaymentRecord,
    "address_detail": AddressDetail,
    "imposed_sanction": ImposedSanction,
    "imposed_disposition": ImposedDisposition,
}


def coerce_row(model, row: dict) -> dict:
    """Keep only known columns and convert JSON-native values to Python types."""
    columns = {c.name: c for c in model.__table__.columns}
    out = {}
    for key, value in row.items():
        column = columns.get(key)
        if column is None:
            continue
        if value is None:
            # Omit rather than pass explicit NULL, so a not-null column with a
            # Python-side or server-side default still gets that default applied.
            if column.nullable:
                out[key] = None
            continue

        col_type = column.type
        if isinstance(col_type, Date) and isinstance(value, str):
            value = date.fromisoformat(value)
        elif isinstance(col_type, Time) and isinstance(value, str):
            value = time.fromisoformat(value)
        elif isinstance(col_type, DateTime) and isinstance(value, str):
            value = parse_dt(value)
            if value.tzinfo is None:
                value = value.replace(tzinfo=UTC)
        elif isinstance(col_type, Numeric) and isinstance(value, str):
            value = Decimal(value)

        out[key] = value
    return out


def build_rows(case: dict) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {table: [] for table in TABLE_ORDER}
    case_id = case["id"]

    rows["case_record"].append(coerce_row(CaseRecord, case))

    if case.get("criminal"):
        rows["criminal"].append(coerce_row(Criminal, case["criminal"]))

    for vehicle in case.get("vehicles") or []:
        rows["vehicle_detail"].append(coerce_row(VehicleDetail, vehicle))

    for party in case.get("parties") or []:
        rows["party_detail"].append(coerce_row(PartyDetail, party))
        for address in party.get("addresses") or []:
            address = {**address, "case_record_id": case_id}
            rows["address_detail"].append(coerce_row(AddressDetail, address))

    # "charges" is a light list; "dispositions.charge_dispositions" carries the
    # full charge fields plus the nested imposed_disposition, keyed by charge id.
    charges_by_id = {charge["id"]: dict(charge) for charge in case.get("charges") or []}
    for charge_disposition in (
        case.get("dispositions", {}).get("charge_dispositions") or []
    ):
        charges_by_id.setdefault(charge_disposition["id"], {}).update(
            charge_disposition
        )

        imposed = charge_disposition.get("imposed_disposition")
        if imposed:
            imposed = {
                **imposed,
                "case_charge_id": charge_disposition["id"],
                "case_record_id": charge_disposition.get("case_record_id", case_id),
            }
            rows["imposed_disposition"].append(coerce_row(ImposedDisposition, imposed))

    for charge in charges_by_id.values():
        charge = {**charge, "case_record_id": case_id}
        rows["case_charge"].append(coerce_row(CaseCharge, charge))

    for hearing in case.get("hearings") or []:
        rows["case_appearance"].append(coerce_row(CaseAppearance, hearing))

    for payment in case.get("payments") or []:
        payment = {**payment, "case_record_id": case_id}
        rows["payment_record"].append(coerce_row(PaymentRecord, payment))

    for sanction in case.get("sanctions") or []:
        rows["imposed_sanction"].append(coerce_row(ImposedSanction, sanction))

    return rows


def load_rows(path: Path) -> dict[str, list[dict]]:
    data = json.loads(path.read_text())
    all_rows: dict[str, list[dict]] = {table: [] for table in TABLE_ORDER}
    for case in data.get("result", []):
        case_rows = build_rows(case)
        for table, values in case_rows.items():
            all_rows[table].extend(values)
    return all_rows


def normalize_rows(model, rows: list[dict]) -> list[dict]:
    """A single multi-row INSERT requires every row dict to share the same
    keys. Fill any row missing a key present on a sibling row with that
    column's Python-side default, or None if nullable."""
    if not rows:
        return rows

    columns = {c.name: c for c in model.__table__.columns}
    all_keys: set[str] = set()
    for row in rows:
        all_keys.update(row.keys())

    normalized = []
    for row in rows:
        filled = dict(row)
        for key in all_keys - row.keys():
            column = columns[key]
            if column.default is not None:
                arg = column.default.arg
                filled[key] = arg(None) if column.default.is_callable else arg
            elif column.nullable:
                filled[key] = None
            else:
                raise ValueError(
                    f"Row missing required value for {model.__tablename__}.{key}: {row}"
                )
        normalized.append(filled)
    return normalized


async def upsert(conn: AsyncConnection, model, values: list[dict]) -> int:
    if not values:
        return 0
    values = normalize_rows(model, values)
    stmt = pg_insert(model.__table__).values(values)
    stmt = stmt.on_conflict_do_nothing(index_elements=["id"])
    result = await conn.execute(stmt)
    return result.rowcount


async def reset_sequences(conn: AsyncConnection) -> None:
    """Advance each table's id sequence past the max explicitly-inserted id."""
    for table in AgencyBase.metadata.tables.values():
        full_name = f"{table.schema}.{table.name}" if table.schema else table.name
        await conn.execute(
            text(
                f"SELECT setval(pg_get_serial_sequence('{full_name}', 'id'), "
                f"GREATEST((SELECT COALESCE(MAX(id), 1) FROM {full_name}), 1))"
            )
        )


async def ingest_file(conn: AsyncConnection, path: Path) -> None:
    print(f"Ingesting {path.name}...")
    rows = load_rows(path)
    for table in TABLE_ORDER:
        model = MODEL_BY_TABLE[table]
        values = rows[table]
        inserted = await upsert(conn, model, values)
        skipped = len(values) - inserted
        print(f"  {table}: {inserted} inserted, {skipped} skipped (already present)")


async def main() -> None:
    files = sorted(DATA_DIR.glob("*.json"))
    if not files:
        print(f"No data files found in {DATA_DIR}")
        return

    async with engine.begin() as conn:
        for path in files:
            await ingest_file(conn, path)
        await reset_sequences(conn)

    await engine.dispose()
    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
