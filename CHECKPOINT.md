# Checkpoint — AI Knowledge / Vector Embeddings

Living progress log for the work described in `PLAN.md`. Update this file at the end of each work session so it can be picked back up cold. Newest entry on top.

---

## 2026-09-13 — Session: standardized router/controller pattern, RequestContext, unified ErrorResponse

**Done this session (user-driven refactor of the router/controller built 2026-09-06, plus this session's own cleanup/docs):**
- The user replaced the plain-function tenant dependency (`get_agency_schema` reading `X-Agency-Schema`) with the pattern now documented as the app standard:
  - `utils/context.py:RequestContext` — a typed, property-based facade over `starlette_context`'s per-request `ContextVar` (`agency`, `config`, `user_details`, `case_types`). Added `starlette_context` as a dependency (`pyproject.toml`) and `RawContextMiddleware` to `main.py`.
  - `utils/dependencies.py:get_agency_header` — reads a plain `agency` request header, validates it against `config.agencies` (`Agencies.name`) via `validate_active_agency`, and writes it into `RequestContext.agency`. Declared once on the router (`APIRouter(..., dependencies=[Depends(get_agency_header)])`), not per-endpoint.
  - `core/controllers/ingestion_controller.py:IngestionController` — now a class, constructed via FastAPI's class-based `Depends()` (`engine: Annotated[AsyncEngine, Depends(get_async_engine)]` in `__init__`), reading `self.agency = RequestContext.agency` instead of receiving `agency` as a method parameter. Endpoints in `routers/ingestion_router.py` now take `controller: Annotated[IngestionController, Depends()]`.
  - `core/constants/error_response.py:ErrorResponse` — added by the user as the single home for client-facing (4xx) message strings, starting with `CLIENT_NOT_PROVIDED`.
- This session's work on top of that:
  - Documented the pattern as mandatory for every future route: `.claude/rules/architecture.md` gained "Router + Controller wiring pattern (concrete)", "Request Context", and "Error Responses" sections, each pointing at `ingestion_router.py`/`ingestion_controller.py` as the reference implementation (mirrors how `coding-patterns.md` points at `core/llm/embedding/`). `CLAUDE.md`'s Controller section gained a one-paragraph pointer to it.
  - Extended `ErrorResponse` with `AGENCY_NOT_FOUND` and `CASE_NOT_FOUND`, and replaced every remaining inline literal client-facing error string with a reference to it: `utils/dependencies.py`'s hardcoded `"Agency not found"`, and `routers/ingestion_router.py`'s `detail=str(exc)` (which leaked the internal `CaseNotFoundError` message, e.g. `case_id=... not found`) now `detail=ErrorResponse.CASE_NOT_FOUND`.
  - Fixed two inconsistent imports the user's edit introduced (`from src.quick_chat_api.utils....` instead of `from quick_chat_api.utils....`) in `routers/ingestion_router.py` and `core/controllers/ingestion_controller.py` — these happened to still resolve (Python 3 implicit namespace packages + `pythonpath = ["src", "."]` in `pyproject.toml`), but were inconsistent with every other import in the codebase and fragile outside that exact `sys.path` setup.
  - Added `tests/routers/test_ingestion_router.py` (6 tests, first test in a new `tests/routers/` dir) — missing/empty agency header, unknown agency, successful reindex delegating to the controller, case-not-found mapping to the unified `ErrorResponse.CASE_NOT_FOUND`, delete-index delegation. Mocks `utils.dependencies.validate_active_agency` and `IngestionController` methods directly (same mocking style as the rest of the suite) rather than hitting a real DB. All 43 tests in the repo pass (`uv run pytest`).
- Updated `PLAN.md` §11's tenant-resolution paragraph to describe the pattern actually kept, and corrected the 2026-09-06 `CHECKPOINT.md` entry's now-stale description (pointer added rather than rewriting history).

**Decisions made:**
- User's own call, not asked this session: class-based controller DI + `RequestContext` + unified `ErrorResponse` — adopted as-is and generalized into a documented pattern rather than treated as one-off.
- `ErrorResponse` messages stay generic (no interpolated case/agency IDs) per the new architecture.md rule — request-specific detail belongs in server-side logs, not the client-facing `detail` string.

**New open questions:**
- None new. Same three from the prior entry remain open: prod embedding provider/model, real auth-derived tenant resolution (this session hardened the *placeholder*, didn't replace it), and single-entity (`ingest_document`/`reindex_document`) granularity.
- Still not run against a real Postgres DB — unchanged from the prior entry.

**Next concrete action:**
- Unchanged from the prior entry: run `data_ingestion/backfill_embeddings.py --agency <schema>` against the real DB, spot-check, then move to retrieval (`PLAN.md` §10) — not Phase 3, per `CLAUDE.md` §12.
- When retrieval's router/controller is built, it must follow the same pattern documented in `.claude/rules/architecture.md` (class-based controller, `RequestContext`, `ErrorResponse`) rather than re-deriving its own shape.

---

## 2026-09-06 — Session: ingestion service + router/controller + backfill script (Phase 2, PLAN.md §11)

**Done this session:**
- Built `CaseIngestionService` at [`src/quick_chat_api/modules/embedding/ingestion_service.py`](src/quick_chat_api/modules/embedding/ingestion_service.py): `ingest_case(case_id)`, `reindex_case(case_id)` (force re-embed), `delete_case_index(case_id)` (soft-delete). Wires together `CaseKnowledgeSourceAdapter.discover_all` → SHA-256 `content_hash` + an `indexing_key` fingerprint (provider/model/version + chunking strategy/version) → skip-if-unchanged → `get_chunker().chunk(...)` → `get_embedding_provider().embed_documents(...)` → a separate write transaction that upserts `AIKnowledgeSource`/`AIKnowledgeChunk` via `INSERT ... ON CONFLICT DO UPDATE` on the existing dedupe unique constraint.
- Transaction/embedding-call separation per `PLAN.md` §9: one read session (discovery + existing-row lookup) closed before any embedding call, one separate write session for everything else.
- Per-entity failure isolation per `PLAN.md` §12: each entity's chunk/embed call and DB write (the latter in its own `SAVEPOINT` via `session.begin_nested()`) are isolated — one bad entity is recorded as a `FAILED` `ai_knowledge_source` row with the error in `source_metadata` (never content), and does not stop the rest of the case. A failed re-embed attempt leaves that entity's last-known-good chunks untouched rather than deleting them.
- Added `AIKnowledgeStatus` `StrEnum` (`core/constants/constants.py`) enforcing `PENDING/PROCESSING/COMPLETED/FAILED/DELETED/SUPERSEDED` at the application layer only (resolves Open Decision #5 below) — no DB check constraint, no model change.
- Added `Settings.EMBEDDING_VERSION` (default `"v1"`) — was missing; needed as the `ai_knowledge_chunk.embedding_version` value and as part of the `indexing_key`.
- Built the first router/controller in the app: `core/controllers/ingestion_controller.py`, `routers/ingestion_router.py` (`POST /cases/{case_id}/index/reindex?force=`, `DELETE /cases/{case_id}/index`), wired into `main.py`. Initial tenant resolution was a plain function dependency reading an `X-Agency-Schema` header — **superseded the same day**, see the entry above this one for the pattern actually kept (`get_agency_header` + `RequestContext`, plain `agency` header).
- Built `data_ingestion/backfill_embeddings.py` — CLI (`--agency`, optional `--case-id`, `--force`) looping `ingest_case`/`reindex_case` over every `CaseRecord` in one agency schema, per PLAN.md §16's backfill deliverable.
- **Bug fix (pre-existing, unrelated to this session's feature but blocking it):** `core/database/connections.py` imported `quick_chat_api.database.config` (module doesn't exist) instead of `quick_chat_api.core.database.config`. Never caught because nothing imported `connections.py` before this router needed `get_async_engine()`. Fixed the one-line import; did not touch anything else in that file.
- Added `tests/modules/embedding/test_ingestion_service.py` (5 tests: skip-unchanged, new-entity embed, forced reindex of unchanged content, per-entity failure isolation, soft-delete) — mocks `session_context`/`CaseKnowledgeSourceAdapter`/`get_embedding_provider`/`get_chunker`, same style as `test_db_adapters.py`. Verified the FastAPI app builds and both routes register (`TestClient(app).get("/openapi.json")`) and did a mocked end-to-end `TestClient` POST against `/cases/{id}/index/reindex` with `app.dependency_overrides`. All 37 tests in the repo pass (`uv run pytest`).

**Decisions made (asked via AskUserQuestion, all three resolved this session):**
1. `status` enforcement: app-level `StrEnum` only, no migration/check constraint — user's explicit call, avoids a `core/models/` change for this phase.
2. Failure granularity: isolate per entity (one bad entity → `FAILED` row + continue; not abort-the-whole-case).
3. Entry point: **both** a router/controller (not deferred) and a standalone backfill script, built together this session rather than router-later.

**New open questions:**
- Open Decision #1 (prod embedding provider/model, still `local`/`sentence-transformers` today) remains open.
- Tenant resolution (now via `get_agency_header`/`RequestContext`, see the entry above) is explicitly a placeholder — real auth-derived tenant resolution is a future replacement, not yet designed.
- `ingest_document(document_id)`/`reindex_document(document_id)` (single-entity granularity, named in `PLAN.md` §11's original spec) were **not** built — `CaseKnowledgeSourceAdapter` has no discover-by-source-id method yet; deferred until a real caller needs single-entity re-indexing instead of whole-case.
- Still not run against a real Postgres DB — all tests mock `session_context`/`AsyncSession`. The backfill script and the two new endpoints are code-complete but unverified against TigerCloud.

**Next concrete action:**
- Run `data_ingestion/backfill_embeddings.py --agency <schema>` against the real DB where `ingest_data.py`'s data already landed, spot-check a few `ai_knowledge_chunk` rows and re-run it once to confirm the skip-unchanged path actually skips (no duplicate embedding calls).
- Only after that manual validation, move to retrieval (`PLAN.md` §10) — do not start Phase 3 entities or retrieval before this, per `CLAUDE.md` §12 and `PLAN.md` §15.

---

## 2026-09-06 — Session: Phase 4 chunking decision recorded (no code yet)

**Done this session:**
- Documentation-only: recorded the user's decision for Phase 4 (file/PDF/DOCX chunking, `PLAN.md` §6) ahead of that phase starting. No code changed — Phase 4 hasn't begun and `StructuredFieldChunker` remains untouched and is the only registered chunker today.

**Decision made:**
- Keep the hand-rolled `StructuredFieldChunker` (`PLAN.md` §7) for every source type built so far (`case`, `case_summary`, `party`, `charge`, `appearance`) — it stays because it's field-boundary-aware in a way no generic splitter can be, not because of inertia.
- For Phase 4 free-text file/PDF chunking, use LangChain: `RecursiveCharacterTextSplitter` as the default (`"recursive"` in the chunking registry), `SemanticChunker` as an opt-in strategy (`"semantic"`) for sections where recursive splitting measurably under-serves retrieval quality — not a blanket default, given its per-boundary embedding-call cost. Full rationale, dependency note, and integration shape written into `PLAN.md` §6/§7.
- This is a **new dependency decision, not yet an install** — `langchain-text-splitters` (+ possibly `langchain-experimental` for `SemanticChunker`) still needs the actual `uv add` approval step per `CLAUDE.md` §5 when Phase 4 implementation starts. Naming the library now is the user's approval-in-principle for *which* library; the dependency-addition step itself happens at implementation time.
- Both future chunkers plug into the existing `chunking/registry.py`/`factory.py` from this session's earlier work — no rework needed there. `Settings.CHUNKING_STRATEGY` will need to become source-type-aware once file sources coexist with Phase 2 structured entities (flagged in `PLAN.md` §7, not resolved yet).

**New open questions:**
- None new for Phase 2/current work. For Phase 4 (not started): the exact chunk size/overlap defaults for `RecursiveCharacterTextSplitter`, and the criteria for when a source type should use `"semantic"` over `"recursive"`, are left open until real Phase 4 documents exist to evaluate against — do not guess these numbers speculatively per `CLAUDE.md` §12.

**Next concrete action:**
- Unchanged from the entry below — this session only updated planning docs. Still: build `ingest_case(case_id)` (`PLAN.md` §11) using the existing `"structured"` chunker, then the backfill script, before touching Phase 3 or Phase 4.

---

## 2026-09-06 — Session: chunking module (Phase 2, PLAN.md §7)

**Done this session:**
- Built the chunking subsystem at `src/quick_chat_api/modules/embedding/chunking/` as a full Interface + Registry + Factory package (`base.py`, `exceptions.py`, `registry.py`, `factory.py`, `providers/structured.py`) — user's explicit call to build the pluggable shape now, ahead of Phase 4 needing a second (recursive/semantic) chunker, rather than starting with a single plain module per the usual YAGNI default in `coding-patterns.md`.
- `StructuredFieldChunker` (`"structured"`, the default): greedily packs whole projector field-lines into a chunk under a token budget — never truncates a field mid-way. Falls back to an overlapping token-window split only when a single field's own text (e.g. a long `additional_notes`) alone exceeds the budget.
- Extended `EmbeddingProvider` (`core/llm/embedding/base.py`) with `max_tokens` (property) and `count_tokens(text)`, implemented in `LocalSentenceTransformerProvider` using the model's real HF tokenizer (`model.tokenizer.encode(...)`) and `model.get_max_seq_length()` — chunking sizes against the model's actual limit, not an estimate, and picks up whichever provider is active without change.
- Parent-child context expansion: resolved to *not* need any schema/model change — `ai_knowledge_chunk.document_id` + `chunk_index` (already in the schema) are sufficient for retrieval to later expand a matched chunk to its full sibling set; each chunk's metadata now carries `total_chunks` to support that.
- New settings: `CHUNKING_STRATEGY` (default `"structured"`), `CHUNKING_VERSION` (default `"v1"` — resolves the `chunking_version` part of PLAN.md §2's versioning gap by stamping it into every chunk's `metadata`), `CHUNK_TOKEN_SAFETY_MARGIN` (default `0.9`), `CHUNK_OVERLAP_RATIO` (default `0.15`).
- Added `tests/modules/embedding/chunking/test_structured_chunker.py` (11 tests: single-chunk passthrough, multi-line packing without mid-field splits, oversized-field overlapping-window fallback incl. a degenerate "every word alone exceeds budget" termination case, metadata merge, registry/factory) and `tests/core/llm/embedding/test_local_sentence_transformer.py` (4 tests: `max_tokens`/`count_tokens` against a mocked tokenizer via `sys.modules` injection — no real model download — plus the pre-existing dimension-mismatch behavior). All 32 tests in the repo pass (`uv run pytest`).

**Decisions made (asked via AskUserQuestion, all four resolved this session):**
1. Chunker shape: full Interface + Registry + Factory now, not deferred to a second implementation.
2. Oversized-document split strategy: structure-aware greedy field-line packing, not a generic fixed-size sliding window.
3. Token counting: the real `EmbeddingProvider` tokenizer (new `max_tokens`/`count_tokens` on the interface), not a chars/4-style estimate.
4. Parent-child context expansion: build it now — but it turned out to need zero new columns/metadata scheme beyond `total_chunks`, since `document_id`/`chunk_index` already provide the linkage.

**New open questions:**
- None new. Open Decisions #1 (prod embedding provider/model) and #2 (new SDK dependency) remain open from prior sessions.
- Fixed one bug during implementation, not left open: the token-window fallback's overlap arithmetic could stall (`start` not advancing) when a single word alone meets/exceeds the budget; guarded with `start = max(start + 1, end - overlap_words)` and covered by the degenerate-case test above.

**Next concrete action:**
- Build the minimal `ingest_case(case_id)` path (`PLAN.md` §11): `CaseKnowledgeSourceAdapter.discover_all(case_id)` → close read session → compute SHA-256 `content_hash` per `DiscoveredEntity` → skip unchanged vs existing `AIKnowledgeSource` rows → `get_chunker().chunk(document.content, document.metadata, get_embedding_provider())` → `get_embedding_provider().embed_documents([...])` (no open transaction) → new DB transaction → bulk upsert `AIKnowledgeSource`/`AIKnowledgeChunk` (`token_count` from `Chunk.token_count`) → commit. See `PLAN.md` §9 for the transaction/embedding-call sequencing.
- Then a one-off backfill script over every already-ingested `CaseRecord`, spot-check retrieval quality manually, and only then move to Phase 3 per `PLAN.md` §15.

---

## 2026-09-06 — Session: DB source adapters (Phase 2, PLAN.md §5)

**Done this session:**
- Built `CaseKnowledgeSourceAdapter` at [`src/quick_chat_api/modules/embedding/db_adapters.py`](src/quick_chat_api/modules/embedding/db_adapters.py): `discover_case`/`discover_case_summary`/`discover_parties`/`discover_charges`/`discover_appearances` (one eager-loaded query each) plus `discover_all` (single eager-loaded query, all 5 `DiscoveredEntity`s) — the method `ingest_case()` should call next.
- Adapter is read-only: returns `DiscoveredEntity` value objects (source identity + `ProjectedDocument`), never computes `content_hash` and never touches `ai_knowledge_source`/`ai_knowledge_chunk` — that's left to the ingestion service (§11) per the user's explicit call this session.
- Added `tests/modules/embedding/test_db_adapters.py` (7 tests, mocked `AsyncSession`) — identity-building per entity type, `discover_all` ordering/composition, `CaseNotFoundError` on a missing case. All 21 tests in the repo pass (`uv run pytest`).
- Updated `.claude/rules/coding-patterns.md` with a new documented shape: "single class for related, non-interchangeable operations" (one class, one file, no registry/factory/base.py) — for subsystems like this one where the methods are complementary operations, not swappable strategies. `db_adapters.py` is now that pattern's reference implementation, alongside `core/llm/embedding/` for the pluggable-subsystem pattern.

**Decisions made:**
- Structure: plain module with one class (`CaseKnowledgeSourceAdapter`), not Interface + Registry + Factory — user's explicit call after being asked, since these methods aren't interchangeable implementations of one interface. Documented as a named pattern rather than a one-off exception (see coding-patterns.md update above).
- Hash/skip ownership: adapters are read-only (discover + project only); the ingestion service (§11, not yet built) owns `content_hash` computation, the unchanged-skip comparison against existing `AIKnowledgeSource` rows, and all writes.
- Scope: all 5 Phase 2 source types (`case`, `case_summary`, `party`, `charge`, `appearance`) covered now, not just `case`/`case_summary`.
- Eager-load depth: full depth in one query via `_load_case_record_with_relations` — `parties`, `charges`+disposition+sanctions, `appearance_history`+`legal_representative`, `payment_records` — so every relationship-aware projector branch gets exercised against real (if still test-mocked) data instead of degrading to "omit section".

**New open questions:**
- None new. Open Decisions #1 (prod embedding provider/model) and #2 (new SDK dependency) remain open from prior sessions; the `EMBEDDING_DIM` 1536→768 migration is still pending on the user's side (see prior entry below).
- No real DB/integration test fixture exists yet — this session's tests mock `AsyncSession.execute`, so the `selectinload` options in `_load_case_record_with_relations` are exercised for shape/dispatch logic only, not verified against a real Postgres tenant schema for actual N+1 avoidance. Flagged in `PLAN.md` §5 and still open under §14.

**Next concrete action:**
- Build the chunking step (`PLAN.md` §7) — likely a passthrough (one chunk per projected document) for Phase 2, unless a `case_summary` document exceeds the embedding model's token limit.
- Build the minimal `ingest_case(case_id)` path (`PLAN.md` §11): call `CaseKnowledgeSourceAdapter.discover_all(case_id)` → close the read session → compute `content_hash` per `DiscoveredEntity` → compare against existing `AIKnowledgeSource` rows to skip unchanged → `get_embedding_provider().embed_documents(...)` (no open transaction) → new DB transaction → bulk upsert `AIKnowledgeSource`/`AIKnowledgeChunk` → commit.
- Once `ingest_case()` works end-to-end against real ingested data, add an integration test against a real tenant schema (or at least a real Postgres test DB) to actually verify the eager-loading avoids N+1, before moving to Phase 3.

---

## 2026-09-06 — Session: semantic projection layer (Phase 2, PLAN.md §4)

**Done this session:**
- Built the full projector subsystem at `src/quick_chat_api/modules/embedding/projectors/`, following the Interface + Registry + Factory pattern (`base.py`, `exceptions.py`, `registry.py`, `factory.py`, `_formatting.py` shared helper, `providers/`).
- Implemented 5 projectors covering all of Phase 2: `CaseRecordProjector` (`case`), `PartyProjector` (`party`), `ChargeProjector` (`charge`, relationship-aware — case + disposition/sanction context), `AppearanceProjector` (`appearance`, relationship-aware — case + legal representative), `CaseSummaryProjector` (`case_summary`, composite whole-case rollup that composes the other four rather than duplicating field lists).
- Added `AIKnowledgeSourceType` `StrEnum` to `core/constants/constants.py` (`case`, `case_summary`, `party`, `charge`, `appearance`) — doubles as the projector registry keys and the intended `ai_knowledge_source.source_type` values.
- Added `src/quick_chat_api/modules/__init__.py` and `.../embedding/__init__.py` (the `modules/` package tree was empty before this).
- Added `tests/modules/embedding/projectors/test_projectors.py` (14 tests) — PII exclusion, relationship-present/absent branches, unknown-`source_type` registry error, factory caching, case-summary composition, payment aggregation excluding voided payments and never surfacing card fields.
- Added `pytest` + `pytest-xdist` as dev dependencies — the project had `[tool.pytest.ini_options]` configured but no pytest actually installed, so no test in this repo could run before this. All 14 new tests pass (`uv run pytest tests/modules/embedding/projectors`).

**Decisions made:**
- Open Decision #4 (PII exclusion list) resolved for `PartyDetail`: `ssn_id` and `license_number` are never projected into embeddable text. Everything else on `PartyDetail` (dob, phone, email, physical descriptors, license type/state) is projected — user's explicit call, not just the "obvious" exclusions.
- Open Decision #3 (initial `source_type` set) resolved: `case`, `case_summary`, `party`, `charge`, `appearance` for Phase 2. `AddressProjector`/`PaymentProjector`/`DispositionProjector`/`SanctionProjector`/`CriminalProjector`/`VehicleProjector` deferred to Phase 3 per `PLAN.md` §15 (not built this session — scope was Phase 2 only).
- Projectors follow the same Interface + Registry + Factory shape as `core/llm/embedding/`, per `.claude/rules/coding-patterns.md` explicitly naming projectors as a pluggable subsystem — user chose this over a simpler shared-module approach.
- Relationship-aware projectors (`charge`, `appearance`, `case_summary`) guard every relationship access with `"relation" in entity.__dict__` and degrade to omitting that section rather than raising — since DB source adapters (§5) don't exist yet and this is the only safe way to unit-test/exercise these projectors against transient (non-session-attached) entities today.
- Payment data in `CaseSummaryProjector` is aggregated (total/currency/count) only — never per-payment card fields (`card_last_4`, `card_brand`, etc.), per `CLAUDE.md` §13/§20.

**New open questions:**
- None new. Open Decisions #1 (prod embedding provider/model) and #2 (new SDK dependency for it) remain open from the prior session.

**Next concrete action:**
- Build the DB source adapters (`PLAN.md` §5, `src/quick_chat_api/modules/embedding/db_adapters.py`) that eager-load each entity's relationships and hand it to the matching projector via `get_projector(source_type)` — this is what actually exercises the relationship-aware branches in `charge.py`/`appearance.py`/`case_summary.py` against real, session-attached data instead of transient test objects.
- Then chunking (§7 — likely a no-op passthrough for Phase 2 since these are single logical chunks per entity, unless a projected `case_summary` exceeds the embedding model's token limit) and the minimal `ingest_case()` path (§11) using `get_embedding_provider()` + `get_projector()` together.
- Do not start Phase 3 entities or retrieval (§10) until `ingest_case()` is validated end-to-end against real ingested data, per `CLAUDE.md` §12.

---

## 2026-09-06 — Session: local embedding provider (Open Decisions #1/#2, partial)

**Done this session:**
- Added `sentence-transformers` (+ `torch`) as a new dependency via `uv add` — approved by user for local/dev embedding only, no per-call cost.
- Added `EmbeddingProvider` abstraction: [`src/quick_chat_api/core/llm/embedding_provider.py`](src/quick_chat_api/core/llm/embedding_provider.py) — abstract `embed_documents`/`embed_query`/`dimension`, a `LocalSentenceTransformerProvider` implementation (batched, MPS/CPU capable, model loaded lazily + cached via `lru_cache` on `get_embedding_provider()`), and a `_build_provider()` factory keyed on `EMBEDDING_PROVIDER` so a hosted provider (OpenAI/Voyage/Cohere) can be added later as a second subclass with no caller changes.
- Added settings to [`src/quick_chat_api/settings/config.py`](src/quick_chat_api/settings/config.py): `EMBEDDING_PROVIDER` (default `local`), `EMBEDDING_MODEL` (default `sentence-transformers/all-mpnet-base-v2`), `EMBEDDING_DIM` (default `768`, no longer implicit in code — read from env/settings), `EMBEDDING_BATCH_SIZE`, `EMBEDDING_DEVICE`, `EMBEDDING_API_KEY` (for the future remote provider).
- Added the same keys to `.env.example`.
- Provider raises `EmbeddingDimensionMismatchError` at construction if the model's actual output dim != `settings.EMBEDDING_DIM` — fails fast instead of silently corrupting vectors.
- Smoke-tested end to end: model loads, batch `embed_documents`, single `embed_query`, dimension == 768, and `get_embedding_provider()` returns the same cached instance across calls.

**Decisions made:**
- Local dev/testing embedding provider: `sentence-transformers/all-mpnet-base-v2`, 768-dim, CPU device by default (works fine on M2 16GB; `EMBEDDING_DEVICE=mps` also available).
- `agency.py:47`'s `EMBEDDING_DIM = 1536` constant and the `ai_knowledge_chunk` vector column were **not** touched — user will do that migration themselves (still currently 1536, mismatched with the new 768-dim local default until that migration lands — do not run real ingestion against the DB until it does).

**New open questions:**
- Open Decision #1 (final provider/model for prod) is still open — this session only resolved the **local/dev** provider. `EMBEDDING_PROVIDER=openai` (or another host) still needs an implementation + approval when that phase starts.
- Migration to change `EMBEDDING_DIM` from 1536 → 768 (or whatever prod ends up needing) is pending on the user's side.

**Next concrete action:**
- Once the user's migration lands (DB column width matches `EMBEDDING_DIM`), proceed to `CaseRecordProjector` (`PLAN.md` §4) and the minimal `ingest_case()` path (`PLAN.md` §11) using `get_embedding_provider()` as the embedding step.

---

## 2026-09-06 — Session: planning + repo reality check

**What's actually true in the codebase right now:**

- Case data has been ingested into Postgres via `data_ingestion/ingest_data.py` (per user: "now that I have data ingested into the tables").
- `ai_knowledge_source` / `ai_knowledge_chunk` tables and their SQLAlchemy models **already exist** — this was NOT built this session, it was already in place:
  - Migration: [`src/quick_chat_api/migrations/agency/versions/2026_09_06_041701-9e9d5258d192_add_initial_vector_embedding_table_.py`](src/quick_chat_api/migrations/agency/versions/2026_09_06_041701-9e9d5258d192_add_initial_vector_embedding_table_.py)
  - Models: `AIKnowledgeSource` / `AIKnowledgeChunk` in [`agency.py:678-776`](src/quick_chat_api/core/models/agency/agency.py:678)
  - `EMBEDDING_DIM = 768` at `agency.py:47`
  - Vector index uses **pgvectorscale's diskann** (`vector_cosine_ops`), not plain pgvector HNSW.
- No embedding generation code exists anywhere in the repo. No `EmbeddingProvider`, no projectors, no chunking, no retrieval module, no LLM/embedding settings.
- `Settings` (`src/quick_chat_api/settings/config.py`) only has DB + `AWS_S3_BUCKET` config — nothing for an embedding/LLM provider yet.
- No background job/queue infra found — embedding backfill will need to be a standalone script initially.

**Decision made this session:** none yet — this was a planning-only session. `PLAN.md` was rewritten to reference real paths and mark Phase 1 (schema) as done; everything from projection onward is unbuilt.

---

## Open Decisions (blocking — must be answered before implementation starts)

1. **Embedding provider/model** — not chosen yet. Whatever is chosen must output 1536-dim vectors to match the already-migrated `EMBEDDING_DIM`, OR a migration change must be explicitly approved to alter it (this touches `core/models/`, which needs explicit user approval per `CLAUDE.md` §7).
   - Candidates to evaluate: OpenAI `text-embedding-3-small` (1536-dim, matches as-is), Voyage AI (legal/case-domain-tuned options exist), Cohere embed-v3. Needs a pricing/latency/quality tradeoff discussion before picking.
2. **New dependency approval** — an SDK client for whichever provider is chosen (e.g. `openai`), plus possibly a tokenizer (e.g. `tiktoken`) for token-aware chunking. Per `CLAUDE.md` §5, must ask before adding.
3. ~~**What counts as a "document" per case**~~ — **RESOLVED** 2026-09-06: `AIKnowledgeSourceType` = `case`, `case_summary`, `party`, `charge`, `appearance` for Phase 2 (`core/constants/constants.py`).
4. ~~**Sensitive field exclusion list**~~ — **RESOLVED** 2026-09-06 for `PartyDetail`: exclude `ssn_id` and `license_number` only; dob/phone/email/physical descriptors/license type+state are projected. `PaymentRecord`/`AddressDetail` exclusion lists still undecided — not needed until their Phase 3 projectors are built (`CaseSummaryProjector`'s payment section already aggregates rather than projecting raw `PaymentRecord` fields, so no card data leaks today).
5. ~~**Status enum enforcement**~~ — **RESOLVED** 2026-09-06: application-level only, via `AIKnowledgeStatus` `StrEnum` in `core/constants/constants.py`. No DB check constraint.

---

## Next Concrete Action (start here next session)

1. Run `data_ingestion/backfill_embeddings.py --agency <schema>` against the real Postgres DB, spot-check `ai_knowledge_chunk` rows for a few cases, and re-run once to confirm the skip-unchanged path actually skips.
2. Only after that manual validation, build retrieval (`PLAN.md` §10): `modules/embedding/retrieval.py`'s `retrieve(session, query, case_record_id, source_types, top_k)`.
3. Do not start Phase 3 (related entities) until retrieval is validated end-to-end against real ingested data, per `CLAUDE.md` §12 and `PLAN.md` §15.

---

## Session Log Template (copy for future entries)

```
## YYYY-MM-DD — Session: <short title>

**Done this session:**
- ...

**Decisions made:**
- ...

**New open questions:**
- ...

**Next concrete action:**
- ...
```
