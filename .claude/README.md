# Claude Code Project Configuration

This directory contains project-specific Claude Code configuration for Quick Chat.

## Structure

```text
.claude/
├── README.md
├── settings.json
└── rules/
    ├── architecture.md
    ├── database.md
    └── rag.md
```

## Responsibilities

- `settings.json` — safe Claude Code permissions and project settings.
- `rules/architecture.md` — application architecture and coding boundaries.
- `rules/database.md` — PostgreSQL, SQLAlchemy, tenant isolation, and model rules.
- `rules/rag.md` — RAG, pgvector, retrieval, grounding, and LLM rules.

The root `CLAUDE.md` remains the primary high-level project guide.

Keep this directory small. Add new rules only when a recurring project constraint deserves its own document.
