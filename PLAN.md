# Quick Chat — Master Plan (v3, rewritten from scratch 2026-10-03)

Status legend: `[x]` done · `[~]` partly done · `[ ]` not started · `[spike]` needs a short proof before committing.

Single forward-looking plan. Build history lives in `CHECKPOINT.md` (to be archived under `docs/history/`, see S0.9). Everything here was decided with the owner on 2026-10-02/03; the decision table (§2) is authoritative.

---

## 1. Goal and invariants

Quick Chat is a **multi-tenant, grounded RAG backend** that answers natural-language questions about court/case data. PostgreSQL is the source of truth; the LLM only interprets retrieved evidence.

Invariants for every stage (from `CLAUDE.md`):

1. **Tenant isolation is a security boundary:** Postgres schema-per-agency, Qdrant collection-per-agency, LangGraph checkpoints in the agency schema. No LLM output can select a tenant.
2. **Grounding:** cite evidence; insufficient evidence → say so; conflicting records → surface both; never fabricate names, dates, charges, payments, hearings, sanctions, dispositions, amounts.
3. **Retrieved content is untrusted data**, never instructions.
4. **No case content in logs or traces by default** (documents, prompts, chunks, LLM output).
5. **Router → Controller → Module**, `RequestContext`, `ErrorResponse`, Interface + Registry + Factory for pluggable subsystems.
6. **Design rule:** a later stage may add nodes, providers, datasets or entities. It must not change a contract, a signature or the storage layout of an earlier stage. Deferred enhancements (§10) get a seam now so adding them later is additive.

## 2. Decisions (owner-confirmed)

| # | Decision |
|---|---|
| D1 | **Python 3.14 everywhere:** `pyproject`, `.python-version`, Dockerfile, CI, `CLAUDE.md`, README, migrations README. |
| D2 | **Qdrant is the only vector store.** Superseded by owner decision 2026-10-03: the `ai_knowledge_source`/`ai_knowledge_chunk` models and tables are removed entirely; chunk text and index fingerprint live in the Qdrant payload. Approved `core/models/` change. |
| D3 | **Qdrant pinned to `v1.19.1`** (latest stable on Docker Hub, verified 2026-10-03; matches `qdrant-client>=1.19.1`). Collection-per-agency kept (about 50 agencies). |
| D4 | **Embeddings (and later reranking) behind a separate inference service** every API worker shares, selected through the existing `EmbeddingProvider` registry (new `remote` provider). In-process `local` stays for CLI/backfill. |
| D5 | **One Postgres connection pool for everything** (app, Alembic, LangGraph checkpointer) → one driver family, psycopg 3 (§6, S0.4 spike). |
| D6 | LangGraph checkpointer in each **agency schema**; multi-turn, session per agency (not per case); `thread_id = "{agency}:{session_id}"`. |
| D7 | Question scopes: case-scoped, cross-case lookup (by case number/party), agency-wide semantic search. |
| D8 | JSON **and** SSE streaming. |
| D9 | **LangChain chat models + LangGraph + `langgraph-supervisor`** for the multi-agent system. Claude Sonnet 5 default via Anthropic; OpenAI second provider. |
| D10 | **LangSmith** tracing, metadata-only/redacted by default; structured JSON logs alongside. |
| D11 | Structured logging with `structlog`; `utils.common.logger.logger` keeps its import path and stdlib-style call signature (`data_ingestion` imports it). |
| D12 | Health (`/healthz`) and readiness (`/readyz`) endpoints; Dockerfile gets `HEALTHCHECK`; compose/Dockerfile otherwise unchanged. Better app description. |
| D13 | Timezone: remove the `America/Denver` hardcode → default from `Settings`, per-agency override from `config.config`. |
| D14 | `config` schema PKs aligned to UUID (the models already say UUID) via a new Alembic migration; `UserDetails.agency_user_id` becomes a UUID. |
| D15 | Dev tooling: `ruff`, `mypy`, `pytest-asyncio`, `pytest-cov`, `testcontainers`, `httpx`, `pre-commit`, `pip-audit`, `bandit`; `deepeval` for evals; `arq` (Redis) for background jobs. |
| D16 | Kept as is: ingestion pipeline, Interface+Registry+Factory pattern, router/controller wiring, `is_active` filter (+ add missing tests, drop stale comments), `RequestContext`, DB engine design, `AWS_S3_BUCKET` (still required) and `aioboto3`, ingestion endpoints, audit columns, `langgraph-supervisor`, `openai`. |
| D17 | **Deferred, with seams:** Cognito auth, OpenTelemetry/metrics, Sentry, Redis rate limiting/caching, `sse-starlette`, JEV-style routing, PII redaction service, tenacity-style retry library. |

### Interpretation notes (tell me if wrong)

