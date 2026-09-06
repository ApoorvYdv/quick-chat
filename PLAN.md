# Quick Chat — AI Knowledge / Vector Embeddings Plan

Status legend: `[x]` done, `[~]` partially done, `[ ]` not started.

This plan is the original spec reconciled against the actual repository state as of 2026-09-06. It references real paths — see `CHECKPOINT.md` for a compact, dated progress log to resume from.

---

## 0. Reality Check (repo inspection results)

Before any implementation, the following were inspected and confirmed:

- **AgencyBase / tenant model**: [`src/quick_chat_api/core/models/agency/agency.py`](src/quick_chat_api/core/models/agency/agency.py) — `AgencyBase` (line ~50) is the tenant-scoped declarative base; tenant isolation is via PostgreSQL schema-per-agency + `session_context()`, not a tenant_id column.
- **Business models** (already exist, do not modify): `CaseRecord`, `Criminal`, `VehicleDetail`, `PartyDetail`, `AddressDetail`, `CaseCharge`, `PaymentRecord`, `ImposedDisposition`, `ImposedSanction`, `CaseAppearance` — all in `agency.py`.
- **AI knowledge tables/models — ALREADY EXIST**:
  - Migration: [`src/quick_chat_api/migrations/agency/versions/2026_09_06_041701-9e9d5258d192_add_initial_vector_embedding_table_.py`](src/quick_chat_api/migrations/agency/versions/2026_09_06_041701-9e9d5258d192_add_initial_vector_embedding_table_.py)
  - Models: `AIKnowledgeSource` (line 678) and `AIKnowledgeChunk` (line 729) in `agency.py`
  - `EMBEDDING_DIM = 768` constant at `agency.py:47`
  - Index is **diskann** (`vectorscale` extension), not HNSW as originally specced — pgvectorscale's diskann was chosen over pgvector's native HNSW. Treat diskann as the current decision; changing it is a model/migration change requiring approval.
  - `CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE` already run in the migration (also creates base `vector` extension).
- **Embedding provider integration**: does **not** exist yet. No `EmbeddingProvider` abstraction, no LangChain/LangGraph, no Qdrant (project uses pgvector only — no separate vector store).
- **Settings**: [`src/quick_chat_api/settings/config.py`](src/quick_chat_api/settings/config.py) has DB + AWS S3 config only. No LLM/embedding provider keys yet — must be added (new dependency requires approval per `CLAUDE.md` §5).
- **Object storage**: `AWS_S3_BUCKET` exists in settings — reuse this for any raw file storage (PDFs/DOCX/etc.), do not invent a new storage mechanism.
- **Background/task queue infra**: none found yet. Embedding calls will need to run out-of-band (script/CLI or async task) — no Celery/RQ/etc. present.
- **Ingestion pipeline**: [`data_ingestion/`](data_ingestion) — `ingest_data.py`, `db.py`, `create_tables.py`, `add_uuid7_ids.py`. This is a standalone script-based pipeline (not part of the FastAPI app modules), currently used to load `data_ingestion/data/batch_1.json` into Postgres. This is where case data already landed — the embedding backfill needs to run against what this produced.
- **App layers**: `src/quick_chat_api/modules/`, `core/controllers/`, `routers/` exist as directories but currently have no embedding/retrieval-related files.

**Conclusion**: Schema/model layer for Phase 1 is done. Everything from projection → embedding → retrieval is unbuilt.

---

## 1. Objective

Build a unified retrieval/indexing system ingesting:
1. Structured PostgreSQL records (case data already ingested via `data_ingestion/`)
2. Related records/entities (parties, charges, dispositions, sanctions, appearances, payments)
3. PDFs / DOCX / TXT / images (OCR) — future case attachments

All sources normalize into the common `ai_knowledge_source` (document) + `ai_knowledge_chunk` (retrievable unit + embedding) representation. No per-entity vector tables.

---

## 2. Schema — `[x]` DONE, already migrated

`ai_knowledge_source` and `ai_knowledge_chunk` exist with the fields, indexes, and constraints originally specced (UUID PK, `case_record_id` FK w/ CASCADE, `source_metadata`/`metadata` JSONB with GIN index, `content_hash`, `status`, optimistic-lock versioning columns, unique constraint on `(source_table, source_id, source_type)` for dedupe, unique `(document_id, chunk_index)`).

Remaining schema-level gaps to confirm before building on top:
- [ ] `status` currently free-text (`Text`, default `"pending"`) — confirm the intended enum values (`PENDING/PROCESSING/COMPLETED/FAILED/DELETED/SUPERSEDED` per §"Error Handling" below) are enforced at the application layer since there's no DB-level check constraint.
- [ ] No explicit `embedding_version`/`projection_version`/`chunking_version`/`parser_version` split — currently only `embedding_model` + `embedding_version` text columns exist on `ai_knowledge_chunk`. Projection/chunking/parser versioning will need to live in `metadata` JSONB unless a model change is approved to add dedicated columns.

---

## 3. Design Principles (carry forward, unchanged)

