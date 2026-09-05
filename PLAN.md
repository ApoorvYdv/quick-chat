You are implementing a production-grade knowledge ingestion and retrieval layer for an existing FastAPI + SQLAlchemy Async + PostgreSQL application.

The application uses TigerCloud/PostgreSQL as the system of record.

The existing SQLAlchemy models include:

- CaseRecord
- Criminal
- VehicleDetail
- PartyDetail
- AddressDetail
- CaseCharge
- PaymentRecord
- ImposedDisposition
- ImposedSanction
- CaseAppearance

CaseRecord is the root entity and has relationships to appearances, criminal information, vehicles, parties, addresses, charges, sanctions, dispositions, and payments.

Do not modify existing transactional tables to add embedding columns.

Instead introduce a centralized AI knowledge layer in the same PostgreSQL database using pgvector.

OBJECTIVE

Build a unified retrieval/indexing system that can ingest:

1. Structured PostgreSQL records
2. Related records/entities
3. PDFs
4. DOCX files
5. TXT files
6. Images where OCR is supported
7. Other case attachments/files

All sources must normalize into a common knowledge document + chunk representation.

ARCHITECTURE

Create:

ai_knowledge_sources
ai_knowledge_chunk

ai_knowledge_source represents one logical source/document.

ai_knowledge_chunk represents the retrievable semantic units and contains pgvector embeddings.

Do not create separate vector tables per business entity.

SCHEMA

ai_knowledge_sources:

- id UUID primary key
- case_record_id nullable
- source_type
- source_table nullable
- source_id nullable
- external_id nullable
- title nullable
- mime_type nullable
- storage_uri nullable
- content_hash nullable
- source_metadata JSONB
- status
- created_on
- created_by
- modified_on
- modified_by
- modification_version

Add suitable indexes and uniqueness constraints.

ai_knowledge_chunks:

- id UUID primary key
- document_id FK
- case_record_id nullable
- chunk_index
- content
- content_hash
- token_count nullable
- embedding VECTOR(N)
- embedding_model
- embedding_version
- metadata JSONB
- created_on
- created_by
- modified_on
- modified_by
- modification_version

N must be configurable and must match the configured embedding model.

Add HNSW cosine similarity index.

Add B-tree indexes for:

- case_record_id
- document_id
- source identifiers
- tenant/agency identifier if required by the existing AgencyBase architecture

FIRST inspect the existing AgencyBase and tenant/agency model before defining these columns.

IMPORTANT DESIGN PRINCIPLES

1. Existing business tables remain the system of record.
2. AI knowledge tables are derived/indexed data.
3. The ingestion pipeline must be idempotent.
4. Never re-embed unchanged content.
5. Use SHA256 content hashes.
6. Store embedding model/version.
7. Store chunking version.
8. Store projection version.
9. Support incremental re-indexing.
10. Support deletes/superseded documents.
11. Preserve source identity and lineage.
12. Do not embed sensitive fields such as SSNs, payment card details, or similarly sensitive identifiers unless explicitly required.
13. Prefer metadata filtering over putting identifiers solely into embeddings.
14. Never rely on vector similarity for tenant isolation.
15. Do not hold SQL transactions open while calling external embedding APIs.

SEMANTIC PROJECTION LAYER

Do not directly serialize SQLAlchemy models into embeddings.

Implement semantic projectors:

- CaseRecordProjector
- PartyProjector
- AddressProjector
- ChargeProjector
- AppearanceProjector
- DispositionProjector
- SanctionProjector
- PaymentProjector
- CriminalProjector
- VehicleProjector
- DocumentProjector

A projector converts a business object into a normalized semantic representation.

Example:

CaseRecordProjector should produce natural-language structured content containing useful semantic fields:

Case Number
Case Type
Case Status
Case Title
Incident Date
Incident Location
Issuer
Hearing information
Additional Notes

It should not dump internal IDs or irrelevant DB implementation details.

RELATIONSHIP-AWARE REPRESENTATIONS

The system must preserve relational context.

Do not embed each entity as an isolated record only.

For example, a charge should be projected with relevant case context and, where appropriate, disposition and sanction context.

A hearing/appearance should contain:

- case
- hearing type
- hearing date/time when available
- result
- hearing notes
- status
- legal representative when appropriate

Build composite case summary documents for high-level retrieval.

DATABASE SOURCE ADAPTERS

Implement source adapters for structured records.

Each adapter should:

- discover records
- load required relationships efficiently
- create/update knowledge documents
- generate semantic content
- calculate content hash
- chunk content if needed
- generate embeddings
- bulk upsert chunks

Avoid N+1 queries.

Use SQLAlchemy eager loading/selectinload/joinedload where appropriate.

Keep DB loading separate from embedding calls.

FILE SOURCE ADAPTERS

Implement a common interface:

KnowledgeSource
NormalizedDocument

Support:

- PDF
- DOCX
- TXT
- image/OCR when available

Normalize all extracted data into the same pipeline as DB content.

The file ingestion flow should be:

file
→ parser
→ normalized document
→ content cleaning
→ metadata enrichment
→ chunking
→ embedding
→ knowledge_chunk

For PDFs retain page number and useful section metadata so retrieval can provide source provenance.

FILE STORAGE

Do not store the raw file inside PostgreSQL.

Keep binary files in the existing object storage system and store storage URI/key metadata in ai_knowledge_source.

CHUNKING