- Your numbered replies lined up with audit findings F1–F16, keep/drop K1–K19, libraries L1–L14, and open questions Q1–Q5; where numbering slipped I mapped by content (e.g. "keep langgraph supervisor" → K19; "yes" → archive `CHECKPOINT.md`; "yes deepeval" → L11, so the PII-service question is treated as deferred; the last library "yes" → `orjson`, adopted only if profiling justifies).
- **F5** (`session_context` logs `str(ex)`, which may include bound SQL parameters) is **kept as is** per your answer. It conflicts with `CLAUDE.md` §20; a one-line sanitizing change is listed as optional S0.10, off by default.
- **D5 means the app engine moves from asyncpg to psycopg 3.** This is the only place "engine keep same" bends: same single engine and pool design, different driver. Guarded by a spike and a `data_ingestion` contract test (S0.4); if it fails, we stop and ask before adding a second pool.
- **D9 changes the earlier custom-provider design:** the LLM "interface" is LangChain's `BaseChatModel`; our registry/factory only selects and configures it. New dependencies `langchain-anthropic` and `langchain-openai` follow from your LangGraph/LangChain choice.
- **`arq` needs Redis**, so a Redis service enters compose with the jobs stage (S5); rate limiting and caching stay deferred but get cheaper later.

## 3. Frozen surface: `data_ingestion/` stays untouched

Nothing inside `data_ingestion/` changes. These `src/` contracts must keep working (enforced by a contract test, S0.8):

| Script | Depends on | Must remain |
|---|---|---|
| `create_tables.py` | `AgencyBase.metadata.create_all`, `get_async_engine` | All models; no extension needed beyond `pg_trgm` once the vector column is gone |
| `ingest_data.py` | 10 business models by name, `get_async_engine`, `settings` | Model/column names; `Settings` loads with `DB_*` and `AWS_S3_BUCKET` |
| `backfill_embeddings.py` | `session_context`, `CaseRecord`, `CaseIngestionService(engine, agency).ingest_case/.reindex_case`, `logger` | Same import path/signature; result exposes `.embedded/.skipped/.failed/.outcomes[].source_type/.source_id/.error`; `logger.error(msg, extra={...})` works |
| `add_uuid7_ids.py` | `uuid_utils` only | — |

## 4. Target architecture

```
                      HTTP  (header `agency` → RequestContext)
   /healthz  /readyz   POST /cases/{id}/ask   POST /ask   POST …/ask/stream (SSE)   ingestion routes
                                      │
                       ChatController (class, Depends)
                                      │
        ┌─────────────────────────────▼───────────────────────────────┐
        │ LangGraph StateGraph  (core/rag)   checkpointer: agency schema│
        │ understand → resolve_case → (structured ∥ vector retrieve)    │
        │   → rerank → build_context → generate → finalize              │
        │ S4: understand → supervisor → {case | hearings | financial}   │
        │     agents (langgraph-supervisor) → combine → finalize        │
        └──┬───────────────┬──────────────┬───────────────┬───────────┘
           ▼               ▼              ▼               ▼
   modules/rag/      core/vectorstore  core/llm/        core/llm/embedding + reranking
   SQL tools, case   Qdrant v1.19.1    generation       local | remote ──► inference service
   resolver, context collection/agency (LangChain chat   (sentence-transformers, shared by
   builder                              models) + prompts all API workers)
           │
   PostgreSQL (psycopg3, ONE pool): case data · chunk content/hash/lineage · checkpoints per agency
```

Target layout (new items marked +):

```
src/quick_chat_api/
  main.py                     lifespan, routers, middleware, exception handlers
  settings/config.py
  utils/  context.py  dependencies.py  helper.py  common/logger.py  agency_resolver.py+ (TTL cache seam)
  routers/   health_router.py+  ingestion_router.py  chat_router.py+
  core/
    constants/  schemas/{ingestion,chat+,health+}  controllers/{ingestion,chat+}
    database/   models/ (protected)  vectorstore/
    llm/  embedding/ (+providers/remote.py)  reranking/+  generation/+  prompts/+
    rag/+  state.py graph.py nodes/ checkpointer.py tracing.py streaming.py agents/ (S4)
    jobs/+ (S5)
  modules/
    embedding/  (ingestion pipeline: chunking, projectors, db_adapters, ingestion_service)  [kept]
    rag/+  structured/{case,hearings,financial}.py  case_resolver.py  context_builder.py  retrieval.py (moved)
src/quick_chat_inference/+     tiny FastAPI app: /embed /rerank /healthz /readyz
tests/  evals/+  docs/history/+  .github/workflows/ci.yml+
```

## 5. Current state (verified in repo)