1. Existing business tables remain the system of record — never modify files under `core/models/` without explicit approval.
2. AI knowledge tables are derived/indexed data.
3. Ingestion pipeline must be idempotent — skip re-embedding via `content_hash` comparison.
4. Use SHA-256 content hashes.
5. Store embedding model/version, and (in metadata, per §2) chunking/projection version.
6. Support incremental re-indexing and deletes/supersession via `status`.
7. Preserve source identity/lineage (`source_table`, `source_id`, `external_id`).
8. Never embed sensitive fields (SSNs, payment card numbers, etc.) unless explicitly required — check `PartyDetail`/`PaymentRecord` fields before writing projectors.
9. Prefer metadata filtering (`source_metadata`/`metadata` JSONB + B-tree indexes) over relying on embeddings to carry identifiers.
10. Never rely on vector similarity for tenant isolation — isolation is schema-based via `session_context()`, enforced before any query runs.
11. Do not hold SQL transactions open while calling external embedding APIs (see §9, Async/DB Safety).

---

## 4. Semantic Projection Layer — `[ ]` NOT STARTED

Do not directly serialize SQLAlchemy models into embeddings. Build projectors (proposed location: `src/quick_chat_api/modules/embedding/projectors/`, one file per entity or a shared module — decide based on projector complexity):

- `CaseRecordProjector` — Case Number, Case Type, Case Status, Case Title, Incident Date/Location, Issuer, Hearing info, `additional_notes`. Omit internal IDs/DB details.
- `PartyProjector`, `AddressProjector`, `ChargeProjector`, `AppearanceProjector`, `DispositionProjector`, `SanctionProjector`, `PaymentProjector`, `CriminalProjector`, `VehicleProjector` — one per model in `agency.py`.
- `DocumentProjector` — for future file-based sources (§7).

**Relationship-aware requirement**: a `ChargeProjector` should carry case context (and disposition/sanction context where relevant, via `CaseCharge.case_record` / joined data already modeled in `agency.py`). An `AppearanceProjector` should include case, hearing type/date/time, result, notes, status, legal representative — using the existing `CaseAppearance` relationship fields, not a bare dump.

Also build a **composite case summary document** (whole-case natural-language rollup spanning `CaseRecord` + its relationships) for high-level retrieval — this is the single highest-value first target given data is already ingested.

---

## 5. Database Source Adapters — `[ ]` NOT STARTED

Proposed location: `src/quick_chat_api/modules/embedding/db_adapters.py` (or one per entity if it grows large).

Each adapter: discover records → eager-load relationships (`selectinload`/`joinedload`, avoid N+1) → run through projector → compute SHA-256 `content_hash` → skip if unchanged → chunk if needed → hand off to embedding step → bulk upsert `AIKnowledgeChunk` rows.

Keep DB loading (read transaction) separate from the embedding API call — see §9.

---

## 6. File Source Adapters — `[ ]` NOT STARTED (Phase 4, later)

Common interface: `KnowledgeSource` → `NormalizedDocument`. Support PDF, DOCX, TXT, image/OCR.

Flow: `file → parser → normalized document → content cleaning → metadata enrichment → chunking → embedding → knowledge_chunk`.

- Raw binaries go to **S3** (`AWS_S3_BUCKET`, already configured in `settings/config.py`) — never store file bytes in Postgres. `ai_knowledge_source.storage_uri` holds the S3 key/URI.
- For PDFs, retain page number / section metadata in chunk `metadata` JSONB for provenance.
- Parser library choices (PDF/DOCX/OCR) are new dependencies — require approval per `CLAUDE.md` §5 when this phase starts.

---

## 7. Chunking — `[ ]` NOT STARTED

Proposed location: `src/quick_chat_api/modules/embedding/chunking.py`.

- Structured entities: generally one logical chunk per semantic unit (a case summary, a charge-with-context, an appearance-with-context) — chunking mainly matters when a projected document exceeds the embedding model's token limit.
- Large files (Phase 4): token-aware chunking, configurable size/overlap, preserve page/section metadata.
- Make chunk size/overlap configurable via `Settings`; version the chunking strategy (store in chunk `metadata`, per §2 gap).

---

## 8. Embedding Service — `[ ]` NOT STARTED

Proposed location: `src/quick_chat_api/core/llm/embedding_provider.py` (new `core/llm/` package — mirrors how `core/database/` isolates DB infra).

- Define an `EmbeddingProvider` interface: `embed_documents(texts: list[str]) -> list[list[float]]`, `embed_query(text: str) -> list[float]`.
- Implement the first concrete provider only after the provider/model is chosen and approved (see `CHECKPOINT.md` open decisions). Confirm output dimension matches `EMBEDDING_DIM = 768` in `agency.py:47`, or get approval for a migration if a different model is chosen.
- Batch embedding calls — never one API call per chunk.
- New settings needed in `Settings` (`config.py`): `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_API_KEY`, `EMBEDDING_BATCH_SIZE`.
- New SDK dependency requires explicit approval before adding.

---

## 9. Async / Database Safety — `[ ]` NOT STARTED (design rule to enforce during implementation)

