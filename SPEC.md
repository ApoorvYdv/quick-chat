# Product specification — quick-chat

> Status: draft. A coding agent must not implement product code until this specification is approved through Genesis.
> Scope: replaces the single-case-scoped answer pipeline (PLAN.md S3 `resolve_case`-first design and S4 agent split) with an agentic, multi-agent RAG flow. PLAN.md S0–S2 work stays as built. Decisions referenced as `DECISION-*` are recorded in Genesis.

## Problem

Quick Chat answers natural-language questions about court case data for multi-tenant agencies. Today every question is forced through a single resolved case (`core/rag/graph.py`: `understand → resolve_case → retrieve → …`, all placeholders), so cross-case questions such as "find all the cases for defendant John Maxwell" or "find all REGISTERED cases for hearing date 10/10/2026" cannot be answered. Structured tools exist only per `case_id` (`get_payment_summary`, `get_appearances`, `get_cases_by_number`), vector search is dense-only with no reranker, and there are no evals.

Desired outcome: a production-ready agentic RAG system that routes each question to the right domain agents (Case, Financial, Procedural), uses deterministic structured queries where the answer is exact and hybrid + reranked semantic retrieval where it is not, has a supervisor check that retrieved context is relevant and retry within a limit, and generates grounded, cited answers. Every step must be traced and evaluated.

## Users

- **Agency staff (court clerks, case managers)**: ask single-case, cross-case and multi-domain questions through the chat API. Affected by wrong-case answers, which are the worst failure.
- **Engineers / operators**: diagnose quality and latency through structured logs, LangSmith traces and eval reports, without seeing case content.
- **Parties named in records (defendants, payees)**: affected through privacy. Their PII must never leak across tenants or into logs and traces.

## Functional requirements

- FR-1: **Query understanding and rewrite.** For each question, produce (a) extracted entities: case numbers, party names with role, dates normalized to the agency timezone, appearance/case statuses, and (b) one self-contained sub-query per selected agent, resolving pronouns and follow-ups from the session's chat history.
- FR-2: **Deterministic-first routing.** Select the agent set (Case, Financial, Procedural, or any combination) with deterministic rules first (case-number pattern, domain keyword sets, extracted entity types). Fall back to an LLM structured-output classifier only when the rules produce no route or conflicting routes. Record the route and its source (`rule` or `llm`) on the request trace.
- FR-3: **Agent execution.** A single-domain question runs one agent. A multi-domain question runs the selected agents concurrently. When an agent needs case identifiers that another agent resolves (for example, Financial for a party name), the Case agent's structured lookup runs first and its resolved case IDs are passed on.
- FR-4: **Case agent: structured.** (a) Lookup by case number, returning every matching case. (b) Lookup by party name and optional role: case-insensitive exact match first, then `pg_trgm` similarity; several plausible people are returned as candidates with case numbers, never silently picked (DECISION "Party-name matching"). (c) Cross-case filter by case attributes (case status, case type, case-record dates). Each list returns at most 20 cases, the total match count, and a truncation flag (DECISION "Cross-case list cap 20").
- FR-5: **Case agent: vector.** Hybrid retrieval (FR-8) and reranking (FR-9) over the source types `case`, `case_summary`, `party`, `charge`, `criminal`, `vehicle` and `address`. Results are scoped to resolved case IDs when there are any, and agency-wide otherwise.
- FR-6: **Financial agent: structured only.** Fetch payment information for one or more resolved cases through the existing `get_payment_summary` function (void payments excluded, non-void total). No vector search. Designed so further structured financial queries can be added as tools without changing the agent contract.
- FR-7: **Procedural agent.** (a) Structured appearances for resolved cases (`get_appearances`, `get_next_appearance`). (b) A cross-case appearance filter by appearance status (for example `REGISTERED`) and hearing date, with the same 20-case cap, total count and truncation flag as FR-4. (c) Hybrid retrieval and reranking over `disposition` and `sanction` chunks.
- FR-8: **Hybrid retrieval.** Each agency's Qdrant collection stores a dense vector and a sparse BM25 vector per chunk. A query runs both and fuses them with RRF inside Qdrant, returning 10 candidates. Filters for agency collection, case IDs and source types apply store-side, never as a Python post-filter (DECISION "Hybrid search").
- FR-9: **Reranking.** A local cross-encoder in `quick_chat_inference` (`/rerank`) scores the 10 candidates against the agent's sub-query. The top 5 are kept, and candidates below a configurable minimum score are dropped. Reranking only reorders and trims; it never widens scope (DECISION "Reranker").
- FR-10: **Supervisor relevance check.** The supervisor grades each agent's returned context for relevance to that agent's sub-query. On a fail it rewrites the sub-query and retries that agent, at most 2 times per agent (DECISION "Supervisor retries"). After that it continues with only the relevant context, or marks the domain as insufficient.
- FR-11: **Context construction.** Merge agent outputs: drop irrelevant items, dedupe by `source_table` + `source_record_id` (preferring the most specific chunk), prefer structured rows over chunks for the same fact, keep source metadata (agency, case_record_id, source_table, source_record_id, chunk_id) and case boundaries, fit `CONTEXT_MAX_TOKENS`, and detect conflicts (same field, different values).
- FR-12: **Grounded generation.** Claude generates `{answer, citations, insufficient_information, conflicts}` from the constructed context only (DECISION "LLM provider"). Citations not present in the supplied context are dropped. Ambiguous candidates produce `needs_clarification`. Empty evidence produces the insufficient-information answer with no LLM call. List answers state the total and whether the list was truncated.
- FR-13: **API compatibility.** `POST /ask` and `POST /cases/{case_id}/ask` (JSON and SSE) keep the `AskRequest`/`AskResponse` contracts, the agency-schema checkpointer and `thread_id = "{agency}:{session_id}"`. A supplied `case_id` scopes every agent to that case. `AskResponse` may gain optional fields only, with no breaking change.
- FR-14: **Logging and tracing.** Each step (rewrite, route, every agent, every tool call, hybrid retrieval, rerank, supervisor grade and retry, context build, generate) emits a structlog event and a LangSmith child run nested under one request run, carrying ids, counts, scores, route source, retry count, latency, model, prompt version and token usage. Inputs and outputs are redacted by default. Content capture is a per-environment opt-in.
- FR-15: **Evals per agent and per component.** Golden datasets under `evals/datasets/`, plus a single command that reports scores for: rewrite (entity extraction exact match), router (route accuracy, LLM-fallback rate), each structured tool (exact match against SQL ground truth), hybrid retrieval (recall@10, MRR), reranker (precision@5 and nDCG uplift versus no rerank), supervisor (grading accuracy, retry rate), each agent end to end (contextual precision and recall), and the full pipeline (faithfulness, answer relevancy, citation validity, insufficient-information correctness, isolation). Results can be logged to LangSmith as experiments.
- FR-16: **Re-indexing.** Recreate each agency collection with dense and sparse vectors and re-ingest it through the existing `backfill_embeddings.py` / `CaseIngestionService` path, without changing `data_ingestion/`.