| Area | Status |
|---|---|
| Projectors (case, case_summary, party, charge, appearance, payment, disposition, sanction, criminal, vehicle, address), `StructuredFieldChunker`, `CaseKnowledgeSourceAdapter`, `CaseIngestionService`, ingestion router/controller | `[x]` (Qdrant-only; Postgres knowledge tables removed in S0.2) |
| `EmbeddingProvider` (`local`), `VectorStore` + Qdrant provider (collection-per-agency, lazy create, 16 indexed payload fields incl. `case_number`/`case_title`/`case_type`/`case_status`/`is_juvenile`) | `[x]` |
| `retrieve()` and `get_cases_by_number()` | `[x]` mock-tested; spot-checked on real data (S0.11) |
| `RequestContext`, `ErrorResponse`, `get_agency_header`, `session_context` + `is_active` filter, two-env Alembic runner | `[x]` |
| Health endpoints, structured logger, lifespan, conftest/integration tests, CI, reranker, LLM layer, prompts, graph, checkpointer, chat endpoints, evals, inference service, jobs | `[ ]` |

---

## S0 — Foundation hygiene `[ ]`

Goal: one storage path, one Python, one driver, real tooling; no feature work.

- **S0.1 Python 3.14 everywhere (D1).** `.python-version`, `pyproject`, Dockerfile (already 3.14), `CLAUDE.md` (§1 says 3.12), `README.md`, `migrations/README.MD` (3.12.4). Smoke: `uv sync && uv run pytest` on 3.14 including torch-CPU, langgraph, qdrant-client imports.
- **S0.2 Drop pgvector (D2).** New agency Alembic migration dropping `ai_knowledge_chunk.embedding` and its diskann index (downgrade re-adds nullable column; extensions left installed). Remove the `Vector` column and `EMBEDDING_DIM` model constant from `AIKnowledgeChunk` (`Settings.EMBEDDING_DIM` stays the vector-store dimension); remove `pgvector` from dependencies. Remove the pgvector write from `CaseIngestionService._write_embedded`. Qdrant upsert becomes the only vector write. Treat `vector_sync != "ok"` as "changed" in the skip check so a failed Qdrant write is retried instead of leaving Postgres saying `COMPLETED`.
- **S0.3 Qdrant pin + compose hygiene.** `qdrant/qdrant:v1.19.1` in compose; healthchecks for postgres and qdrant (verify what tooling exists in the pinned image before choosing the command); `app` `depends_on` with `condition: service_healthy`. Compose/Dockerfile otherwise unchanged (D12/D16). Note: the Dockerfile's default `CMD` still has `--reload`; production deployments must override the command (listed under risks, not changed here).
- **S0.4 One driver, one pool `[spike]` (D5).** Switch `DatabaseConfig.build_db_url` to `postgresql+psycopg` for async and sync (Alembic); drop `asyncpg` and `psycopg2-binary`. Same single `get_async_engine`, same pool settings. Success criteria: (a) all four `data_ingestion` scripts run unchanged against a scratch schema; (b) full existing suite green; (c) an `AsyncPostgresSaver` can run against a connection borrowed from this same pool with `search_path` set to an agency schema and reset on return (autocommit and `dict_row` set for the checkout and restored). If (c) fails, stop and bring the options back to you; do not add a second pool unprompted.
- **S0.5 Structured logging (D11).** `structlog` configured over stdlib (`ProcessorFormatter`) so `logger` stays a stdlib logger (`extra=` still works). JSON output, `merge_contextvars`, `request_id`, `correlation_id`, `agency` bound per request by middleware; remove the default `SysLogHandler`; no import-time side effects beyond configuring once. A processor drops known sensitive keys (`question`, `prompt`, `context`, `answer`, `content`).
- **S0.6 `main.py` and health (D12).** Lifespan: dispose engine on shutdown, optionally pre-warm vector-store client. `/healthz` (liveness, no dependencies) and `/readyz` (Postgres `SELECT 1`, Qdrant reachable, inference service reachable once it exists; returns 503 with a generic body, details only in logs). Not behind `get_agency_header`. Generic exception handler returning a stable error shape (no stack traces). App title/description updated to: "Quick Chat — a grounded, multi-tenant RAG API for natural-language questions about court case data." Dockerfile `HEALTHCHECK` using Python stdlib (`urllib`) against `/healthz`.
- **S0.7 Cleanups (D14, D13, F9).** (a) New `config` Alembic migration converting `agencies`, `config`, `user` PKs to UUID with `uuidv7()` default (verify FK/data references first; use `USING` with generated ids); `UserDetails.agency_user_id: UUID | None`. (b) Remove unused `RequestContext.case_types`/`config` and the unused `AWS_ACCESS_KEY`/`DATABASE_URL` entries from `.env.example` (keep `AWS_S3_BUCKET` required). (c) Delete the stale "ROA after_flush" warning in `session_context_manager.py`; fix the docstring's reference to a non-existent test by actually adding `tests/core/database/test_is_active_filter.py` (include-inactive, exempt-model, cache-leak-across-requests cases). (d) Timezone: `Settings.DEFAULT_TIMEZONE`; `helper.get_client_timezone()` reads the per-agency value from `config.config` via the agency resolver when a request context exists, else the default; `RequestContext` getters must not raise outside a request (scripts, workers). (e) Replace bare `except Exception` in `helper.py` with `ZoneInfoNotFoundError`.
- **S0.8 Tooling and test scaffolding (D15).** Dev group: `ruff`, `mypy`, `pytest-asyncio`, `pytest-cov`, `testcontainers`, `httpx`, `pre-commit`, `pip-audit`, `bandit`. Ruff rule set `E,F,I,UP,B,ASYNC,S,SIM,RUF`; mypy on `src` (new packages strict). `.pre-commit-config.yaml`. `tests/conftest.py` and fakes per §7. `.github/workflows/ci.yml` (assumes GitHub; adjust if you use another CI). Add the three contract tests: `data_ingestion` scripts vs scratch schema, schema parity (`create_all` vs Alembic produce the same tables/indexes/columns), frozen-surface import/signature test.
- **S0.9 Docs.** Update `CLAUDE.md`/`.claude/rules` where stale (Python version, `reset_sequences`, pgvector mentions, architecture additions); move `CHECKPOINT.md` to `docs/history/CHECKPOINT-2026-09.md` and start a short new one; update README env table.
- **S0.10 Optional (default off):** sanitize `session_context`'s error log to exception class + SQLSTATE only.
- **S0.11 Real-data validation `[x]` (2026-10-05, agency `southern_ute`, local compose).** Run `create_tables → ingest_data → backfill_embeddings` for a scratch agency from `batch_1.json`; spot-check `retrieve()` and `get_cases_by_number()`.
- **Acceptance:** CI green (lint, types, unit, integration); `grep -ri pgvector src` finds only the historical migration; ingestion contract test passes; `/healthz` and `/readyz` behave; one driver family in `uv.lock`.