Use different strategies for structured records and large documents.

Structured entities:

- generally one logical entity per semantic unit

Large files:

- token-aware chunking
- configurable chunk size
- configurable overlap
- preserve page/section metadata

Make chunking configurable and versioned.

EMBEDDING SERVICE

Create:

EmbeddingProvider

with:

embed_documents(...)
embed_query(...)

Do not couple the pipeline directly to one vendor.

Implement the existing application's preferred provider first.

Batch document embeddings.

Never make one external API call per chunk when batching is possible.

VECTOR STORAGE

Use pgvector through the official SQLAlchemy integration.

Use cosine distance by default.

Create the required HNSW index.

Use metadata filters and B-tree indexes appropriately.

RETRIEVAL

Implement:

1. Exact/entity retrieval
2. Semantic vector retrieval
3. Relational expansion
4. Optional reranking
5. Context building

Do not implement vector-only RAG.

For example:

Query:
"What happened at John's hearing in case CE-123?"

The system should:

1. Resolve case number CE-123 exactly.
2. Resolve party/entity John.
3. Retrieve hearing/appearance records.
4. Perform semantic retrieval over hearing notes/documents.
5. Expand related entities.
6. Build grounded context.
7. Return ranked sources.

RETRIEVAL API

Create a service similar to:

retrieve(
    query: str,
    case_record_id: int | None = None,
    tenant_id: str | None = None,
    source_types: list[str] | None = None,
    top_k: int = 20,
)

Return:

- chunk
- similarity
- source metadata
- case metadata
- document metadata

Then implement a context builder that converts results into structured LLM context.

INGESTION

Implement:

ingest_case(case_id)

and:

ingest_document(document_id)

also provide:

reindex_case(case_id)
reindex_document(document_id)
delete_case_index(case_id)

The pipeline must be idempotent.

If content_hash + embedding_model + projection_version + chunking_version have not changed, skip re-embedding.

VERSIONING

Store:

embedding_model
embedding_version
projection_version
chunking_version
parser_version

in metadata/database fields.

Allow re-indexing by version.

OBSERVABILITY

Log/trace:

- ingestion ID
- case ID
- document ID
- source type
- number of chunks
- embedding model
- embedding latency
- parsing latency
- failures
- retry attempts

Add metrics where the application's existing observability stack supports them.

ERROR HANDLING

One bad document must not abort a complete case ingestion.

Use document-level failure states:

PENDING
PROCESSING
COMPLETED
FAILED
DELETED
SUPERSEDED

Store error information for failures.

ASYNC/DATABASE SAFETY

The application uses SQLAlchemy async.

Do not keep DB transactions open during external embedding requests.

Use:

DB read transaction
→ projection
→ commit/close
→ embedding API
→ new DB transaction
→ bulk upsert

MIGRATIONS

Create proper Alembic migrations.

Do not manually modify production schema.

Include:

- CREATE EXTENSION vector
- knowledge tables
- indexes
- constraints

TESTS

Create unit tests for:

- semantic projection
- relationship context construction
- hashing
- chunking
- idempotency
- embedding provider
- metadata generation

Create integration tests for:

- pgvector insertion
- vector similarity search
- filtered search
- case-level retrieval
- document retrieval
- deletion/supersession
- reindexing

Add a retrieval evaluation fixture with example queries and expected source records.

PERFORMANCE

Avoid:

- N+1 relationship queries
- one embedding request per chunk
- one DB insert per chunk
- global vector search when case/tenant filters are known

Use bulk inserts/upserts and eager loading.

REUSE EXISTING SYSTEMS

Before implementing anything:

1. Inspect existing Qdrant/vector-store code.
2. Inspect current document/attachment models.
3. Inspect S3/object-storage helpers.
4. Inspect embedding provider configuration.
5. Inspect existing LangChain/LangGraph integration.
6. Inspect AgencyBase and tenant isolation.
7. Inspect task queue/background processing infrastructure.
8. Inspect Alembic setup.

Reuse existing parsers, embedding providers, metadata conventions and tracing where practical.

DO NOT rewrite existing application architecture unnecessarily.

MIGRATION STRATEGY

Do not immediately embed the entire database.

Implement in this order:

Phase 1:
pgvector + knowledge tables

Phase 2:
CaseRecord + PartyDetail + CaseCharge + CaseAppearance

Phase 3:
related entities

Phase 4:
PDF/DOCX/attachments

Phase 5:
hybrid retrieval

Phase 6:
reranking/evaluation

Phase 7:
incremental/event-driven ingestion

DELIVERABLES

Produce:

1. Alembic migrations
2. SQLAlchemy models
3. semantic projector framework
4. DB source adapters
5. file parsers/adapters
6. chunking module
7. embedding provider abstraction
8. ingestion service
9. retrieval service
10. context builder
11. tests
12. CLI/scripts to backfill cases/documents
13. configuration/env variables
14. documentation
15. sample retrieval queries

IMPORTANT

Before writing code, inspect the existing repository and identify the actual locations of:

- SQLAlchemy models
- AsyncSession setup
- AgencyBase
- file/document models
- S3 helpers
- existing Qdrant integration
- existing embedding integration
- existing LangGraph/RAG code
- Alembic setup
- background task processing

Then provide an implementation plan referencing actual repository paths.

Do not invent existing files or APIs.

Implement in small commits/steps and preserve backward compatibility with the existing application.