Sequence for every ingestion unit:
```
DB read transaction (session_context, tenant-scoped)
  → load + project
  → commit/close session
  → call embedding API (no open transaction)
  → open new DB transaction
  → bulk upsert AIKnowledgeSource/AIKnowledgeChunk
  → commit
```
Never hold a transaction open across an external HTTP call.

---

## 10. Vector Storage & Retrieval — `[ ]` NOT STARTED

- Storage: pgvector via SQLAlchemy (already wired in the model), diskann index already migrated (§2), cosine distance ops.
- Retrieval must combine, per `.claude/rules/rag.md`:
  1. Exact/entity retrieval (case number, party name) via structured SQL on existing models.
  2. Semantic vector retrieval scoped by tenant schema + `case_record_id`/`source_types` filters — never a global unscoped vector search.
  3. Relational expansion (e.g., pull related charges/dispositions once a case is resolved).
  4. Optional reranking (later phase).
  5. Context building — dedupe, rank, respect token limits, preserve source metadata for traceability.

Proposed retrieval service signature (location: `src/quick_chat_api/modules/embedding/retrieval.py`):
```python
async def retrieve(
    session: AsyncSession,
    query: str,
    case_record_id: UUID | None = None,
    source_types: list[str] | None = None,
    top_k: int = 20,
) -> list[RetrievedChunk]: ...
```
Return chunk content, similarity score, source metadata, case metadata, document metadata — tenant scoping is implicit via the session's `session_context()`, never a parameter that could be bypassed.

Then a **context builder** (filter → dedupe → rank → respect token limits) converts results into structured LLM context — per `CLAUDE.md` §14.

---

## 11. Ingestion Service Entry Points — `[ ]` NOT STARTED

Proposed location: `src/quick_chat_api/modules/embedding/ingestion_service.py`.

```
ingest_case(case_id)
ingest_document(document_id)
reindex_case(case_id)
reindex_document(document_id)
delete_case_index(case_id)
```

Idempotent: skip re-embedding when `content_hash` + `embedding_model` + projection/chunking version are unchanged.

---

## 12. Error Handling — `[ ]` NOT STARTED

One bad document/entity must not abort a whole case's ingestion. Use `ai_knowledge_source.status` values: `PENDING`, `PROCESSING`, `COMPLETED`, `FAILED`, `DELETED`, `SUPERSEDED`. Store error detail in `source_metadata` JSONB (do not log full content — `CLAUDE.md` §20).

---

## 13. Observability — `[ ]` NOT STARTED

Log per `CLAUDE.md` §26/§20 (safe metadata only, no content/prompts): ingestion id, case id, document id, source type, chunk count, embedding model, embedding latency, parsing latency, failures/retries.

---

## 14. Tests — `[ ]` NOT STARTED

- Unit: projectors, hashing, chunking, idempotency skip logic, embedding provider (mocked), metadata generation.
- Integration: pgvector insert, similarity search, filtered/tenant-scoped search, case-level retrieval, deletion/supersession, reindexing.
- Retrieval eval fixture: example queries + expected source records (see `.claude/rules/rag.md` "important scenarios": correct case retrieval, irrelevant query, missing info, similar party names, cross-tenant isolation, empty vector results, conflicting records).

---

## 15. Migration / Rollout Order

```
Phase 1: pgvector + knowledge tables                         [x] DONE
Phase 2: CaseRecord + PartyDetail + CaseCharge + CaseAppearance projection+embedding   [ ] NOT STARTED  ← current focus
Phase 3: related entities (Criminal, VehicleDetail, AddressDetail,
         PaymentRecord, ImposedDisposition, ImposedSanction)  [ ] NOT STARTED
Phase 4: PDF/DOCX/attachments (file adapters + S3)            [ ] NOT STARTED
Phase 5: hybrid retrieval (structured + vector combined)      [ ] NOT STARTED
Phase 6: reranking / evaluation harness                       [ ] NOT STARTED
Phase 7: incremental / event-driven ingestion                 [ ] NOT STARTED
```

Do not jump ahead — Phase 2 must be working and validated (retrieval quality checked) before Phase 3 content is added, per `CLAUDE.md` §12.

---

## 16. Deliverables Checklist

- [x] Alembic migration (knowledge tables + vectorscale extension)
- [x] SQLAlchemy models (`AIKnowledgeSource`, `AIKnowledgeChunk`)
- [ ] Semantic projector framework
- [ ] DB source adapters
- [ ] File parsers/adapters (Phase 4)
- [ ] Chunking module
- [ ] Embedding provider abstraction
- [ ] Ingestion service
- [ ] Retrieval service
- [ ] Context builder
- [ ] Tests (unit + integration + retrieval eval fixture)
- [ ] CLI/script to backfill already-ingested cases (`data_ingestion/data/batch_1.json` data)
- [ ] Configuration/env variables (`Settings` additions)
- [ ] Documentation
- [ ] Sample retrieval queries

See `CHECKPOINT.md` for the live status log, open decisions, and the next concrete action.