---

## S1 — Platform seams (thin, permanent) `[ ]`

### S1.1 Contracts (`core/schemas/chat.py`)

```text
AskRequest   { question, session_id: UUID, case_id: UUID | None, case_number: str | None,
               mode: "auto" | "case" | "agency_search" = "auto" }
AskResponse  { answer, citations[], insufficient_information, conflicts[], resolved_case_ids[],
               needs_clarification | None, trace_id, session_id }
Citation     { chunk_id, case_record_id, source_table, source_record_id, source_type }
SSE events   token | citation | status | final(AskResponse) | error
```

Endpoints (router-level `Depends(get_agency_header)`, class-based `ChatController`, `ErrorResponse` constants): `POST /cases/{case_id}/ask`, `POST /ask`, plus `/stream` variants. SSE is a plain `StreamingResponse` with `text/event-stream` via one `encode_sse()` helper (so `sse-starlette` can replace it later with no caller change).

### S1.2 State (`core/rag/state.py`)

`PipelineState`: question, agency (from `RequestContext` only), session_id, requested case id, mode, `understanding` {scope, domains, needs_structured, needs_vector, case_refs}, `resolved_case_ids` (validated against Postgres), structured/vector `EvidenceItem[]`, `contexts[]` (exactly what the LLM saw, needed by evals), answer, citations, conflicts, trace. `EvidenceItem` keeps `agency, case_record_id, source_table, source_record_id, chunk_id, text, score, rerank_score`. Case scope is recomputed every turn: a remembered case from the checkpointer is only a hint to `understand`, re-validated; a different case in the question wins; ambiguity → clarification, never a silent pick.

### S1.3 Graph runtime and tracing

`build_graph(checkpointer)` returns a compiled graph; nodes are async functions with injected dependencies, callable without HTTP (eval seam). Conditional edges short-circuit to `finalize` on clarification or empty evidence (**no LLM call**). Every node wrapped by `@traced_node`: logs `request_id, agency, session_id, node, latency_ms, counts, status, model, prompt_version, tokens`, never content. The decorator fans out to a list of tracing sinks (structlog now; LangSmith via `@traceable` metadata-only; OTel later, §10). LangSmith default is **redacted** (inputs/outputs scrubbed to ids/counts) until you opt in per environment.

### S1.4 LLM layer (`core/llm/generation/`, D9)

