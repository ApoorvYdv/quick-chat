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

## 4. Semantic Projection Layer — `[x]` DONE for Phase 2 entities

Built at `src/quick_chat_api/modules/embedding/projectors/`, following the Interface + Registry + Factory pattern from `.claude/rules/coding-patterns.md` (mirrors `core/llm/embedding/`):

- `base.py` — `Projector[EntityT]` ABC (`project(entity) -> ProjectedDocument`) + `ProjectedDocument` (content, title, metadata).
- `exceptions.py` — `ProjectorError`, `UnknownProjectorError`.
- `registry.py` / `factory.py` — `register_projector(source_type)`, `get_projector(source_type)` (`lru_cache`d).
- `_formatting.py` — shared `field_line`/`join_lines` helpers used by every provider.
- `providers/case.py` — `CaseRecordProjector` (`source_type="case"`) — Case Number, Case Type, Case Status, Case Title, Incident Date/Location, Issuer, Hearing info, `additional_notes`. Omits internal IDs/DB details.
- `providers/party.py` — `PartyProjector` (`source_type="party"`) — excludes `ssn_id` and `license_number` (see Open Decision #4 resolution below); everything else on `PartyDetail` is projected.
- `providers/charge.py` — `ChargeProjector` (`source_type="charge"`) — relationship-aware: case context via `charge.case_record`, plus `imposed_disposition`/`imposed_sanctions` when eager-loaded.
- `providers/appearance.py` — `AppearanceProjector` (`source_type="appearance"`) — relationship-aware: case context, `legal_representative.full_name` when eager-loaded.
- `providers/case_summary.py` — `CaseSummaryProjector` (`source_type="case_summary"`) — the composite whole-case rollup, composing the four projectors above over `CaseRecord.parties`/`.charges`/`.appearance_history`, plus a non-sensitive payment aggregate (total/currency/count — never per-payment card fields).

Source types are the `AIKnowledgeSourceType` enum in `core/constants/constants.py` (`case`, `case_summary`, `party`, `charge`, `appearance`) — also the registry keys.

**Not yet built (later phases, per §15):** `AddressProjector`, `DispositionProjector`/`SanctionProjector`/`PaymentProjector` as standalone projectors (Phase 3), `CriminalProjector`/`VehicleProjector` (Phase 3), `DocumentProjector` (Phase 4).

**Relationship-loading precondition:** every relationship-aware projector guards with `"relation" in entity.__dict__` before touching it, so passing an entity where the DB adapter (§5, not yet built) did not eager-load a relationship silently omits that section rather than triggering a lazy-load/`MissingGreenlet` error in an async context. Adapters must still eager-load deliberately for correctness (an omitted section is not the same as "nothing to say").

Unit tests: `tests/modules/embedding/projectors/test_projectors.py` — PII exclusion, relationship-present/absent branches, registry unknown-key error, factory caching, case-summary composition, payment aggregation (voided payments excluded, no card fields ever appear).

---

## 5. Database Source Adapters — `[x]` DONE (Phase 2 entities)

Built at [`src/quick_chat_api/modules/embedding/db_adapters.py`](src/quick_chat_api/modules/embedding/db_adapters.py) as a single class, `CaseKnowledgeSourceAdapter`, per `.claude/rules/coding-patterns.md`'s "single class for related, non-interchangeable operations" shape (not the Interface + Registry + Factory pattern — these methods aren't swappable implementations of one interface).

