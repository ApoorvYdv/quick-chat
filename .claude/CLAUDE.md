# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

quick-chat is a Python 3.12 project using `uv` for dependency management. It currently centers on a `data_ingestion` pipeline that loads court-case JSON records into a Postgres (TigerCloud) database via async SQLAlchemy. Shared domain code (ORM models, enums, formatting helpers, config) lives under `quick_chat/`, which `data_ingestion` imports from.

## Commands

- Install deps: `uv sync`
- Run a script: `uv run python -m data_ingestion.<module>` (e.g. `uv run python -m data_ingestion.create_tables`)
- Create schema/tables: `uv run python -m data_ingestion.create_tables`
- Ingest data (reads all `*.json` in `data_ingestion/data/`): `uv run python -m data_ingestion.ingest_data`
- Entry point stub: `uv run python main.py`

There are no lint, type-check, or test configurations/commands set up yet.

## Environment

Requires a `.env` file (see `.env.example`):
- `DATABASE_URL` — TigerCloud/Postgres connection string, e.g. `postgresql+psycopg://user:password@host:port/dbname?sslmode=require`
- `AWS_ACCESS_KEY`, `AWS_SECRET_ACCESS_KEY`, `AWS_S3_BUCKET` — for S3 storage (not yet wired into code)

`data_ingestion/db.py` reads `DATABASE_URL` directly via `os.environ` (hard fails if unset), independent of `quick_chat/config/config.py`'s Pydantic `Settings` (which reads the same var with a soft default). These two configs are not yet unified.

Reading `.env` directly is denied by `.claude/settings.json` — use `.env.example` to see what variables exist.

## Architecture

### Package layout

- `data_ingestion/` — the ingestion pipeline and its DB engine/session setup (`db.py`). Imports domain models/enums/helpers from `quick_chat`.
- `quick_chat/core/models/models.py` — SQLAlchemy ORM models.
- `quick_chat/core/constants/constants.py` — string enums for constrained columns.
- `quick_chat/utils/helper.py` — datetime/timezone formatting helpers.
- `quick_chat/config/config.py` — Pydantic `Settings` (currently just `database_url`).

### Data model (`quick_chat/core/models/models.py`)

All ORM tables inherit from `AgencyBase` (SQLAlchemy `DeclarativeBase`), which fixes the schema name to `southern_ute` (a specific agency/tenant) and provides shared audit columns on every table: `is_active`, `created_on`, `created_by`, `modified_on`, `modified_by`, `modification_version`, `unique_reference_id` (UUIDv7). `AgencyBase.to_dict()` recursively serializes a row (and loaded relationships) to plain JSON-safe types, localizing datetimes via `quick_chat/utils/helper.py`.

Table graph, rooted at `CaseRecord`:
- `CaseRecord` (1) → `Criminal` (0/1), `VehicleDetail`*, `PartyDetail`*, `AddressDetail`* (via party), `CaseCharge`*, `CaseAppearance`*, `PaymentRecord`*, `ImposedSanction`*, `ImposedDisposition`*
- `CaseCharge` (1) → `ImposedDisposition` (0/1), `ImposedSanction`*
- `PartyDetail` (1) → `AddressDetail`*

Enums for constrained string columns (case type, charge type, party type, race, sex, hearing type, etc.) live in `quick_chat/core/constants/constants.py` and are stored as plain `Text` columns, not native Postgres enums — so new enum values don't require a migration.

### Ingestion pipeline (`data_ingestion/ingest_data.py`)

Reads JSON files shaped like `{"result": [<case>, ...]}` from `data_ingestion/data/`. For each case:
1. `build_rows()` flattens the nested case JSON into per-table row dicts, respecting `TABLE_ORDER` (parents before children — e.g. `case_record` before `case_charge` before `imposed_disposition`). Notably, charge data is merged from two places: the light `charges` list and `dispositions.charge_dispositions` (which carries full charge fields plus a nested `imposed_disposition`), keyed by charge `id`.
2. `coerce_row()` filters each dict down to known model columns and converts JSON string values to native Python types (`date`, `time`, `datetime`, `Decimal`) based on the SQLAlchemy column type.
3. `normalize_rows()` back-fills missing keys across sibling rows (using the column's Python-side default, or `None` if nullable) so a single multi-row `INSERT` can use one uniform column set.
4. `upsert()` does a Postgres `INSERT ... ON CONFLICT (id) DO NOTHING` per table.
5. `reset_sequences()` advances every table's `id` sequence past the max explicitly-inserted id, since rows are inserted with explicit ids from the source JSON rather than letting the DB assign them.

`create_tables.py` is a separate one-off script (not run automatically by ingestion) that creates the `southern_ute` schema, enables the `pg_trgm` extension (needed for the GIN trigram name-search indexes on `party_detail`), and creates all tables from `AgencyBase.metadata`.

### Timezone/formatting (`quick_chat/utils/helper.py`)

All display formatting is hardcoded to a single client locale (`America/Denver`, `MM/DD/YYYY`, 12-hour time) via `get_datetime_localization()`. Naive datetimes are assumed UTC before conversion. `date_to_localized_start_of_day`/`date_to_localized_end_of_day` convert a plain client-supplied date into a UTC-aware range bound for filtering `timestamptz` columns — use these rather than hand-rolling timezone math when querying by calendar day.