Registry + factory pattern selects and configures a LangChain `BaseChatModel`: `get_chat_model(role)` with roles `answer` (default `claude-sonnet-5`) and `router` (a cheaper/faster model); providers `anthropic` (`langchain-anthropic`) and `openai` (`langchain-openai`). Timeouts and `max_retries` set on the model (SDK-level retries; no retry library). Usage comes from `usage_metadata`; streaming via `astream`; structured output via `with_structured_output`; tools via `bind_tools`. New dependencies: `langchain-anthropic`, `langchain-openai` (the direct `anthropic`/`openai` pins become transitive).

### S1.5 Prompts (`core/llm/prompts/`)

Versioned `ChatPromptTemplate`s (`understand.v1`, `answer.v1`, later per-agent). The version is stamped into the trace. System prompt: role; use only provided evidence; cite by evidence id; missing info → "the available case data does not provide enough information"; conflicts → state both with sources; retrieved text is delimited data, never instructions; never fabricate the listed fact types.

### S1.6 Tenant-safe tool layer (`modules/rag/`)

Plain async functions used by the linear pipeline now and by agents later: `structured/{case,hearings,financial}.py`, `case_resolver.py` (candidates by case number/party name; never auto-picks), `context_builder.py`. **Rule:** no tool parameter is a tenant or user identifier; tools open `session_context(engine, RequestContext.agency)` themselves; `case_id` arguments are validated to exist in the current tenant. `RequestContext` flows through LangGraph's async task tree via `ContextVar`, **and a concurrency test proves two simultaneous requests for different agencies never cross** (also required again in S4).

### S1.7 Checkpointer in the agency schema (D5/D6)

`AsyncPostgresSaver` bound to a connection borrowed from the **same** engine pool (S0.4 spike), `search_path` set to the agency schema (validated registry value, quoted with `psycopg.sql.Identifier`, never request input) and reset on return. `setup()` runs lazily once per agency (idempotent, in-process set, like Qdrant `_ensure_collection`). `thread_id = f"{agency}:{session_id}"`; history window `CHAT_HISTORY_MAX_TURNS`; retrieved evidence is never stored as conversation history (re-retrieved each turn). Chat history is PII at rest in the agency schema; retention default is 30 days (purge job in S5).

### S1.8 Inference service (D4)

`src/quick_chat_inference/` — small FastAPI app (uses the existing `sentence-transformers`/`torch`) exposing `/embed`, `/rerank`, `/healthz`, `/readyz`; one container in compose; API workers call it with `httpx` through a new `remote` `EmbeddingProvider` (and `remote` reranker provider in S3). The embedding **indexing key must not change when switching `local` ↔ `remote`**: key on model + version (remote reports the underlying provider identity), otherwise every agency re-embeds on a config change. Optional image slimming (API image without torch via a dependency extra) decided when this lands; Dockerfile unchanged until then.

### S1.9 Settings and `.env.example` additions

`DEFAULT_TIMEZONE`, `LLM_PROVIDER`, `LLM_ANSWER_MODEL`, `LLM_ROUTER_MODEL`, `LLM_TIMEOUT_S`, `LLM_MAX_RETRIES`, `LLM_MAX_TOKENS`, `ANTHROPIC_API_KEY`, `OPENAI_API_KEY` (use `SecretStr`), `EMBEDDING_REMOTE_URL`, `RERANKER_PROVIDER/MODEL`, `RERANK_CANDIDATE_K/TOP_N/MIN_SCORE`, `CONTEXT_MAX_TOKENS`, `CHAT_HISTORY_MAX_TURNS`, `LANGSMITH_*`, `AGENT_MAX_ITERATIONS`. Agents may edit `.env.example` (never `.env`); keep the README table and the file in sync.

### S1.10 Domain map

`SOURCE_TYPE_GROUPS` (S2, `core/constants/constants.py`: financial, outcome, people, hearings, case_level) already exists for `retrieve(source_types=…)`; the S4 agent domain map below must be reconciled with it (here disposition/sanction sit under `outcome`, not financial). One constant maps `AIKnowledgeSourceType → Domain` (`case | hearings | financial`): case, case_summary, party, charge → case; appearance → hearings; payment, disposition, sanction → financial. `retrieve(source_types=…)` already filters in Qdrant, so S4 agents need no payload or index change.

**Acceptance:** an empty-but-wired graph (fake nodes) serves both endpoints with checkpointing, tracing and streaming; replacing a fake node with a real one needs no signature change; cross-agency checkpoint isolation test passes against real Postgres.

---

## S2 — Data coverage `[~]` (indexing done 2026-10-07; structured query functions open)