- `discover_case(case_id)` / `discover_case_summary(case_id)` / `discover_parties(case_id)` / `discover_charges(case_id)` / `discover_appearances(case_id)` — one eager-loaded query each, each calling the matching projector via `get_projector(...)`.
- `discover_all(case_id)` — the method `ingest_case()` (§11) should call: one eager-loaded query covering every Phase 2 entity for a case, returning all 5 `DiscoveredEntity`s in one round trip.
- `_load_case_record_with_relations` eager-loads exactly what the relationship-aware projectors need: `parties`, `charges` (+ `imposed_disposition`, `imposed_sanctions`), `appearance_history` (+ `legal_representative`), `payment_records`. Back-populated relationships (`case_record` on each child) come for free in memory — no extra query — because SQLAlchemy sets both sides of a `back_populates` pair when the collection is loaded; only `legal_representative` (not back-populated) needs its own `selectinload`.
- Read-only by design: **does not** compute `content_hash` or touch `ai_knowledge_source`/`ai_knowledge_chunk` — it returns `DiscoveredEntity` (source_type, source_table, source_id, case_record_id, `ProjectedDocument`) value objects. Hashing, the unchanged-skip decision, and all knowledge-table writes are the ingestion service's job (§11), keeping the DB read transaction, the embedding API call, and the knowledge-table write transaction on separate sides of the §9 boundary.
- Raises module-local `CaseNotFoundError` when `case_id` doesn't resolve in the current tenant schema.

Unit tests: `tests/modules/embedding/test_db_adapters.py` — mocks `AsyncSession.execute` (no DB fixture infra exists yet, see §14) to verify each `discover_*` method's identity-building and projector dispatch, `discover_all`'s ordering/composition, and the `CaseNotFoundError` path. Real eager-loading behavior (the `selectinload` options actually preventing N+1 against Postgres) is **not** covered here — that needs an integration test against a real tenant schema, still open per §14.

---

## 6. File Source Adapters — `[ ]` NOT STARTED (Phase 4, later)

Common interface: `KnowledgeSource` → `NormalizedDocument`. Support PDF, DOCX, TXT, image/OCR.

Flow: `file → parser → normalized document → content cleaning → metadata enrichment → chunking → embedding → knowledge_chunk`.

- Raw binaries go to **S3** (`AWS_S3_BUCKET`, already configured in `settings/config.py`) — never store file bytes in Postgres. `ai_knowledge_source.storage_uri` holds the S3 key/URI.
- For PDFs, retain page number / section metadata in chunk `metadata` JSONB for provenance.
- Parser library choices (PDF/DOCX/OCR) are new dependencies — require approval per `CLAUDE.md` §5 when this phase starts.
- **Chunking for this phase is decided (2026-09-06): LangChain's `RecursiveCharacterTextSplitter` (default) and `SemanticChunker` (for narrative sections where recursive splitting alone under-serves retrieval quality) — see §7 below for the full rationale and how this plugs into the existing chunking registry.**

---

## 7. Chunking — `[x]` DONE for Phase 2 (structured entities)

Built at `src/quick_chat_api/modules/embedding/chunking/`, following the Interface + Registry + Factory pattern (mirrors `core/llm/embedding/`), per the user's explicit call to build the pluggable shape now rather than wait for a second chunker implementation (Phase 4 file chunking) to show up.

- `base.py` — `Chunker` ABC (`chunk(content, document_metadata, provider) -> list[Chunk]`), `Chunk` dataclass (content, index, token_count, metadata), `SplitReason` enum (`single_chunk`/`field_packed`/`token_window_fallback`).
- `exceptions.py` / `registry.py` / `factory.py` — `ChunkingError`, `UnknownChunkerError`, `register_chunker(name)`, `get_chunker()` (`lru_cache`d, keyed on `Settings.CHUNKING_STRATEGY`).
- `providers/structured.py` — `StructuredFieldChunker` (`"structured"`, the default): splits a projected document along the field-line boundaries the projectors already emit (`_formatting.join_lines`), greedily packing whole lines into a chunk under the token budget rather than a blind fixed-size window — a field is never truncated mid-way. Falls back to an overlapping token-window split only for a single field whose own text (e.g. a long `additional_notes`) exceeds the budget alone.
- Token budget is derived from the **real embedding-model tokenizer**, not an estimate: `EmbeddingProvider` (`core/llm/embedding/base.py`) gained `max_tokens`/`count_tokens()`, implemented in `LocalSentenceTransformerProvider` via the model's own HF tokenizer (`model.tokenizer.encode(...)`, `model.get_max_seq_length()`). `Settings.CHUNK_TOKEN_SAFETY_MARGIN` (default `0.9`) leaves headroom below the model's absolute max.
- Parent-child context: no schema change needed or added — sibling chunks already share `document_id` (+ `chunk_index`), which is sufficient for retrieval to expand a matched chunk into its full document later; each chunk's metadata carries `total_chunks` for that purpose now.
- New settings: `CHUNKING_STRATEGY` (default `"structured"`), `CHUNKING_VERSION` (default `"v1"`, stamped into every chunk's metadata per §2's gap), `CHUNK_TOKEN_SAFETY_MARGIN`, `CHUNK_OVERLAP_RATIO` (default `0.15`, used only by the token-window fallback).

