# Quick Chat — AI Knowledge / Vector Embeddings Plan

Status legend: `[x]` done, `[~]` partially done, `[ ]` not started.

This plan is the original spec reconciled against the actual repository state as of 2026-09-06. It references real paths — see `CHECKPOINT.md` for a compact, dated progress log to resume from.

**2026-09-26 update — architectural evolution decided, not yet implemented.** Everything below this notice (§0–§16) documents Phase 1–2 as actually built and is still accurate history. But the *target* architecture has changed: vector storage is moving from pgvector to **Qdrant**, and the single-path retrieval this doc's §10/§15 sketches is being replaced by a **3-agent LangGraph system** behind an orchestrator. See **"Architectural Evolution (2026-09-26): Qdrant + Multi-Agent RAG"** below for the full phased plan (Phase A–D) — that section supersedes §10 (Vector Storage & Retrieval) and §15 (Migration/Rollout Order) as the forward-looking plan. Nothing in §0–§16 has been implemented differently than described; this is a planning-only update, no code/dependency/migration changed yet.

---

## Architectural Evolution (2026-09-26): Qdrant + Multi-Agent RAG

### Why

The user requested a deliberate evolution beyond the original pgvector/single-agent design: move vector storage to Qdrant (dedicated vector DB, proper payload pre-filtering, decoupled from Postgres), replace the never-built single-path retrieval with three specialized LangGraph agents (Case Details / Procedural Hearings / Financial Details) behind an orchestrator, add DeepEval as a first-class evaluation system, and apply broader production-engineering hardening. Postgres/TigerCloud remains the system of record throughout; the LLM/vector layer is being made more production-grade, not replacing the DB as ground truth.

