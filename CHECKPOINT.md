# Checkpoint — AI Knowledge / Vector Embeddings

Living progress log for the work described in `PLAN.md`. Update this file at the end of each work session so it can be picked back up cold. Newest entry on top.

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
3. **What counts as a "document" per case** — decide the initial `source_type` set for Phase 2 (proposal: `"case_summary"` as a first synthesized document type covering the whole case, before doing per-entity chunks for parties/charges/appearances).
4. **Sensitive field exclusion list** — before writing `PartyProjector` / `PaymentProjector`, explicitly enumerate which fields must never be embedded (SSNs, payment card numbers, similar identifiers) per `PLAN.md` §3 rule 8. Not yet audited against the actual `PartyDetail`/`PaymentRecord`/`AddressDetail` columns.
5. **Status enum enforcement** — `ai_knowledge_source.status` is a free-text column with no DB check constraint. Decide whether to enforce the `PENDING/PROCESSING/COMPLETED/FAILED/DELETED/SUPERSEDED` set purely at the application layer (e.g. a Python `StrEnum` + validation in the module) or request a migration to add a check constraint.

---

## Next Concrete Action (start here next session)

1. Resolve **Open Decision #1 and #2** (provider + dependency approval) with the user — this blocks everything else.
2. Once approved, add `EMBEDDING_PROVIDER` / `EMBEDDING_MODEL` / `EMBEDDING_API_KEY` / `EMBEDDING_BATCH_SIZE` to `Settings` (`src/quick_chat_api/settings/config.py`).
3. Build `CaseRecordProjector` first (highest value, per `PLAN.md` §4) — a natural-language rollup of one `CaseRecord` (+ eagerly-loaded relationships) into a single text document.
4. Build the `EmbeddingProvider` abstraction + first concrete implementation (`src/quick_chat_api/core/llm/embedding_provider.py`).
5. Build the minimal ingestion path for one entity type (`ingest_case(case_id)`) end-to-end: project → hash → embed → upsert `AIKnowledgeSource`/`AIKnowledgeChunk`.
6. Write a one-off backfill script to run `ingest_case()` over every already-ingested `CaseRecord` (this is the immediate payoff — makes the already-loaded data queryable).
7. Only after (6) is validated manually (spot-check a few embeddings/retrieval results), move to Phase 3 (related entities) per `PLAN.md` §15.

Do not start on retrieval (`PLAN.md` §10) or Phase 3+ until step 6 above is done and spot-checked — see `CLAUDE.md` §12 ("do not blindly increase top_k / jump ahead").

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
