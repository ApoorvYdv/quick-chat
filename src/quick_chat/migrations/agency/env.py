from logging.config import fileConfig

import sqlalchemy as sa
from alembic import context
from sqlalchemy import engine_from_config, pool, text

from quick_chat.core.models.agency.agency import AgencyBase
from quick_chat.migrations.utils import (
    add_optimistic_lock_directives,
    ensure_schema,
    ensure_version_table,
    get_agency_schemas,
)
from quick_chat.settings.config import settings

# Alembic config
config = context.config
config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)

# Logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

agency_metadata = AgencyBase.metadata

agency_table_names = set(agency_metadata.tables.keys())


# include_object helpers
def include_object(obj, name, type_, reflected, compare_to):
    if type_ != "table":
        return True

    if name == "alembic_version":
        return False

    # Keep tables that exist in metadata
    if name in agency_table_names:
        return True

    # Keep reflected-only tables so drops can be detected
    if reflected and compare_to is None:
        return True

    return False


def compare_type(
    context_, inspected_column, metadata_column, inspected_type, metadata_type
):
    if isinstance(inspected_type, sa.JSON):
        return False
    return None


# Core Migration Online
def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    target_schemas = get_agency_schemas()
    for schema in target_schemas:
        ensure_schema(schema)

    is_autogenerate = getattr(config.cmd_opts, "autogenerate", False)

    with connectable.connect() as connection:
        # AUTOGENERATE MODE (Revision Creation)
        if is_autogenerate:
            representative_schema = target_schemas[0]

            connection.execute(
                text(f"SET search_path TO {representative_schema}, public")
            )
            connection.commit()

            context.configure(
                connection=connection,
                target_metadata=agency_metadata,
                version_table_schema=representative_schema,
                include_object=include_object,
                include_schemas=False,
                compare_type=compare_type,
                compare_server_default=False,
                process_revision_directives=lambda ctx, rev, directives: (
                    add_optimistic_lock_directives(
                        directives, representative_schema, agency_metadata
                    )
                ),
            )
            # Ensure version table exists just in case
            ensure_version_table(representative_schema)

            with context.begin_transaction():
                context.run_migrations()

            return

        for schema in target_schemas:
            print(f"=== Migrating AGENCY schema: {schema} ===")

            connection.execute(text(f"SET search_path TO {schema}, public"))
            connection.commit()

            context.configure(
                connection=connection,
                target_metadata=agency_metadata,
                version_table_schema=schema,
                include_schemas=False,
                compare_type=compare_type,
                compare_server_default=False,
                include_object=include_object,
            )

            ensure_version_table(schema)

            with context.begin_transaction():
                context.run_migrations()


# Entrypoint
if context.is_offline_mode():
    run_migrations_online()
else:
    run_migrations_online()