Repo-state findings that shaped the plan (verified this session, not assumed):
- **No retrieval module, no answer-generation endpoint, no chat/query/agent code exists anywhere.** `routers/` has exactly one file (`ingestion_router.py`). The app currently stops at ingestion.
- `langgraph`, `langgraph-supervisor`, `langgraph-checkpoint-postgres`, `langchain-core`, `anthropic`, and `openai` are **already declared in `pyproject.toml`/`uv.lock`** but zero code imports any of them — a clean slate for agent orchestration, not a refactor.
- `qdrant-client` and `deepeval` are **not present anywhere** — genuinely new dependencies, each needing the standard approval step (`CLAUDE.md` §5) when its phase starts.
- No vector-store abstraction exists — `pgvector`/`Vector(EMBEDDING_DIM)` is hardcoded directly into `AIKnowledgeChunk` (`core/models/agency/agency.py`), with no interface separating "compute the embedding" (already clean, `EmbeddingProvider`) from "store/query the vector" (not abstracted at all).
- No auth exists; tenant resolution is a single trusted `agency` header (`get_agency_header` → `RequestContext.agency`), isolation is 100% Postgres schema-per-agency (`session_context()`'s `schema_translate_map`).
- Test convention: no `conftest.py`/fixtures, no `pytest-asyncio` — hand-rolled fakes + bare `asyncio.run(...)`. Any new test in this evolution follows the same convention.

### Decisions made 2026-09-26 (all confirmed with the user)

1. **Scope for this session: plan-only.** No application code, dependencies, or migrations changed. This section is the deliverable; a future session executes Phase A against it.
2. **Qdrant hosting**: self-hosted via Docker Compose (new `qdrant` service alongside the existing Postgres/TimescaleDB container) — matches the existing local-dev pattern. Production hosting (self-managed vs. Qdrant Cloud) is a separate future decision.
3. **LLM provider**: pluggable Interface + Registry + Factory (mirrors `core/llm/embedding/`), default **Anthropic**, OpenAI registered as a second provider — both SDKs already installed.
4. **Pgvector transition: cut over, not dual-write.** `AIKnowledgeChunk.embedding` (and its `diskann` index) will be dropped once Qdrant ingestion works — approved `core/models/` change per `CLAUDE.md` §7, executed in Phase A. Everything else on `AIKnowledgeSource`/`AIKnowledgeChunk` (content, `content_hash`, dedupe constraint, cascade, `status`, `is_active`) stays — Postgres remains the lineage/content system of record, Qdrant only ever holds vectors + filter payload.
5. **Terminology mapping — CONFIRMED 2026-09-26**: `agency` is the Qdrant payload tenant field, as originally mapped. No separate "client" concept exists or is needed.
6. **LLM default for A5 — CONFIRMED 2026-09-26**: `claude-sonnet-5` via the Anthropic provider.

### Target end state

```
PostgreSQL/TigerCloud          → system of record: case data, chunk content/hash/lineage, agency registry
Qdrant                         → vector index only: embeddings + filterable payload (agency, case_record_id, source_type, ...)
core/llm/embedding/            → embedding computation (EXISTING, unchanged)
core/vectorstore/              → NEW: vector storage/query abstraction (Interface+Registry+Factory), Qdrant is the sole provider
core/llm/generation/            → NEW: LLM abstraction (Interface+Registry+Factory), Anthropic default + OpenAI provider
modules/embedding/retrieval.py → NEW: hybrid structured+vector retrieval, tenant/case pre-filtered
modules/agents/                → NEW (Phase B): Case Details / Procedural Hearings / Financial Details agents
core/orchestration/             → NEW (Phase B): LangGraph orchestrator/router, built on langgraph-supervisor
evals/                          → NEW (Phase C): DeepEval harness + datasets
Observability/hardening        → Phase D: tracing, cost/latency tracking, retries, rate limiting, etc.
```

Phases are ordered so each is independently shippable and validated against real data before the next starts — same discipline as Phase 1→2 above, per `CLAUDE.md` §12/§27.

### Phase A — Vector-store abstraction, Qdrant cutover, retrieval, single-path answer endpoint `[~]` IN PROGRESS (A1 done)

**Goal:** close the biggest actual gap first — there is currently no way to ask a question and get an answer at all. Build that end-to-end on Qdrant, behind an abstraction clean enough that Phase B's multi-agent system consumes the same building blocks without rework.

- **A1. `core/vectorstore/`** — `[x]` DONE (2026-09-26, revised same day to collection-per-agency). New pluggable subsystem, mirrors `core/llm/embedding/` exactly: `base.py:VectorStore(ABC)` (`upsert_points`, `delete_points`, `delete_by_filter`, `search` — every method takes `agency: str` explicitly), `VectorPoint`/`VectorSearchResult`/`VectorFilter` frozen dataclasses (`VectorFilter` no longer carries `agency` — see below), `exceptions.py` (`VectorStoreError`, `UnknownVectorStoreError`, `VectorStoreOperationError`), `registry.py`/`factory.py` (`get_vector_store()`, `lru_cache`d) keyed on `Settings.VECTOR_STORE_PROVIDER` (default `"qdrant"`), `providers/qdrant.py:QdrantVectorStore` (lazy `qdrant_client` import).

  **Multi-tenancy revised 2026-09-26 (same session, before A3 started): collection-per-agency, not a single shared collection + payload filter.** Originally built as one collection with a mandatory `agency` payload filter; the user weighed the two approaches (single-collection filtering vs. per-tenant collections) and chose **per-agency collections**, expecting a high number of agencies where physical isolation and simple per-tenant operations (delete/backup/resize one agency without touching others) outweigh the single-shared-index approach. Each agency gets its own collection, named `f"{Settings.QDRANT_COLLECTION_PREFIX}__{sanitized_agency}"` (`Settings.QDRANT_COLLECTION_PREFIX` replaces the old `Settings.QDRANT_COLLECTION`, default `"case_knowledge_chunks"`; agency names are lowercased and non-`[a-z0-9_-]` characters replaced with `_` for a valid collection name). Collections are created lazily on first use per agency (`_ensure_collection`, cached in an in-process `set` so existence isn't re-checked on every call) — no upfront provisioning step for a new agency. `agency` is no longer a payload field at all (the collection itself is the tenant boundary); indexed payload fields are the remaining 12: `case_record_id`, `source_type`, `source_table`, `source_id`, `document_id`, `chunk_index`, `status`, `is_active`, `embedding_model`, `embedding_version`, `chunking_strategy`, `chunking_version`. Point ID = same UUID as `AIKnowledgeChunk.id`. Vector config per collection: cosine distance, dim = `Settings.EMBEDDING_DIM`.

  Added dependency `qdrant-client` (`uv add`, approved 2026-09-26). Added `qdrant` service to `docker-compose.yml` (image `qdrant/qdrant:latest`, port 6333, volume `qdrant_data`) and `QDRANT_URL=http://qdrant:6333` to the `app` service env. New `Settings`: `VECTOR_STORE_PROVIDER`, `QDRANT_URL` (default `http://localhost:6333`), `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` (default `"case_knowledge_chunks"`). **Not added to `.env.example`** — that file is outside this session's write permissions; add the vars there manually. Tests: `tests/core/vectorstore/test_qdrant_store.py` (11 tests, mocks `qdrant_client.QdrantClient` — per-agency collection created lazily on first use and only once, different agencies map to distinct sanitized collection names, empty-list upserts/deletes never touch the client, optional case/source-type filter construction, filtered delete scoped to the right collection). All 54 repo tests pass.
- **A2. `core/models/agency/agency.py`** — **DEFERRED, not this pass (decided 2026-09-26).** User held off on dropping `AIKnowledgeChunk.embedding`/its diskann index for now. Instead: **dual-write** — ingestion writes to both pgvector and Qdrant until the user is confident enough to cut over in one clean migration later. Revisit dropping the column only when the user explicitly says so.
- **A3. `CaseIngestionService`** (`modules/embedding/ingestion_service.py`) — `[x]` DONE (2026-09-26). Dual-write wired in: `AIKnowledgeChunk.embedding` still written exactly as before, and every successfully-embedded entity's chunks are batched into `VectorPoint`s (payload: `case_record_id`, `source_type`, `source_table`, `source_id`, `document_id`, `chunk_index`, `status`, `embedding_model`, `embedding_version`, `chunking_strategy`, `chunking_version`, `is_active` — no `agency` key, per A1's collection-per-agency revision) and upserted via `get_vector_store().upsert_points(agency, points)` **after** the Postgres transaction commits (source of truth commits independently; one batched Qdrant call per `_run`, not per entity). Chunk ids are minted client-side (`uuid7()`) at chunk-construction time rather than relying on the model's flush-time default, so the same id is usable as both the Postgres PK and the Qdrant point id without an extra flush. Because `_write_embedded` does a full delete+recreate of an entity's chunks on every re-embed (chunk count/order can change), the entity's *old* chunk ids are captured before the Postgres delete and passed to `get_vector_store().delete_points(agency, stale_ids)` before the new upsert — otherwise re-embedded entities would leak orphaned vectors in Qdrant under ids nothing in Postgres references anymore. All calls to the (synchronous) `qdrant-client` SDK go through `asyncio.to_thread(...)` so the async ingestion path never blocks the event loop (`CLAUDE.md` §18). A `VectorStoreError` is caught, logged, and never fails `ingest_case`/`reindex_case` — instead every entity's `ai_knowledge_source.source_metadata["vector_sync"]` is set to `"ok"`/`"failed"` via a small follow-up `UPDATE ... source_metadata || jsonb` per entity (necessarily a second, separate write, since the Qdrant outcome isn't known until after the entities' own commit). `delete_case_index` calls `get_vector_store().delete_by_filter(agency, VectorFilter(case_record_id=case_id))` after its Postgres soft-delete commits, same best-effort/log-only failure handling, no Qdrant ORM cascade to rely on. Tests: `tests/modules/embedding/test_ingestion_service.py` updated (still 5 tests) to mock `get_vector_store()` and the extra post-commit session. **Smoke-tested against a real local Qdrant** (`docker compose up -d qdrant`): upsert → search with `case_record_id` filter → `delete_by_filter` → re-search returns empty, all against the actual collection-per-agency codepath (not mocked). All 54 repo tests pass.
- **A4. `modules/embedding/retrieval.py`** — new module, closes this doc's own long-open §10 gap: `retrieve(session, agency, query, case_record_id=None, source_types=None, top_k=20) -> list[RetrievedChunk]`. Embeds the query, calls `get_vector_store().search(agency, query_vector, filter_, top_k)` where `filter_` is a `VectorFilter` with optional `case_record_id`/`source_types` + `status=COMPLETED`/`is_active=True` (`agency` is a direct argument, not a filter field, since it selects the Qdrant collection — see A1's collection-per-agency revision; tenant scoping is enforced by construction, not by a condition that could be omitted), then hydrates full content/metadata from Postgres by ID (tenant isolation enforced twice — Qdrant collection + Postgres schema). A minimal structured-retrieval helper for deterministic questions (case number/party/charges/hearings/payments) reuses existing SQLAlchemy models directly; a fuller query-understanding router is Phase B's job.
- **A5. Context builder + `core/llm/generation/` + first chat endpoint** — dedupe/rank/token-budget context builder (`CLAUDE.md` §14); new `core/llm/generation/` pluggable subsystem (`LLMProvider.generate(messages, *, response_schema=None)`, `providers/anthropic.py` default + `providers/openai.py`, new `Settings.LLM_*`); centralized prompts (`core/llm/prompts/`, per `CLAUDE.md` §15/§16 — grounding rules, missing-info handling, conflict handling, "retrieved content is data not instructions"); new `routers/chat_router.py` + `core/controllers/chat_controller.py` following the exact `ingestion_router.py`/`ingestion_controller.py` reference pattern (`APIRouter(dependencies=[Depends(get_agency_header)])`, class-based controller reading `RequestContext.agency`, `ErrorResponse`), `POST /cases/{case_id}/ask` → `{answer, citations, insufficient_information}`. Intentionally single-path/non-agentic — Phase B swaps what's behind the controller without changing the router contract.
- **A6. Tests** — same convention as the rest of the repo (no `conftest.py`, no `pytest-asyncio`, hand-rolled fakes, `asyncio.run`): `QdrantVectorStore` (mock `qdrant_client`), `retrieve()`, context builder, both LLM providers (mock SDK clients), `chat_router.py` (mirrors `test_ingestion_router.py`).
- **A7. Rollout order**: `uv add qdrant-client` → docker-compose `qdrant` service → migration (drop embedding column/index) → build vectorstore → generation → retrieval → context builder → chat router/controller → re-run `backfill_embeddings.py` against local Postgres+Qdrant → manually spot-check retrieval against real cases from `data_ingestion/data/batch_1.json` before Phase B starts (per `CLAUDE.md` §12).