- `[x]` Projectors for `payment` (aggregate-safe: type, amount, currency, date, status; never card or account fields), `disposition`, `sanction`, `criminal`, `vehicle`, `address` (PII exposure to be reviewed field by field; default: not embedded until you decide). Update `AIKnowledgeSourceType`, `discover_all`, eager loading (one round trip, no N+1).
- `[x]` Add `case_number` (and `case_title`) to the Qdrant payload before the first real re-ingest so agency-wide search can display it without a Postgres hop. A payload change later means a full reindex, so decide now.
- `[ ]` Complete the structured query functions per domain and the domain map (see S1.10 note on `SOURCE_TYPE_GROUPS`).
- `[x]` Re-ingest once via `backfill_embeddings.py` (content hash now covers the case payload, so everything re-embedded).
- **Decisions (2026-10-06):** payment embeds only amount, currency, date, void, `payee_name`, `payee_email`, `payee_address`, `reference_number`, `receipt_number`, `consider_as_full` (never card/exp/`qp_payment_id`/method/mode/`service_fee`); vehicle (incl. plate, VIN), address (all types) and criminal (incl. observation text) embed all fields; disposition and sanction get standalone chunks (still also inlined in the charge chunk, so S3 dedupes by `source_id`); payload adds `case_number`, `case_title`, `case_type`, `case_status`, `is_juvenile`; `case_summary` unchanged.
- **Acceptance `[x]` (verified on `southern_ute`):** every entity a domain agent needs is indexed; `retrieve(source_types=<financial>)` returns only financial chunks for the right tenant and case; PII exclusion tests per projector.

## S3 — Single-path answer pipeline on the graph `[ ]`

- **S3.1 Reranker** (`core/llm/reranking/`, Interface+Registry+Factory; providers `cross_encoder`, `remote`, `none`). Over-fetch `RERANK_CANDIDATE_K` from Qdrant (still tenant/case/source-type pre-filtered), hydrate, rerank on authoritative text, keep `RERANK_TOP_N`, drop below `RERANK_MIN_SCORE`. Reranking reorders and trims only; it never widens scope.
- **S3.2 `understand`** (router model, structured output) with deterministic fast-paths (supplied `case_id`, case-number regex). Failure degrades to retrieval on the given scope, never a client error.
- **S3.3 `resolve_case`:** 0 matches → insufficient info; 1 → proceed; more than 1 → `needs_clarification` with safe identifiers. `agency_search` retrieves without `case_record_id` from the agency collection, grouped per case with a per-case cap.
- **S3.4 Context builder:** filter, dedupe, prefer structured data, order by rerank score, fit `CONTEXT_MAX_TOKENS` with the embedder tokenizer, keep source metadata and case boundaries, detect conflicts (same field, different values).
- **S3.5 `generate`:** structured output `{answer, citations, insufficient_information}`; citations validated against the evidence actually supplied; SSE streams tokens, `final` carries the validated response.
- **S3.6 Controller/routers** exactly per the ingestion reference pattern; new `ErrorResponse` constants; unexpected errors logged and returned as a generic 5xx.
- **S3.7 Evaluation gate** (§8).
- **Acceptance (gate):** §8 thresholds met on the golden set; isolation tests green; per-node p95 latency recorded.

## S4 — Multi-agent with `langgraph-supervisor` `[ ]`

Prerequisite: S3 gate passed. Add a supervisor after `understand` and three agents (Case Details, Procedural Hearings, Financial Details), each built from the S1.6 tools with its own versioned prompt, its own `source_types` scope, its own Pydantic output schema. Single-domain questions go to one agent; multi-domain fan out; a combiner merges citations/conflicts. Hard caps: `AGENT_MAX_ITERATIONS`, graph recursion limit, per-request token budget; tool arguments validated by Pydantic; any tool call with a `case_id` outside the resolved set is rejected. Endpoint/`AskResponse`/checkpointer contracts unchanged; per-agent spans through the same `@traced_node`; eval suite gains per-domain slices. **Acceptance:** per-domain scores at or above the S3 baseline, no isolation/grounding regression, concurrent-tenant test green, cost and latency reported against the baseline.

## S5 — Jobs and breadth `[ ]`

- **Background jobs (D15):** `core/jobs/` with `arq` and a Redis service in compose; tasks `reindex_case(agency, case_id, force)`, `backfill_agency(agency)`, `purge_old_checkpoints`. Workers re-validate `agency` against the registry (never trust the queue payload) and use `CaseIngestionService(engine, agency)` as today. A narrow `enqueue(job_name, **kwargs)` seam isolates `arq` (low release activity) so it could be swapped later. Ingestion endpoints stay synchronous until you choose to move them (D16); switching to 202 + job id is then a controller change only.
- Eval in CI (nightly), reranker/top-K sweeps, regression alerts.
- File sources (PDF/DOCX/OCR + S3 via `aioboto3`, recursive/semantic chunkers, source-type-aware chunking) and event-driven incremental ingestion.
- Pick up deferred enhancements from §10 as needed.

---

## 6. Single-pool design notes (D5)