Unit tests: `tests/modules/embedding/chunking/test_structured_chunker.py` (single-chunk passthrough, multi-line packing without mid-field splits, oversized-field overlapping fallback incl. a degenerate all-words-oversized termination case, metadata merge, registry/factory), `tests/core/llm/embedding/test_local_sentence_transformer.py` (`max_tokens`/`count_tokens` against a mocked tokenizer, dimension-mismatch still raises).

**Not yet built:** an actual second chunker for Phase 4 PDF/DOCX/TXT text — the registry/factory exist and are ready for it.

### Phase 4 chunking decision (2026-09-06, recorded ahead of that phase starting)

The hand-rolled `StructuredFieldChunker` above is **kept as-is** for every source type built so far (`case`, `case_summary`, `party`, `charge`, `appearance`) — it is field-boundary-aware in a way a generic text splitter cannot be, because it understands the projectors' own line format. Do not replace it or route it through a third-party splitter.

For Phase 4 (free-flowing file/PDF/DOCX text, which has no field-line structure to exploit), add new chunkers to the same registry instead of extending `StructuredFieldChunker`:

- **`RecursiveCharacterTextSplitter`** (LangChain) as the Phase 4 default — the standard production baseline for narrative/unstructured text: splits on a prioritized separator list (`\n\n`, `\n`, sentence, word) with configurable size/overlap, degrading gracefully instead of cutting mid-word. Register as `"recursive"` in `chunking/providers/`.
- **`SemanticChunker`** (LangChain, embedding-similarity-based boundary detection) as an opt-in strategy for sections where recursive splitting's fixed size/separator heuristics measurably under-serve retrieval quality (e.g. long narrative case notes/attachments with weak paragraph structure) — register as `"semantic"`. Do not default to it: it costs an embedding call per candidate boundary, which is real latency/cost `CLAUDE.md` §30 says to weigh against `"recursive"`'s near-zero cost. Adopt it per source type only after comparing retrieval quality against `"recursive"` on real Phase 4 documents, not speculatively.
- Both wrap `langchain-text-splitters` (recursive splitter has no LLM/embedding dependency; `SemanticChunker` needs an embedding call — reuse `get_embedding_provider()` via a small LangChain `Embeddings` adapter rather than a second embedding client). **New dependency (`langchain-text-splitters`, and `langchain-experimental` if `SemanticChunker` isn't in core) — needs the `uv add` approval step in `CLAUDE.md` §5 when Phase 4 implementation actually starts; this entry records the *choice*, not the install.**
- Both still return the same `Chunk` dataclass (content, index, token_count via `EmbeddingProvider.count_tokens`, metadata) and go through `get_chunker()` like `"structured"` — `Settings.CHUNKING_STRATEGY` becomes source-type-aware at that point (e.g. resolve strategy from `AIKnowledgeSourceType` for file sources vs. the existing global default for Phase 2 entities), since a single global chunking strategy stops making sense once structured and file sources coexist.
- `CHUNKING_VERSION` bumps whenever the Phase 4 default changes, per the existing versioning contract in §2/§7 above.

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
- [x] Semantic projector framework (Phase 2 entities: case, party, charge, appearance, case_summary)
- [x] DB source adapters
- [ ] File parsers/adapters (Phase 4)
- [x] Chunking module
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