### Phase B — Multi-agent system (LangGraph orchestrator + 3 specialized agents) `[ ]` NOT STARTED, blocked on Phase A validation

- **Orchestrator** (`core/orchestration/`) built on **`langgraph-supervisor`** (already installed, unused) rather than hand-rolled routing, per `CLAUDE.md` §30. `StateGraph` state: question, agency/case scope, per-agent retrieved context, per-agent structured output, combined answer + merged citations.
- **`langgraph-checkpoint-postgres`** (already installed, unused) for state persistence/checkpointing/resumability, reusing existing Postgres infra.
- **Three agents** (`modules/agents/case_details/`, `.../procedural_hearings/`, `.../financial_details/`) — each with its own prompt, its own domain-scoped structured-query tool (different models: `CaseCharge`/`PartyDetail` vs. `CaseAppearance` vs. `PaymentRecord`/`ImposedSanction`), its own scoped `retrieve()` call, its own Pydantic output schema. Not three copies of one generic agent.
- Router/classifier decides single- vs. multi-agent fan-out; combiner merges outputs preserving per-fact provenance; hard iteration/depth cap prevents uncontrolled agent-to-agent loops.
- `chat_controller.py` swaps its internal linear retrieve→generate call for graph invocation — the Phase A router/endpoint contract does not change.
- Detailed node-by-node design deferred to a dedicated Phase-B planning session once Phase A's real retrieval quality is known.

