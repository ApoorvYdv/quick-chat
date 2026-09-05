from alembic import context
from alembic.autogenerate import comparators, renderers
from alembic.operations import MigrateOperation, Operations
from alembic.operations import ops as alembic_ops
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from quick_chat.utils.database.engine import engine


def ensure_schema(schema: str):
    session = Session(engine)
    session.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))
    session.commit()
    session.close()


def get_agency_schemas():
    session = Session(engine)
    result = session.execute(
        text("SELECT name FROM config.agencies ORDER BY agency_id")
    )
    schemas = [row[0] for row in result]
    session.close()
    return schemas


# Version Table Helpers (Using Alembic's own DB Connection)
def ensure_version_table(schema: str | None):
    bind = context.get_bind()
    bind.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema}"))

    # Create version table if needed
    bind.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS {schema}.alembic_version (
                version_num VARCHAR(32)
            );
        """
        )
    )


def create_optimistic_lock_trigger(table_name: str, schema: str | None) -> None:
    """Create the optimistic_lock trigger on a table, skipping if it already exists."""
    from alembic import op

    op.execute(
        f"""
        DO $$
        BEGIN
            CREATE TRIGGER optimistic_lock
            BEFORE UPDATE ON {schema}.{table_name}
            FOR EACH ROW
            EXECUTE FUNCTION check_version_no();
        EXCEPTION
            WHEN duplicate_object THEN
                NULL;
        END $$;
        """
    )


def drop_optimistic_lock_trigger(table_name: str, schema: str | None) -> None:
    """Drop the optimistic_lock trigger from a table if it exists."""
    from alembic import op

    op.execute(f"DROP TRIGGER IF EXISTS optimistic_lock ON {schema}.{table_name};")


# ── New: custom op classes so autogenerate emits the calls above ───────────────
@Operations.register_operation("create_optimistic_lock_trigger")
class CreateOptimisticLockTriggerOp(MigrateOperation):
    def __init__(self, table_name: str, schema: str):
        self.table_name = table_name
        self.schema = schema

    @classmethod
    def create_optimistic_lock_trigger(cls, operations, table_name: str, schema: str):
        return operations.invoke(cls(table_name, schema))

    def reverse(self):
        return DropOptimisticLockTriggerOp(self.table_name, self.schema)


@Operations.register_operation("drop_optimistic_lock_trigger")
class DropOptimisticLockTriggerOp(MigrateOperation):
    def __init__(self, table_name: str, schema: str):
        self.table_name = table_name
        self.schema = schema

    @classmethod
    def drop_optimistic_lock_trigger(cls, operations, table_name: str, schema: str):
        return operations.invoke(cls(table_name, schema))

    def reverse(self):
        return CreateOptimisticLockTriggerOp(self.table_name, self.schema)


@Operations.implementation_for(CreateOptimisticLockTriggerOp)
def _run_create(operations, op: CreateOptimisticLockTriggerOp):
    create_optimistic_lock_trigger(op.table_name, op.schema)


@Operations.implementation_for(DropOptimisticLockTriggerOp)
def _run_drop(operations, op: DropOptimisticLockTriggerOp):
    drop_optimistic_lock_trigger(op.table_name, op.schema)


# ── New: autogenerate hook ─────────────────────────────────────────────────────
def _process_ops(op_list, schema: str, metadata, upgrade: bool):
    inserts = []

    for i, op in enumerate(op_list):
        if upgrade and isinstance(op, alembic_ops.CreateTableOp):
            table_schema = op.schema or schema
            #  only handle tables that belong to THIS schema iteration
            if table_schema != schema:
                continue
            inserts.append(
                (i + 1, CreateOptimisticLockTriggerOp(op.table_name, table_schema))
            )

        elif not upgrade and isinstance(op, alembic_ops.DropTableOp):
            table_schema = op.schema or schema
            #  same guard for drop
            if table_schema != schema:
                continue
            table = metadata.tables.get(f"{table_schema}.{op.table_name}")
            if table is None:
                table = metadata.tables.get(op.table_name)

            if table is not None:
                inserts.append(
                    (i, DropOptimisticLockTriggerOp(op.table_name, table_schema))
                )

    for i, op in reversed(inserts):
        op_list.insert(i, op)


def add_optimistic_lock_directives(directives, schema: str, metadata):
    for directive in directives:
        for migration_script in directive.upgrade_ops_list:
            _process_ops(migration_script.ops, schema, metadata, upgrade=True)
        for migration_script in directive.downgrade_ops_list:
            _process_ops(migration_script.ops, schema, metadata, upgrade=False)


@renderers.dispatch_for(CreateOptimisticLockTriggerOp)
def render_create_optimistic_lock_trigger(autogen_context, op):
    autogen_context.imports.add(
        "from court_cms_api.migrations.utils import create_optimistic_lock_trigger"
    )
    version_schema = autogen_context.migration_context.version_table_schema
    if version_schema and op.schema == version_schema:
        autogen_context.imports.add("from alembic import context")
        schema_expr = "context.get_context().version_table_schema"
    else:
        schema_expr = repr(op.schema)

    return f"create_optimistic_lock_trigger({op.table_name!r}, {schema_expr})"


@renderers.dispatch_for(DropOptimisticLockTriggerOp)
def render_drop_optimistic_lock_trigger(autogen_context, op):
    autogen_context.imports.add(
        "from court_cms_api.migrations.utils import drop_optimistic_lock_trigger"
    )
    version_schema = autogen_context.migration_context.version_table_schema
    if version_schema and op.schema == version_schema:
        autogen_context.imports.add("from alembic import context")
        schema_expr = "context.get_context().version_table_schema"
    else:
        schema_expr = repr(op.schema)

    return f"drop_optimistic_lock_trigger({op.table_name!r}, {schema_expr})"


@comparators.dispatch_for("schema")
def compare_optimistic_lock_triggers(autogen_context, upgrade_ops, schemas):
    conn = autogen_context.connection
    metadata = autogen_context.metadata
    version_schema = autogen_context.migration_context.version_table_schema
    if version_schema:
        metadata_schemas = {version_schema}
    else:
        metadata_schemas = {
            table.schema for table in metadata.tables.values() if table.schema
        }

    if not metadata_schemas:
        current = conn.execute(text("SELECT current_schema()")).scalar()
        if current:
            metadata_schemas.add(current)

    for schema in metadata_schemas:
        expected_tables = {
            table.name
            for table in metadata.tables.values()
            if (
                table.schema == schema
                or (table.schema is None and schema == version_schema)
            )
        }

        existing_tables = set(
            conn.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = :schema
                    AND table_type = 'BASE TABLE'
                    """
                ),
                {"schema": schema},
            )
            .scalars()
            .all()
        )

        expected_tables = expected_tables & existing_tables

        existing_triggers = set(
            conn.execute(
                text(
                    """
                    SELECT event_object_table
                    FROM information_schema.triggers
                    WHERE trigger_schema = :schema
                    AND trigger_name = 'optimistic_lock'
                    """
                ),
                {"schema": schema},
            )
            .scalars()
            .all()
        )

        for table_name in sorted(expected_tables - existing_triggers):
            upgrade_ops.ops.append(CreateOptimisticLockTriggerOp(table_name, schema))

        for table_name in sorted(existing_triggers - expected_tables):
            upgrade_ops.ops.append(DropOptimisticLockTriggerOp(table_name, schema))