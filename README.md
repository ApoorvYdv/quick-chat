# Quick Chat

A RAG backend for querying court/case data in natural language. FastAPI +
PostgreSQL (Tiger Cloud) as the source of truth, pgvector/Qdrant for
semantic retrieval, LLM for grounded answer generation. See `CLAUDE.md` for
the full architecture and engineering rules.

## Setup

```bash
uv sync
cp .env.example .env   # then fill in the values below
```

### Environment variables (`.env`)

| Variable | Description |
|---|---|
| `DB_USERNAME`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT`, `DB_NAME` | Postgres (Tiger Cloud) connection |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | SQLAlchemy async connection pool sizing |
| `AWS_S3_BUCKET` | S3 bucket used for file storage |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIM`, `EMBEDDING_BATCH_SIZE`, `EMBEDDING_DEVICE`, `EMBEDDING_API_KEY`, `EMBEDDING_VERSION` | Embedding provider config |
| `VECTOR_STORE_PROVIDER`, `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` | Qdrant vector store config |
| `CHUNKING_STRATEGY`, `CHUNKING_VERSION`, `CHUNK_TOKEN_SAFETY_MARGIN`, `CHUNK_OVERLAP_RATIO` | Chunking config for embedding ingestion |

`.env.example` is kept in sync with `src/quick_chat_api/settings/config.py` —
if you add a new `Settings` field, add it there too.

## Running the API

```bash
uv run fastapi dev src/quick_chat_api/main.py
```

## Data ingestion

Case data lives as JSON files under `data_ingestion/data/` and is loaded in
stages:

Every stage takes `--agency <schema_name>` — tables live in a per-agency
Postgres schema (e.g. `southern_ute`), never `public`, since schema names
must never be hardcoded (`CLAUDE.md` §8). Model metadata's schema is `None`;
the real schema is only applied at runtime via `schema_translate_map`.

**1. Create the agency schema + tables** (first time only, or after a schema
change):

```bash
uv run python -m data_ingestion.create_tables --agency <schema_name>
```

**2. Ingest case data into Postgres** (no embeddings):

```bash
uv run python -m data_ingestion.ingest_data --agency <schema_name>
```

Loads every `*.json` file in `data_ingestion/data/`, and inserts rows in
FK-safe order (`case_record` → `criminal`/`vehicle_detail`/`party_detail` →
`case_charge`/`case_appearance`/`payment_record`/`address_detail` →
`imposed_sanction`/`imposed_disposition`), skipping rows that already exist
(`ON CONFLICT DO NOTHING` on `id`).

**3. Backfill embeddings / vector store** (separate step, run after data is
in Postgres):

```bash
uv run python -m data_ingestion.backfill_embeddings --agency <schema_name>
```

## Tests

```bash
uv run pytest
```