SQLAlchemy `postgresql+psycopg` serves the app, Alembic and `data_ingestion`. The checkpointer borrows a raw psycopg connection from the same pool for the duration of one graph run (autocommit + `dict_row` for the checkout, restored afterwards; `SET search_path` then `RESET`). `schema_translate_map` for ORM sessions is unaffected. Pool sizing accounts for chat concurrency: `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` must cover request sessions plus in-flight graph runs; load-test before production. Fallback if the spike fails: a dedicated small psycopg pool, which requires your explicit re-approval.

## 7. Testing plan

**Principles:** fast default run, real services only where behavior depends on them, tenant isolation tested on every new path, no network or paid LLM calls in default runs.

| Layer | Scope | Tools | Runs |
|---|---|---|---|
| Unit (`tests/unit`-style, mirrors `src`) | projectors, chunker, context builder, prompt registry, understand fallbacks, reranker orderings, retry helper | pytest, fakes | every commit |
| Component | modules against fakes of Qdrant/LLM/embedder | `FakeVectorStore`, `GenericFakeChatModel`, `FakeEmbeddingProvider` | every commit |
| Integration (`@pytest.mark.integration`) | real Postgres 18 (timescale image) + Qdrant v1.19.1 via `testcontainers`; ingestion service, retrieval, `is_active` filter, checkpointer, schema parity | testcontainers, unique schema/collection prefix per test module for xdist safety | CI job with services, locally on demand |
| API | endpoints incl. SSE, validation errors, error shapes, health/readiness | `httpx.AsyncClient` + `ASGITransport`, dependency overrides | every commit |
| Contract | `data_ingestion` scripts unchanged vs scratch schema; frozen-surface signatures; Alembic vs `create_all` parity | integration containers | CI |
| Isolation | agency A can never see agency B: retrieval, tools, checkpoints, agency-wide search, concurrent requests | integration, two schemas/collections | CI, mandatory |
| Eval (`@pytest.mark.eval`, `evals/`) | golden set, DeepEval metrics, reranker A/B | real LLM judge, synthetic data | nightly/manual |

**Fixtures (`tests/conftest.py` and layers below):** settings override that refuses non-local hosts; `fake_embedding` (deterministic hashing, small dimension); `fake_vector_store` (in-memory `VectorStore` implementation); `fake_chat_model`; `fake_reranker`; `agency_pair` (two seeded tenants); case factories as plain functions (no extra library); `asgi_client` with `RequestContext`/agency header helpers; async mode `auto` via `pytest-asyncio` (existing `asyncio.run` tests stay).

**Mandatory scenarios** (from `.claude/rules/rag.md`): correct case retrieval, irrelevant query, missing information, multiple similar cases, similar party names, cross-tenant isolation, empty vector results, conflicting records, cross-case lookup, agency-wide search, multi-turn follow-up with case switch, ambiguity → clarification, prompt-injection text in a chunk, no LLM call on empty evidence, citation not in supplied context gets dropped, logs contain no content.

**Quality bars:** coverage ≥ 80% on `core/` and `modules/` (ratchet up), ruff and mypy clean, `pip-audit` and `bandit` in CI, pre-commit hooks mirror CI. CI order: lint → types → unit/component/API → integration (services) → image build → audit; evals nightly.

## 8. Evaluation design

- **Seam (S1):** `run_pipeline(question, agency, session_id, case_id=None) -> PipelineResult{answer, citations, contexts, trace}` callable without HTTP.
- **Golden set** (`evals/datasets/*.jsonl`, from `batch_1.json` plus a second synthetic agency): `question, agency, case_id|case_number, expected_facts[], expected_source_ids[], expected_insufficient, tags[]`, covering the mandatory scenarios above.
- **Metrics:** DeepEval contextual precision/recall/relevancy, faithfulness, answer relevancy, hallucination; custom deterministic checks for tenant isolation (zero foreign-agency evidence), citation validity, insufficient-information correctness, clarification on ambiguity. Judge runs on synthetic or approved data only.
- **A/B:** `RERANKER_PROVIDER=none` vs `cross_encoder`, candidate-K/top-N sweeps, answer-model comparison.
- **Initial gate:** isolation 100%, citation validity ≥ 98%, faithfulness ≥ 0.85, contextual precision ≥ 0.7; tune after the first baseline. A gate failure blocks S4.

## 9. Observability baseline (now)

structlog JSON with `request_id`, `correlation_id`, `agency`; per-node latency and counts; LLM token usage and model; LangSmith traces redacted by default; readiness checks; no content in logs. Metrics and distributed tracing arrive through the seams below.

## 10. Deferred enhancements and the seam each already has

