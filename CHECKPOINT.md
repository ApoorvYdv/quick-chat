# Checkpoint

Short living log; newest on top. Build history before S0 is in `docs/history/CHECKPOINT-2026-09.md`. The forward plan is `PLAN.md`.

## 2026-10-03 — S0 foundation hygiene

Done: Python 3.14 refs; pgvector and the `ai_knowledge_source`/`ai_knowledge_chunk` models removed (Qdrant is the only chunk store: text, `content_hash`, `indexing_key` live in the payload; point ids are deterministic per entity+chunk index; `retrieve(agency, query, ...)` no longer takes a session); Qdrant pinned to v1.19.1 with healthchecks; one psycopg 3 driver (spike passed, incl. checkpointer on the shared pool); structlog JSON logging; `/healthz` + `/readyz`, lifespan engine dispose, generic 500 handler; UUID PKs in the existing config migration, `RequestContext` cleanup, per-agency timezone; ruff/mypy/bandit/pip-audit/pre-commit (CI deferred); fakes, `integration` marker and three contract tests.

Open (owner):
- The config migration was edited in place (UUID PKs); recreate any DB that already ran it.
- `Dockerfile` default `CMD` still has `--reload`; override it in production.