## Non-functional requirements

- NFR-1: **Tenant isolation.** Every tool, retrieval call, agent, retry and checkpoint is bound to `RequestContext.agency`. No tool takes a tenant or user identifier as an argument. Any case ID outside the current tenant, or outside the resolved set when a scope exists, is rejected. Holds under concurrent requests for different agencies.
- NFR-2: **Grounding.** No fabricated names, dates, charges, payments, hearings, sanctions, dispositions, amounts or case events. Conflicting records are reported, never silently resolved.
- NFR-3: **Prompt injection.** Retrieved content is delimited data in every prompt (rewrite, supervisor, generate) and can never change routing, tenant, authorization or tool arguments.
- NFR-4: **Privacy.** No case content, prompt, chunk, or LLM output appears in logs, or in LangSmith while redaction is on. Payment card and method fields are never embedded or sent to the LLM.
- NFR-5: **Latency.** End-to-end non-streaming p95 under 12 s on the golden set against the dev dataset, with per-node p50 and p95 reported (DECISION "Latency target").
- NFR-6: **Bounded cost and loops.** Hard caps on supervisor retries (2 per agent), graph recursion limit, `AGENT_MAX_ITERATIONS`, and a per-request token budget. LLM calls use SDK timeouts and retries.
- NFR-7: **Quality gate.** Isolation 100%, citation validity ≥ 98%, faithfulness ≥ 0.85, contextual precision ≥ 0.7, answer relevancy ≥ 0.8, routing accuracy ≥ 95%, structured-tool exact match 100% (DECISION "Eval release gate").
- NFR-8: **Engineering standards.** Router → Controller → Module, `RequestContext`, `ErrorResponse`, the Interface + Registry + Factory pattern for pluggable pieces (reranker, sparse encoder), async I/O, Pydantic boundaries, ruff and mypy clean, `core/models/` unchanged, `data_ingestion/` unchanged.

## Constraints