| Enhancement | Seam in place now | Added later without touching callers |
|---|---|---|
| Cognito auth | `get_current_user` dependency returning `UserDetails` (stub now); `RequestContext.user_details` | JWT/JWKS verification (`pyjwt`), session↔user binding, real `created_by` |
| OpenTelemetry / metrics | `@traced_node` fans out to sinks | OTel exporter + FastAPI/SQLAlchemy/httpx instrumentation, Prometheus |
| Sentry | single exception-handler boundary in `main.py` | `sentry-sdk` init with PII scrubbing |
| Redis cache / rate limiting | `AgencyResolver` TTL cache interface; middleware slot | Redis-backed cache and limiter (Redis already present after S5) |
| `sse-starlette` | one `encode_sse()` helper | swap the response class |
| JEV-style routing | `understand` node is an isolated, versioned prompt + schema | replace classifier logic |
| PII redaction service | `Redactor` hook before LLM/trace boundaries (allow-list implementation now) | Presidio-based implementation |
| Retry library | small stdlib `retry_async` helper for Qdrant/inference calls; SDK retries for LLMs | drop-in `tenacity` |

## 11. Dependency ledger

- **Remove:** `pgvector`, `asyncpg`, `psycopg2-binary`.
- **Add (runtime):** `structlog`, `langsmith` (explicit), `langchain-anthropic`, `langchain-openai`, `arq` (S5, brings Redis client), `deepeval` (S3), `orjson` only if profiling justifies.
- **Add (dev):** `ruff`, `mypy`, `pytest-asyncio`, `pytest-cov`, `testcontainers`, `httpx`, `pre-commit`, `pip-audit`, `bandit`.
- **Keep:** `fastapi`, `uvicorn`, `gunicorn`, `sqlalchemy`, `alembic`, `psycopg[binary]`, `pydantic-settings`, `qdrant-client`, `sentence-transformers`, `torch` (CPU index), `langgraph`, `langgraph-supervisor`, `langgraph-checkpoint-postgres`, `langchain-core`, `starlette-context`, `aioboto3`, `uuid-utils`, `python-dateutil`.
- Every addition still gets a quick approval step at the moment it is installed (`CLAUDE.md` §5); this ledger records the decisions already made.

## 12. Open items (defaults apply)

| Item | Default |
|---|---|
| Chat history retention | 30 days, purge job in S5 |
| PII sent to LLM/judge | party names allowed; SSN, licence, card never; addresses, vehicle plate/VIN, payee email/address embedded (decided in S2) |
| Limits | 6 history turns, 12k context tokens, target p95 < 8 s non-streaming |
| JEV routing | revisit after S3 baseline |
| Production hosting for Qdrant/inference/Redis | decide at S5; compose is dev-only |
| Postgres image | keep `timescaledb-ha:pg18-oss` (Postgres 18 needed for `uuidv7()`) |
| CI provider | GitHub Actions assumed |

## 13. Risks

| Risk | Mitigation |
|---|---|
| Driver switch to psycopg 3 changes behavior for `data_ingestion` | S0.4 spike and contract tests before anything else builds on it |
| Qdrant becomes the only vector copy | rebuild script (reindex per agency), `vector_sync` retry rule, volume backups |
| Switching embedding provider triggers full reindex | indexing key based on model + version, not provider name |
| `--reload` in the Dockerfile CMD | override the command in prod deployment; revisit when you want the Dockerfile changed |
| `session_context` error logging may include SQL parameters (kept per your answer) | optional S0.10 fix; revisit before handling real PII |
| `created_by`/`modified_by` hardcoded to `"uuid1"` (kept) | fixed with auth (Cognito) |
| Case ambiguity (same number, similar names) | candidates + clarification, never a silent pick |
| Tenant context lost inside agent tool calls | concurrency/isolation tests in S1 and S4 |
| LangSmith exposing case data | redacted by default; per-environment opt-in |
| Agent loops and cost | iteration, recursion and token caps |
| `arq` low release activity | `enqueue` seam isolates it |
| Many Qdrant collections | ~50 agencies is comfortable; revisit single-collection + payload tenancy if it grows well past a few hundred |

## 14. Definition of done (every stage)

Router → Controller → Module respected; models unchanged except the approved S0.2 drop; tenant isolation tests for every new path; async I/O only; Pydantic schemas on API boundaries; grounding/insufficient-info tested; no content in logs/traces; ruff, mypy, tests and coverage gates green in CI; `PLAN.md` statuses and the short `CHECKPOINT.md` updated.

## 15. Order

```
S0 hygiene (3.14, drop pgvector, one driver, logging, health, tooling, tests scaffold)
  ├─► S1 platform seams ─┐
  └─► S2 data coverage ──┴─► S3 answer pipeline + eval gate ─► S4 multi-agent ─► S5 jobs & breadth
```

S1 and S2 can run in parallel after S0.