### Phase C — Evaluation (DeepEval) `[ ]` NOT STARTED, blocked on Phase B (or at least Phase A) existing

- New dependency `deepeval` (approval step when this phase starts). Datasets built from real ingested data (`data_ingestion/data/batch_1.json`), per-domain (case/hearings/financial/cross-domain), mirroring `.claude/rules/rag.md`'s named scenarios (correct retrieval, irrelevant query, missing info, similar party names, cross-tenant isolation, empty results, conflicting records).
- Metrics: retrieval relevancy, contextual relevancy, faithfulness/groundedness, answer relevancy, hallucination, plus custom checks for tenant/case isolation and citation correctness (likely custom, not off-the-shelf DeepEval metrics).
- New `evals/` directory, runnable standalone, pluggable into CI later — kept separate from `tests/` since eval runs are slower/costlier (real LLM calls).

### Phase D — Production hardening `[ ]` NOT STARTED

Lighter detail — depends on what A–C actually need in practice. Candidates: correlation IDs extended through agent/tool spans (extend the existing `RequestIdPlugin`/`CorrelationIdPlugin`, don't replace); LLM cost/token/latency tracking centralized in `core/llm/generation/`; retries/backoff on LLM and Qdrant calls; rate limiting (evaluate need before adding a dependency); a security review pass on agent tool boundaries once they exist (agent tools must not bypass `agency` scoping — this one is a hard correctness requirement, should land at the end of Phase B, not be deferred indefinitely).

### What does NOT change

`core/llm/embedding/`, `modules/embedding/{db_adapters,projectors,chunking}.py`, the `AIKnowledgeSource`/`AIKnowledgeChunk` tables (minus the one column/index), the tenant isolation mechanism (`session_context()`, `RequestContext`, `get_agency_header` — Qdrant's `agency` payload filter is an *additional* layer, not a replacement), and the router/controller/`ErrorResponse`/`RequestContext` wiring pattern.

### Flagged in passing (not part of this plan, worth a separate look later)

- `CLAUDE.md` §24 describes ingestion as ending in `reset_sequences()` — this function does not exist anywhere in the codebase; stale doc relative to `data_ingestion/ingest_data.py`'s actual UUID-based implementation.
- `config.agencies`/`config.config`/`config.user`'s Alembic migration defines their PKs as `Integer` (serial), but the current SQLAlchemy models declare them as `UUID` — no reconciling migration has landed. Not blocking for Phase A/B (they don't touch these tables), but a latent inconsistency.

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

**`case_record_id` pre-filtering (recorded 2026-09-07, not yet implemented):** most `ai_knowledge_chunk` rows are scoped to a single case, so when `case_record_id` is provided, filter in SQL, in the same query as the similarity search — never a global ANN search followed by a Python-side filter (`.claude/rules/rag.md`):
```python
stmt = (
    select(AIKnowledgeChunk)
    .where(AIKnowledgeChunk.case_record_id == case_record_id)
    .order_by(AIKnowledgeChunk.embedding.cosine_distance(query_vector))
    .limit(top_k)
)
```
- `case_record_id` already has its own standalone btree index (`ix_ai_knowledge_chunk_case_id`); the diskann index (§2) is a separate, single-column index on `embedding` only — there is no composite/partial index combining the two today.
- Before assuming the standalone indexes are sufficient, check the query plan (`EXPLAIN ANALYZE`) once real data volume exists: confirm Postgres/pgvectorscale pushes the `case_record_id` filter down into (or ahead of) the diskann ANN search rather than doing a full ANN scan and filtering the result. DiskANN is graph-based (unlike ivfflat's bucket partitioning), so it tends to tolerate prefiltering better, but this needs to be verified against real data, not assumed.
- If plan inspection shows the filter isn't pushed down efficiently at scale, the fallback is a partial diskann index scoped to hot case_record_ids — do not add this speculatively; only after profiling shows it's needed, and only with approval since it touches the migration.

Then a **context builder** (filter → dedupe → rank → respect token limits) converts results into structured LLM context — per `CLAUDE.md` §14.

---

## 11. Ingestion Service Entry Points — `[x]` DONE for case-level entry points

Built at [`src/quick_chat_api/modules/embedding/ingestion_service.py`](src/quick_chat_api/modules/embedding/ingestion_service.py) as `CaseIngestionService(engine, agency)`:

```
ingest_case(case_id)          # skips entities whose content_hash + indexing_key are unchanged
reindex_case(case_id)         # force re-embed, ignoring the skip check
delete_case_index(case_id)    # soft-delete: status=DELETED, is_active=False, purges chunks
```

`ingest_document(document_id)` / `reindex_document(document_id)` (single-entity granularity) are **not built** — `CaseKnowledgeSourceAdapter` only discovers at case granularity (`discover_all`, plus per-type `discover_parties`/etc. returning *all* of that type), so a single-entity entry point would need a new adapter method first. Deferred until a real use case needs it.

Idempotency key: `content_hash` (SHA-256 of `ProjectedDocument.content`) **and** an `indexing_key` (`EMBEDDING_PROVIDER|EMBEDDING_MODEL|EMBEDDING_VERSION|CHUNKING_STRATEGY|CHUNKING_VERSION`, stored in `source_metadata["indexing_key"]`) — both must match the existing row for an entity to be skipped, so a model/chunking change triggers re-embedding even with byte-identical content.

Transaction safety (`PLAN.md` §9): one read session (discovery + existing-row lookup) closed before any embedding call; one separate write session for all persistence, committed once at the end.

Failure isolation (`PLAN.md` §12): each entity's chunk/embed call is wrapped individually; a failure marks that entity's `ai_knowledge_source` row `FAILED` with `source_metadata.error` (its last-known-good chunks, if any, are left untouched) and the rest of the case continues. Each entity's DB write also runs in its own `SAVEPOINT` (`session.begin_nested()`) so one row's write failure doesn't abort the whole write transaction.

`status` enforcement: application-level only via the new `AIKnowledgeStatus` enum (`core/constants/constants.py`) — no DB check constraint, per the user's explicit call (§2's open gap, now resolved).

Exposed via both a controller/router (`core/controllers/ingestion_controller.py`, `routers/ingestion_router.py` — `POST /cases/{case_id}/index/reindex`, `DELETE /cases/{case_id}/index`) and a standalone backfill script (`data_ingestion/backfill_embeddings.py`), per the user's explicit call to build both now rather than one now/one later.

Tenant resolution for the new endpoints follows the app's now-standard router/controller pattern (`.claude/rules/architecture.md` "Router + Controller wiring pattern"): `APIRouter(..., dependencies=[Depends(get_agency_header)])` (`utils/dependencies.py`) validates the `agency` request header against `config.agencies` and writes it into `RequestContext.agency` (`utils/context.py`, backed by `starlette_context` — middleware wired in `main.py`). `IngestionController` (class-based, constructed via `Depends()`) reads `RequestContext.agency` in `__init__` rather than receiving it as a parameter — this is the only tenant-resolution mechanism in the app today (no auth middleware exists yet); meant to be swapped for real auth-derived resolution later without changing the controller/module layers beneath it. All client-facing errors here (`ErrorResponse.AGENCY_NOT_FOUND`, `.CASE_NOT_FOUND`, `.CLIENT_NOT_PROVIDED`) go through the new unified `core/constants/error_response.py:ErrorResponse`.

Unit tests: `tests/modules/embedding/test_ingestion_service.py` — skip-unchanged, new-entity embed, forced reindex of an otherwise-unchanged entity, per-entity failure isolation (one bad entity doesn't block others), soft-delete.

**Bug fixed in passing:** `core/database/connections.py` had a broken import (`quick_chat_api.database.config` instead of `quick_chat_api.core.database.config`) — never caught because nothing imported it before this router needed `get_async_engine()`.

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
Phase 2: CaseRecord + PartyDetail + CaseCharge + CaseAppearance projection+embedding   [~] CODE DONE, not yet run against real DB  ← current focus
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
- [x] Embedding provider abstraction
- [x] Ingestion service (case-level; document-level deferred)
- [ ] Retrieval service
- [ ] Context builder
- [ ] Tests (unit + integration + retrieval eval fixture)
- [x] CLI/script to backfill already-ingested cases (`data_ingestion/backfill_embeddings.py`) — not yet run against a real DB
- [ ] Configuration/env variables (`Settings` additions)
- [ ] Documentation
- [ ] Sample retrieval queries

See `CHECKPOINT.md` for the live status log, open decisions, and the next concrete action.
