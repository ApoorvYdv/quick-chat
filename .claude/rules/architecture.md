# Architecture Rules

## Application Architecture

Quick Chat follows:

```text
Router
  ↓
Controller
  ↓
Module
  ↓
Database / Retrieval
```

Keep responsibilities separated.

### Router

Routers handle:

- HTTP routes
- Request validation
- Response models
- HTTP-specific concerns

Routers must not contain:

- Database queries
- Complex business logic
- RAG orchestration
- LLM prompt construction

### Controller

Controllers coordinate application-level behavior.

They may orchestrate:

- Modules
- Retrieval
- Business rules
- Response construction

Keep controllers small. Move reusable or complex logic into focused modules/services.

### Module

Modules contain persistence and domain operations.

They may contain:

- SQLAlchemy queries
- CRUD operations
- PostgreSQL operations
- Vector retrieval
- Data access logic

Modules must not depend on FastAPI request/response objects.

## Coding Practices

- Use Python type hints.
- Use async functions for I/O-bound work.
- Keep functions small and focused.
- Reuse existing project abstractions.
- Prefer clear code over clever abstractions.
- Do not introduce a new dependency without approval.
- Do not create duplicate database engines, configuration systems, or logging systems.
- Read existing code before modifying it.

## Change Strategy

For a feature:

1. Trace the existing request flow.
2. Identify reusable code.
3. Make the smallest appropriate change.
4. Preserve existing behavior.
5. Add or update tests when practical.

Do not rewrite unrelated code while implementing a feature.
