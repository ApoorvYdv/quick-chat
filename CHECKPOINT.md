# Checkpoint

Short living log; newest on top. Build history before S0 is in `docs/history/CHECKPOINT-2026-09.md`. The forward plan is `PLAN.md`.

## 2026-10-07 — S2 indexing done

Done: six new projectors (payment, disposition, sanction, criminal, vehicle, address) with the S2 field decisions recorded in `PLAN.md`; `CaseKnowledgeSourceAdapter` discovers them in one eager-loaded query; `SOURCE_TYPE_GROUPS` constant; Qdrant payload now carries `case_number`, `case_title`, `case_type`, `case_status`, `is_juvenile` (all indexed; indexes are also created on pre-existing collections); the content hash covers the case payload so a changed title/status re-embeds. `southern_ute` re-ingested: 1149 points across all 11 source types (100 case, 176 case_summary, 214 charge, 163 party, 130 appearance, 100 criminal, 87 address, 85 vehicle, 56 payment, 22 sanction, 16 disposition); payment chunks match the 56 Postgres payments. Acceptance verified: every group filter returns only its own types, financial plus `case_record_id` returns only that case's payments, no card/exp/method fields in payment chunks, every point has the case payload keys. 120 tests, ruff and mypy clean.

Open: structured query functions per domain and the domain map (rest of S2); reconcile `SOURCE_TYPE_GROUPS` with the S4 agent domains. Findings for S3: charge/disposition/sanction facts now appear in several chunk types (dedupe by `source_id`, prefer the specific chunk); chunks carry PII by design (payee email/address, plates, VIN, addresses), so S3 logging and tracing must keep chunk content out.

Next: structured query functions, then S3.

## 2026-10-05 — S0.11 real-data validation

Done: `create_tables → ingest_data → backfill_embeddings` run on local compose (Postgres + Qdrant) for agency `southern_ute` from `batch_1.json`: 100 cases in Postgres and Qdrant. `get_cases_by_number()` returns eager-loaded parties/charges/appearances/payments (unknown number → empty); `retrieve()` returns charge chunks for charge questions and `case_id` scoping is applied store-side. The `southern_ute` schema and its Qdrant collection are kept as the dev dataset for S2/S3.

Findings for S2/S3: a charge appears both as a `charge` chunk and inside a `case_summary` chunk, so context construction must dedupe by `source_id`; payment-balance and hearing-date questions retrieve poorly by vector (scores 0.37–0.47, no date ranking) and should route to structured Postgres; Ollama is not needed until S3.

Next: S2 data coverage, then S3.

## 2026-10-04 — S1 closed

Done: `understand.v1` prompt; `traced_node` now fans out to sinks (structlog always, redacted LangSmith when `LANGSMITH_ENABLED`; ids/counts/latency only, own flag so LangChain's auto-tracing of LLM content is never switched on); `get_current_user` anonymous stub on the chat router. S1 acceptance met except nothing new open.

Next: S0.11 (done 2026-10-05), then S2/S3. LLM is local Ollama only (qwen3:4b); S2 PII decision: payment, disposition, sanction, criminal, vehicle and address may all be embedded.

## 2026-10-04 — S1.7 checkpointer

Done: `core/rag/checkpointer.py` (`agency_checkpointer`: connection borrowed from the shared pool, `search_path` pinned to the agency schema and restored, lazy per-agency `setup()`); graph compiled per request with it; `thread_id = "{agency}:{session_id}"`. Only `messages` + `last_case_ids` persist (`evidence`/`contexts` are untracked channels; `initial_state` resets per-turn fields). Checkpointer failure → generic 5xx. Integration test proves per-schema isolation and a clean pool connection.

Open: session ids are client-chosen and unauthenticated until Cognito (risk accepted). Still in S1: inference service + `remote` embedder, concurrent-tenant test, `understand.v1`, LangSmith sink, `get_current_user` stub. Then S0.11.

## 2026-10-03 — S0 foundation hygiene

Done: Python 3.14 refs; pgvector and the `ai_knowledge_source`/`ai_knowledge_chunk` models removed (Qdrant is the only chunk store: text, `content_hash`, `indexing_key` live in the payload; point ids are deterministic per entity+chunk index; `retrieve(agency, query, ...)` no longer takes a session); Qdrant pinned to v1.19.1 with healthchecks; one psycopg 3 driver (spike passed, incl. checkpointer on the shared pool); structlog JSON logging; `/healthz` + `/readyz`, lifespan engine dispose, generic 500 handler; UUID PKs in the existing config migration, `RequestContext` cleanup, per-agency timezone; ruff/mypy/bandit/pip-audit/pre-commit (CI deferred); fakes, `integration` marker and three contract tests.

Open (owner):
- The config migration was edited in place (UUID PKs); recreate any DB that already ran it.
- `Dockerfile` default `CMD` still has `--reload`; override it in production.
