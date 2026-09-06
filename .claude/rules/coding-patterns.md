# Pluggable Component Pattern

## Purpose

Quick Chat has several subsystems that will grow multiple interchangeable
implementations over time: embedding providers, LLM providers, projectors,
chunkers, retrievers, file parsers. Left unmanaged, these tend to collapse
into one growing file with an `if/elif` chain switching on a config string.

This file defines the **one pattern** every such subsystem must follow, so
the codebase stays consistent regardless of which agent or engineer touches
it next. `src/quick_chat_api/core/llm/embedding/` is the canonical,
already-implemented reference — when in doubt, read that package instead of
re-deriving the pattern from this description.

Do not invent a different plugin mechanism for a new subsystem. Do not add
a new `if provider == "x"` branch to route provider selection. Follow this
pattern or ask before deviating.

---

## The pattern: Interface + Registry + Factory

Every pluggable subsystem is a package with this exact shape:

```text
<subsystem>/
├── __init__.py          # public re-exports only — the package's external API
├── base.py              # the abstract interface (ABC) — no implementation logic
├── exceptions.py         # typed exception hierarchy for this subsystem
├── registry.py            # @register_x decorator + build_x() lookup
├── factory.py            # get_x() — reads Settings, builds via registry, caches
└── providers/            # or impls/, backends/ — one file per implementation
    ├── __init__.py       # imports every impl module (triggers self-registration)
    └── <impl_name>.py    # one concrete class + its @register_x(...) builder
```

Reference implementation: `src/quick_chat_api/core/llm/embedding/`
(`base.py: EmbeddingProvider`, `registry.py`, `factory.py: get_embedding_provider()`,
`providers/local_sentence_transformer.py`).

### Why this shape, not a simpler one

- **`base.py` is the only thing callers may import.** Application code
  (controllers, modules, ingestion, retrieval) depends on the interface,
  never on a concrete class. Swapping an implementation is a config change
  (`Settings.EMBEDDING_PROVIDER`, etc.), not a code change at every call site.
- **The registry decouples the factory from concrete implementations.**
  `factory.py` and `registry.py` never need to change when a new
  implementation is added — only `providers/__init__.py` gains one import
  line, and a new file appears under `providers/`. This is what prevents the
  `if/elif` chain from ever forming.
- **`exceptions.py` gives callers something precise to catch** —
  `EmbeddingProviderError` and its subclasses, never a bare `RuntimeError`
  or `ValueError`. Mirrors `CLAUDE.md` §19 (no swallowed/generic exceptions).
- **`factory.py` owns caching.** Expensive-to-construct things (a loaded
  model, an HTTP client, a connection) are built once per process via
  `functools.lru_cache`, not per request/call. Callers never call a
  provider's constructor directly.

---

## Rules for each file

- **`base.py`** — an `ABC` with `@abstractmethod`s only. No default logic,
  no shared implementation. If two implementations need shared code, put it
  in a separate shared module they both import, not in the base class.
- **`exceptions.py`** — one base error for the subsystem
  (`XProviderError(RuntimeError)`), plus specific subclasses for each
  distinct failure mode a caller might want to handle differently
  (e.g. `UnknownXProviderError`, `XDimensionMismatchError`).
- **`registry.py`** — generic, has zero knowledge of any specific
  implementation. Exposes `register_x(name)` (decorator) and
  `build_x(name, settings)` (lookup + construct). Raises the subsystem's
  "unknown name" exception with the list of currently-registered names in
  the message — never a bare `KeyError`.
- **`providers/<impl>.py`** — one implementation class + one small builder
  function decorated with `@register_x("name")` that reads whatever it
  needs from `Settings` and constructs the class. Heavy/optional imports
  (e.g. `torch`, an SDK client) are imported inside the class's `__init__`,
  not at module top level, so importing the package never pulls in a
  dependency that isn't actually selected.
- **`providers/__init__.py`** — imports every implementation module purely
  for its registration side effect. This is the **only** file that needs a
  new line when a new implementation is added.
- **`factory.py`** — one `@lru_cache`-decorated `get_x()` function. Reads
  `Settings`, calls `registry.build_x(...)`. No business logic here beyond
  wiring config to the registry.
- **`__init__.py` (package root)** — re-exports the interface, the public
  exceptions, and `get_x()`. Nothing else is part of the public surface;
  internal modules (`registry`, `providers.*`) are implementation detail
  callers should not import directly.

---

## Checklist: adding a new implementation to an existing subsystem

Example: adding an OpenAI embedding provider alongside the local one.

1. Add any new required `Settings` fields (e.g. `EMBEDDING_API_KEY` — likely
   already present; add provider-specific ones as needed). New third-party
   SDK dependency → ask for approval first (`CLAUDE.md` §5).
2. Create `providers/openai.py`: the implementation class + a
   `@register_provider("openai")` builder function.
