# Feature 01 — AI Knowledge Foundation

## Objective

Create the database and configuration foundation for the AI knowledge layer without modifying existing transactional tables with embedding columns.

## Outcome

The application has a centralized PostgreSQL/pgvector schema that can store logical knowledge documents and their versioned vectorized chunks.

## Scope

### Repository discovery

Before changing code, inspect:

- PostgreSQL connection/version
- `AgencyBase`
- tenant/agency isolation
- SQLAlchemy async setup
- Alembic setup
- existing vector/Qdrant implementation
- existing application configuration patterns

### Database

Enable pgvector through Alembic migration.

Create `ai_knowledge_document` with at least:

- `id`
- `case_record_id`
- `source_type`
- `source_table`
- `source_id`
- `external_id`
- `title`
- `mime_type`
- `storage_uri`
- `content_hash`
- `source_metadata`
- `status`
- `created_at`
- `updated_at`

Create `ai_knowledge_chunk` with at least:

- `id`
- `document_id`
- `case_record_id`
- `chunk_index`
- `content`
- `content_hash`
- `token_count`
- `embedding`
- `embedding_model`
- `embedding_version`
- `metadata`
- `created_at`

The vector dimension must be configurable and consistent with the configured embedding model.

### Indexing

Add indexes for:

- case ID
- document ID
- source identity
- tenant/agency identity where required
- HNSW cosine similarity on the embedding column

Add appropriate uniqueness constraints to prevent duplicate source/document records.

### SQLAlchemy

Create SQLAlchemy models for both knowledge tables using the project's existing conventions.

### Configuration

Add typed configuration for:

- embedding provider
- embedding model
- embedding dimension
- embedding version
- projection version
- chunking version
- parser version

Do not hardcode provider/model values inside service code.

## Non-goals

- No case ingestion yet.
- No file parsing yet.
- No embedding API calls yet.
- No retrieval API yet.
- No changes to existing transactional tables.

## Acceptance criteria

- Alembic upgrade succeeds on a clean database.
- Alembic downgrade is safe and complete for the new objects.
- pgvector extension exists after migration.
- Both SQLAlchemy models load successfully.
- HNSW index is present.
- Required tenant/case/source indexes exist.
- Configuration validates at application startup.
- Tests cover model creation and schema assumptions.
- Existing test suite remains green.

## Deliverables

- Alembic migration(s)
- SQLAlchemy models
- config changes
- schema tests
- short developer documentation
