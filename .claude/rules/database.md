# Database Rules

## Database

Quick Chat uses PostgreSQL hosted on Tiger Cloud.

SQLAlchemy is the application's ORM/database abstraction.

Use the existing async database session and engine infrastructure.

Do not create ad-hoc database engines or connection pools.

## Critical Model Rule

Do not modify files under:

```text
src/quick_chat/core/models/
```

unless the user explicitly asks for a model change.

Do not:

- Add columns
- Remove columns
- Change relationships
- Change constraints
- Change indexes
- Change table names
- Change existing model behavior

If a feature appears to require a model change, explain why and ask for approval before making it.

## Multi-Tenancy

Agency schemas are a security boundary.

Use the existing `session_context()` and schema translation mechanism.

Never:

- Hardcode an agency schema into application queries.
- Interpolate an agency/schema name into raw SQL.
- Query multiple agencies and filter them afterward in Python.

Tenant filtering must happen at the database/query layer.

## Active Records

The application has a global `is_active` filtering mechanism.

Do not duplicate the filter unnecessarily.

If inactive records are intentionally required, use the project's existing `include_inactive` execution options.

## SQLAlchemy

Prefer SQLAlchemy 2.x style queries:

```python
stmt = select(CaseRecord).where(
    CaseRecord.id == case_id
)

result = await session.execute(stmt)
case = result.scalar_one_or_none()
```

Avoid legacy query patterns.

Use appropriate loading strategies such as `selectinload` and `joinedload` when relationships are required.

Avoid N+1 queries.

## Raw SQL

Use SQLAlchemy ORM/Core by default.

Raw SQL is acceptable when PostgreSQL-specific behavior or pgvector functionality makes it appropriate.

Always parameterize values.

Never construct SQL using string interpolation with user input.

## Performance

Before adding a query:

- Check expected row count.
- Check filtering.
- Check existing indexes.
- Avoid unnecessary columns.
- Avoid unnecessary relationship loading.
- Use pagination for large result sets.

For performance-sensitive queries, inspect the generated SQL/query plan rather than optimizing blindly.