3. Add one import line to `providers/__init__.py`.
4. Do not touch `base.py`, `registry.py`, or `factory.py`.
5. Switch to it via `EMBEDDING_PROVIDER=openai` in env — no other code
   changes.
6. Add a unit test for the new provider (mock the SDK call) plus a
   dimension-mismatch test if applicable.

## Checklist: introducing a brand-new pluggable subsystem

Example: chunking strategies, projectors, retrievers.

1. Confirm it actually needs multiple interchangeable implementations. If
   there is and will only ever be one implementation, this pattern is
   overkill — a single module is fine (see "When not to use this pattern").
2. Scaffold the package shape above under the appropriate layer
   (`core/` for infra-like things such as embeddings/LLMs, `modules/` for
   domain logic such as projectors/chunkers — see `.claude/rules/architecture.md`).
3. Write `base.py` first — the interface is the design decision; get it
   right before writing any implementation.
4. Write `exceptions.py` next.
5. Write the registry + factory (copy `embedding/registry.py` and
   `embedding/factory.py`, rename).
6. Write the first implementation under `providers/`.
7. Wire any new config into `Settings` (`settings/config.py`) — magic
   strings/numbers belong in env-driven config, not hardcoded in the
   implementation.

---

## When *not* to use this pattern

- A single, fixed implementation with no realistic near-term alternative
  (e.g. "the Postgres session factory") does not need an ABC/registry —
  that's the "New abstraction" tier at the bottom of `CLAUDE.md` §30's
  preference order. Don't build a registry for something that will only
  ever have one implementation.
- Simple value objects, Pydantic schemas, and one-off scripts don't need
  this shape.
- If unsure whether a component will grow multiple implementations, prefer
  a plain module/class first; upgrade to this pattern when the second
  implementation actually shows up (YAGNI still applies — this pattern
  exists to prevent a *mess* once there are 2+ implementations, not to be
  applied speculatively to everything).

---

## General code quality rules (apply everywhere, not just plugin packages)

These restate and sharpen `CLAUDE.md` §4 specifically for how an agent
should write code in this repo:

- Full type hints on every function signature, including return types.
- No comments that restate what the code does. A comment is only for a
  non-obvious *why* (a workaround, a constraint from an external system, a
  subtle invariant).
- No bare `except Exception`. Catch specific exceptions; let unexpected
  ones propagate and be logged at the boundary that owns error handling.
- No magic strings/numbers for anything configurable — read from `Settings`.
- No new dependency without asking first, regardless of how small.
- Never construct a pluggable component's implementation class directly
  from application code — always go through that subsystem's `get_x()`.
- Docstrings: one line is usually enough. Reserve multi-line docstrings for
  the module/class level where the "why" genuinely needs explaining (see
  `embedding/registry.py` for the level of detail expected — not more, not
  less).
- Before adding a file, check whether an existing package in this pattern
  already covers the need (e.g. don't add a second embedding-provider
  mechanism because it seemed easier than reading this file).

---

## Why instructions are laid out this way (context for future agents)

This repo intentionally layers its instructions the way mature GenAI/ML
platform teams structure agent-facing documentation, so it's worth naming
the layering explicitly rather than re-deriving it every session:

1. **`CLAUDE.md`** — the constitution. Architecture, priorities, and hard
   invariants (tenant isolation, model-file immutability, RAG grounding).
   Rarely changes. States *what must always be true*.
2. **`.claude/rules/*.md`** (this file included) — topic-scoped, enforceable
   rules that expand on the constitution for a specific concern
   (architecture, database, RAG, and now pluggable-component patterns).
   Each file is short, single-purpose, and independently loadable — an
   agent working only on embeddings doesn't need to re-read database rules,
   but both always load automatically alongside `CLAUDE.md`.
3. **A canonical reference implementation** (`core/llm/embedding/`) —
   mature teams don't just describe a pattern in prose, they point at one
   real, working example and say "match this." Prose rules drift from code
   over time; a working reference doesn't. When this file and the actual
   code under `embedding/` disagree, treat the code as ground truth and
   flag the mismatch rather than trusting the doc blindly.
4. **`PLAN.md`** — the living spec: what's being built, in what order, and
   what's already been verified against the real repo (not assumed).
5. **`CHECKPOINT.md`** — the living session log: what was decided, what's
   still open, and the next concrete action. This is what lets a session
   with no memory of previous conversations resume cold instead of
   re-litigating settled decisions (e.g. "local embeddings use
   sentence-transformers, 768-dim, migration owned by the user").

The reason this layering matters in practice: an agent should never need to
scroll back through chat history to know how to structure new code. It
should be able to open `.claude/rules/coding-patterns.md`, look at
`core/llm/embedding/`, and produce code indistinguishable in shape from
what's already there — every time, regardless of which session or model
wrote it.
