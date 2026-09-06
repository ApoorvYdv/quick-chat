# Checkpoint — AI Knowledge / Vector Embeddings

Living progress log for the work described in `PLAN.md`. Update this file at the end of each work session so it can be picked back up cold. Newest entry on top.

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
5. **Status enum enforcement** — `ai_knowledge_source.status` is a free-text column with no DB check constraint. Decide whether to enforce the `PENDING/PROCESSING/COMPLETED/FAILED/DELETED/SUPERSEDED` set purely at the application layer (e.g. a Python `StrEnum` + validation in the module) or request a migration to add a check constraint.

---

## Next Concrete Action (start here next session)

1. Build the chunking step (`PLAN.md` §7) — likely a passthrough (one chunk per projected document) for Phase 2, unless a `case_summary` document exceeds the embedding model's token limit.
2. Build the minimal ingestion path for one entity type (`ingest_case(case_id)`) end-to-end: `CaseKnowledgeSourceAdapter.discover_all(case_id)` → hash each `DiscoveredEntity` (SHA-256) → close session → skip unchanged (compare against existing `AIKnowledgeSource.content_hash`) → `get_embedding_provider().embed_documents(...)` → new DB transaction → bulk upsert `AIKnowledgeSource`/`AIKnowledgeChunk` (see `PLAN.md` §9 for the async/DB-safety sequencing — never hold a transaction open across the embedding call).
3. Write a one-off backfill script to run `ingest_case()` over every already-ingested `CaseRecord` (this is the immediate payoff — makes the already-loaded data queryable).
4. Only after (3) is validated manually (spot-check a few embeddings/retrieval results), move to Phase 3 (related entities) per `PLAN.md` §15.

Do not start on retrieval (`PLAN.md` §10) or Phase 3+ until step 4 above is done and spot-checked — see `CLAUDE.md` §12 ("do not blindly increase top_k / jump ahead").

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
