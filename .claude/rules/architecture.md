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

### Router + Controller wiring pattern (concrete — follow this for every route)

Every router/controller pair in this app follows the same shape. Do not
invent a per-route variation (a plain function controller, an inline
`agency: str = Depends(...)` parameter threaded through every endpoint,
etc.) — match the reference implementation below every time, regardless of
which agent or engineer adds the next route.

Reference implementation: [`routers/ingestion_router.py`](../../src/quick_chat_api/routers/ingestion_router.py)
+ [`core/controllers/ingestion_controller.py`](../../src/quick_chat_api/core/controllers/ingestion_controller.py).

- **Controller is a class, constructed via FastAPI's class-based `Depends()`.**
  `__init__` declares its dependencies as `Annotated[T, Depends(get_x)]`
  parameters (e.g. `engine: Annotated[AsyncEngine, Depends(get_async_engine)]`).
  Endpoints receive it as `controller: Annotated[XController, Depends()]` —
  never construct a controller directly (`XController(...)`) inside a route
  function.
- **Tenant/request-scoped data is never passed as an explicit function
  argument between router → controller → module.** The controller reads it
  from `RequestContext` (`utils/context.py`) inside `__init__` or the method
  body — e.g. `self.agency = RequestContext.agency`. A route function must
  not accept `agency: str` (or `user`, etc.) as its own parameter and forward
  it manually; that's what `RequestContext` exists to eliminate.
- **Tenant resolution happens once, at the router level**, via a header
  dependency declared on the `APIRouter` itself:
  `APIRouter(..., dependencies=[Depends(get_agency_header)])`
  (`utils/dependencies.py:get_agency_header`) — not repeated per-endpoint.
  That dependency validates the header and writes it into `RequestContext`;
  every endpoint under that router can then rely on `RequestContext.agency`
  being populated.
- **Every endpoint delegates to exactly one controller method** and maps
  known business exceptions to `HTTPException` with a status code — using a
  message from `ErrorResponse` (see below), never an inline string. Unexpected
  exceptions are not caught here; they propagate to be logged/handled at the
  boundary that owns that (`CLAUDE.md` §19).
- **Response bodies are Pydantic schemas** (`core/schemas/<domain>.py`),
  built via a `from_result(...)`-style classmethod from the module's return
  value — routers never return an ORM object or a raw dict.

### Module

Modules contain persistence and domain operations.

They may contain:

- SQLAlchemy queries
- CRUD operations
- PostgreSQL operations
- Vector retrieval
- Data access logic

Modules must not depend on FastAPI request/response objects.

## Request Context

`RequestContext` (`utils/context.py`) is the single, typed facade for
per-request state — agency/tenant, authenticated user details, active
config, and anything else request-scoped. It is backed by
`starlette_context`'s per-request `ContextVar` (wired in `main.py` via
`RawContextMiddleware`), so concurrent requests never interfere with each
other even though the underlying storage looks like a shared global.

- **Read/write via `RequestContext.<field>`, never via a raw
  `starlette_context.context.get(...)`/`.update(...)` call** outside
  `utils/context.py` itself — that file is the only place allowed to know
  the underlying storage mechanism.
- **A dependency populates it, not the controller/module.** e.g.
  `get_agency_header` (`utils/dependencies.py`) validates the incoming
  header and sets `RequestContext.agency = agency`. Controllers/modules
  further down only ever *read* it.
- **Anything that needs request-scoped data reads `RequestContext`
  directly** instead of accepting it as a parameter threaded through every
  call in between. This keeps module/service signatures
  (`CaseIngestionService(engine, agency)` is the one exception, since it's
  constructed once per call from a controller that already resolved
  `agency` — see the reference implementation) free of parameters that
  exist only to relay context, not to express that function's actual
  inputs.
- Do not add a new field to `RequestContext` for something that is only
  ever needed within a single request handler's own call stack and can be
  passed as a normal argument — this facade is for state that would
  otherwise have to be threaded through multiple unrelated layers
  (router → controller → module).

## Error Responses

Every client-facing (4xx) error message is a named constant on
`core/constants/error_response.py:ErrorResponse` — never an inline literal
string in an `HTTPException(detail=...)` call, in a router, controller,
module, or dependency.

```python
from quick_chat_api.core.constants.error_response import ErrorResponse

raise HTTPException(status_code=404, detail=ErrorResponse.AGENCY_NOT_FOUND)
```

- Adding a new client-facing error means adding one constant to
  `ErrorResponse` and referencing it — not writing a new string wherever the
  error is raised.
- Keep messages generic/stable (e.g. `CASE_NOT_FOUND = "Case not found."`)
  rather than interpolating request-specific detail (IDs, internal state)
  into the client-facing string — that avoids leaking internal detail to
  clients (`CLAUDE.md` §19/§20) and keeps the constant reusable across every
  call site that raises the same error. If request-specific detail is
  useful for debugging, log it server-side; don't put it in `detail`.
- This applies to 4xx (client) errors only. It is not where unexpected
  5xx-class failures get their message — those are logged and returned as a
  generic error at the boundary that owns them, per `CLAUDE.md` §19.

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
