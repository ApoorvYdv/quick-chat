from logging.config import fileConfig

from alembic import context
from sqlalchemy import MetaData, engine_from_config, pool

from quick_chat.core.models.config.config import ConfigBase
from quick_chat.migrations.utils import add_optimistic_lock_directives, ensure_schema
from quick_chat.settings.config import settings

# Alembic config
config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Original metadata
config_metadata = ConfigBase.metadata

# Merge metadata
merged_metadata = MetaData()


def add_tables_to_metadata(source_metadata, target_metadata):
    for table in source_metadata.tables.values():
        key = f"{table.schema}.{table.name}" if table.schema else table.name
        if key not in target_metadata.tables:
            table.to_metadata(target_metadata)


add_tables_to_metadata(config_metadata, merged_metadata)


# Include only tables defined in merged metadata
def include_object(obj, name, type_, reflected, compare_to):
    if type_ != "table":
        return True

    if name == "alembic_version":
        return False

    schema = obj.schema

    # Only config schema tables
    if schema != "config":
        return False

    key = f"{schema}.{name}" if schema else name

    # Present in metadata
    if key in merged_metadata.tables:
        return True

    # Reflected-only tables => allow drops
    if reflected and compare_to is None:
        return True

    return False


# Run migrations online
def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # Ensure all schemas exist
        schemas = {
            table.schema for table in merged_metadata.tables.values() if table.schema
        }

        for schema in schemas:
            ensure_schema(schema)

        def _process_revision_directives(ctx, rev, directives):
            for schema in schemas:
                add_optimistic_lock_directives(directives, schema, merged_metadata)

        context.configure(
            connection=connection,
            target_metadata=merged_metadata,
            include_object=include_object,
            include_schemas=True,
            transaction_per_migration=True,
            process_revision_directives=_process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()

        connection.close()


# Entrypoint
if context.is_offline_mode():
    raise Exception("Offline mode not supported for multi-schema setup.")
else:
    run_migrations_online()