- PostgreSQL is the source of truth. Qdrant uses one collection per agency (v1.19.1). One psycopg 3 pool is shared by everything.
- `core/models/` must not change. Party-name trigram indexes (`idx_full_name_trgm`, `idx_first_name_trgm`, `idx_last_name_trgm`) already exist.
- New dependencies need approval at install time (CLAUDE.md §5). Expected: `langchain-anthropic`, and possibly a BM25 sparse encoder (see Open questions).
- Claude via Anthropic is the answer, supervisor, rewrite and routing-fallback model. Ollama stays registered for local development.
- Retrieved text and party PII stay inside the tenant and the local inference service, except the evidence sent to Claude for generation and grading.
- `data_ingestion/` is a frozen surface.

## Non-goals

- Authentication and authorization (Cognito). The `get_current_user` stub stays.
- Financial queries beyond payments for resolved cases (balances, assessed amounts, payee search). These are planned extensions.
- File and document ingestion (PDF, DOCX, OCR), new projectors, or changes to database models.
- UI, OpenTelemetry metrics, Redis caching and rate limiting, background jobs.
- Automatic tuning of top-K or thresholds beyond the eval sweeps.

## Acceptance criteria

- AC-1: On the dev agency, "find all the cases for defendant John Maxwell" (with a seeded or existing matching DEFENDANT) routes to the Case agent by rule, with no LLM routing call. It returns exactly the cases that SQL ground truth returns (up to 20, with the total), each with a citation.
- AC-2: "find all REGISTERED cases for hearing date 10/10/2026" returns exactly the cases whose appearance has status `REGISTERED` and a hearing date of 2026-10-10 per SQL ground truth, with the total and truncation flag.
- AC-3: A question spanning payments and hearings for one case number runs the Financial and Procedural agents concurrently and returns one answer citing evidence from both.
- AC-4: A test with a stub agent whose context is graded irrelevant shows exactly 2 retries for that agent, then an insufficient-information outcome for that domain and no further retries.
- AC-5: Hybrid retrieval returns at most 10 candidates and the reranker at most 5. A test proves the agency collection, case-ID and source-type filters are applied in the Qdrant query.
- AC-6: Cross-tenant tests for every new tool, agent and retrieval path, including concurrent requests for two agencies, show zero foreign-agency evidence.
- AC-7: Empty evidence produces no LLM generation call. A citation ID not present in the supplied context is dropped from the response.
- AC-8: An ambiguous party name returns `needs_clarification` with candidate case numbers. A list with more than 20 matches returns 20, the true total, and a truncation statement.
- AC-9: With LangSmith enabled and redaction on, one request produces a single parent run with child runs for rewrite, route, each agent, each tool, retrieval, rerank, supervisor and generate. A test proves no case content appears in the run inputs or outputs.
- AC-10: One documented eval command produces per-agent and per-component scores (FR-15), and the scores meet NFR-7 on the golden set.
- AC-11: The p95 end-to-end non-streaming latency over the golden set is under 12 s, with per-node p95 reported.
- AC-12: Existing tests, contract tests (`data_ingestion` frozen surface), ruff and mypy pass, and `git diff` shows no change under `core/models/` or `data_ingestion/`.

## Risks

- **Re-index cost and downtime.** Adding sparse vectors means recreating every agency collection. Mitigation: re-ingest per agency through the existing backfill path, with an alias or recreate-then-swap per collection.
- **Wrong-person match from fuzzy names.** Mitigation: exact match first, a similarity threshold, candidate lists with clarification, and eval cases with similar names.
- **Router misroutes multi-domain questions.** Mitigation: rule coverage measured by router evals, LLM fallback on conflict, and a routing-accuracy gate.
- **Supervisor grading drift or loops.** Mitigation: a hard cap of 2 retries, grading-accuracy evals, and recursion and token caps.
- **Latency from sequential case resolution plus retries.** Mitigation: concurrent agents, the p95 gate, and per-node timing.
- **PII leaving the tenant via LLM or traces.** Mitigation: redaction by default and a test asserting no content in traces.
- **Small golden set overfitting thresholds.** Mitigation: development and holdout splits, plus a second synthetic agency.

## Open questions

- **Which column is the hearing date?** In the data, `REGISTERED` is `case_appearance.status`. "Hearing date" could be `case_appearance.due_date` or `case_record.hearing_date`. Default: `case_appearance.due_date` for appearance-status questions, and `case_record.hearing_date` only when no appearance filter is involved.
- **How are BM25 sparse vectors produced?** Options are Qdrant server-side BM25 inference, if the pinned v1.19.1 OSS image supports it, or the `fastembed` client-side encoder, which is a new dependency. Default: verify server-side first, and ask for approval before adding `fastembed`.
- **Who authors the golden dataset?** Default: generated from the `southern_ute` dev data plus a synthetic second agency, reviewed by the owner before thresholds are treated as binding.
- **How does PLAN.md relate to this spec?** Default: this spec supersedes PLAN.md S3/S4, and PLAN.md is updated to point here once the plan is approved.
